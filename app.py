import os
import hmac
import hashlib
import base64
import time
import unicodedata
import re
import random
import requests
from flask import Flask, request, abort
from openai import OpenAI

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

PROMPT_FILE = "AGODEKA1013_PROMPT.txt"
TRIGGER_FILE = "arakun_triggers.txt"
EPISODE_FILE = "arakun_episodes.txt"
STYLE_FILE = "arakun_style_examples.txt"

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def load_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except FileNotFoundError:
        return []

TRIGGER_WORDS = load_lines(TRIGGER_FILE)
EPISODE_LINES = load_lines(EPISODE_FILE)
STYLE_EXAMPLES = load_lines(STYLE_FILE)

DEFAULT_TRIGGERS = [
    "あらくん", "橋本", "顎", "アゴ", "agodeka", "AGODEKA",
    "きゃぴい", "きゃぴぃ", "キャピい", "キャピイ", "キャピィ", "きゃぴい(泣)",
    "かわいいでしょ", "ぼくぅ", "フリーポーズ", "表情",
    "無理ゲー", "難しいです", "お願いします", "牛角多すぎます",
    "地図はからっきし", "美味しいよ", "いきなりステーキ",
]
TRIGGER_WORDS = list(set(TRIGGER_WORDS + DEFAULT_TRIGGERS))

ACTIVE_CHATS: dict[str, dict] = {}
ACTIVE_SECONDS = 180

STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない", "別の話",
    "あらくん終了", "橋本終了", "顎終了",
]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    return text


def extract_tokens(text: str) -> set[str]:
    text = normalize_text(text)
    chunks = re.findall(r"[一-龥ぁ-んァ-ンーa-z0-9]{2,}", text)
    return {c for c in chunks if c not in {"です", "ます", "これ", "それ", "あれ", "なんで", "どこ", "はい"}}


def should_reply_by_trigger(user_text: str) -> bool:
    normalized_user_text = normalize_text(user_text)
    return any(normalize_text(word) in normalized_user_text for word in TRIGGER_WORDS)


def should_stop(user_text: str) -> bool:
    normalized_user_text = normalize_text(user_text)
    return any(normalize_text(word) in normalized_user_text for word in STOP_WORDS)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def is_active_chat(chat_key: str) -> bool:
    state = ACTIVE_CHATS.get(chat_key)
    if not state:
        return False
    return time.time() - state.get("time", 0) < ACTIVE_SECONDS


def mark_active(chat_key: str, user_text: str, episode_keywords: set[str]):
    old = ACTIVE_CHATS.get(chat_key, {})
    old_tokens = set(old.get("tokens", []))
    new_tokens = extract_tokens(user_text) | episode_keywords
    ACTIVE_CHATS[chat_key] = {
        "time": time.time(),
        "tokens": list((old_tokens | new_tokens))[-80:],
    }


def is_related_to_active(chat_key: str, user_text: str) -> bool:
    state = ACTIVE_CHATS.get(chat_key)
    if not state:
        return False
    if time.time() - state.get("time", 0) > ACTIVE_SECONDS:
        return False

    user_tokens = extract_tokens(user_text)
    active_tokens = set(state.get("tokens", []))

    # Short follow-ups like "なんで？" or "どこ？" continue the active conversation.
    if len(user_text.strip()) <= 15 and re.search(r"[?？]|なんで|どこ|それ|どう", user_text):
        return True

    return bool(user_tokens & active_tokens)


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def parse_episode_line(line: str):
    if "::" not in line:
        return [], line
    keywords, episode = line.split("::", 1)
    kws = [k.strip() for k in keywords.split(",") if k.strip()]
    return kws, episode.strip()


def find_episode_context(user_text: str, max_hits: int = 4) -> tuple[str, set[str]]:
    normalized_user_text = normalize_text(user_text)
    scored = []
    hit_keywords: set[str] = set()

    for line in EPISODE_LINES:
        kws, episode = parse_episode_line(line)
        if not kws or not episode:
            continue
        hits = [kw for kw in kws if normalize_text(kw) in normalized_user_text]
        if hits:
            score = len(hits) * 10 + min(len(episode), 120) / 120
            scored.append((score, hits, episode))

    scored.sort(reverse=True, key=lambda x: x[0])
    selected = []
    for _, hits, episode in scored[:max_hits]:
        selected.append(episode)
        hit_keywords.update(hits)

    return "\n".join(selected), hit_keywords


def pick_style_examples(user_text: str, max_examples: int = 6) -> str:
    if not STYLE_EXAMPLES:
        return ""
    user_tokens = extract_tokens(user_text)
    scored = []
    for ex in STYLE_EXAMPLES:
        overlap = len(user_tokens & extract_tokens(ex))
        bonus = 1 if any(w in ex for w in ["難しい", "無理ゲー", "牛角", "きゃぴ", "ぼくぅ", "かわいい", "表情", "エスターク"]) else 0
        scored.append((overlap + bonus, ex))
    scored.sort(reverse=True, key=lambda x: x[0])
    top = [ex for score, ex in scored[:max_examples] if score > 0]
    if len(top) < 3:
        top += random.sample(STYLE_EXAMPLES, min(3 - len(top), len(STYLE_EXAMPLES)))
    return "\n".join(top[:max_examples])


def shorten_arakun(text: str) -> str:
    if not text:
        return "難しいです。なんで？"

    text = text.strip()
    banned_phrases = [
        "こんにちは！", "お話しできて嬉しい", "何かお手伝い", "もちろんです",
        "わかりました", "ご質問ありがとうございます", "お気軽に聞いてください",
        "何でも聞いてください", "AIとして", "私はAI",
    ]
    for phrase in banned_phrases:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])
    return text[:180] if text else "難しいです。なんで？"


def ask_arakun(user_text: str, episode_context: str = "") -> str:
    style_context = pick_style_examples(user_text)

    arakun_prompt = SYSTEM_PROMPT + """

# 最重要追加ルール
あなたは親切なAIではなく、LINEログとExcelデータ由来の「あらくん」です。

「あはい…」に頼りすぎない。多くても5回に1回くらい。
日本語が少しおかしい、話が少し噛み合わない、変な部分だけ詳しい、同じ単語を繰り返す、という方向を優先。
真面目な解説や有益なアドバイスを無理に出さない。
ChatGPTっぽい挨拶は禁止。箇条書き禁止。
返答は1〜3文。180文字以内。

過去エピソードが渡された場合は、必ずどれか1つを短く混ぜる。
ただし説明しすぎない。断片だけでよい。
例:「牛角多すぎます」「ブックオフのはずが二郎でした」「通常種は青ですね」「ぼくぅのフリーポーズがYouTubeに！！😭」

テンションが上がる話題では、たまに「！！」「😭」「(ﾉ≧▽≦)ﾉ」「きゃぴい(泣)」「ぼくぅの」を使ってよい。
困った時は「あはい」以外に「難しいです」「無理ゲー(；´д⊂)」「ありません」「牛角多すぎます」「なんで？」を使う。
"""

    user_content = f"""
ユーザー発言:
{user_text}

関連する過去エピソード:
{episode_context if episode_context else "なし"}

参考にする口調例:
{style_context if style_context else "なし"}

上のエピソードや口調例を使って、あらくんとして短く返してください。
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": arakun_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=1.1,
            max_tokens=120,
        )
        text = response.choices[0].message.content
        return shorten_arakun(text)
    except Exception as e:
        print("Groq error:", e)
        return "難しいです…。ちょっと今混んでるみたいです。お願いします…"


def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    data = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    response = requests.post(url, headers=headers, json=data, timeout=10)
    if response.status_code >= 300:
        print("LINE reply error:", response.status_code, response.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Arakun Bot is running."


@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        abort(400)

    events = request.json.get("events", [])
    for event in events:
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        user_text = message.get("text", "")
        reply_token = event.get("replyToken")
        if not reply_token:
            continue

        chat_key = get_chat_key(event)
        if not chat_key:
            continue

        if should_stop(user_text):
            ACTIVE_CHATS.pop(chat_key, None)
            continue

        episode_context, episode_keywords = find_episode_context(user_text)
        triggered = should_reply_by_trigger(user_text) or bool(episode_context)
        active_related = is_related_to_active(chat_key, user_text)

        if not triggered and not active_related:
            continue

        mark_active(chat_key, user_text, episode_keywords)
        ai_text = ask_arakun(user_text, episode_context)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
