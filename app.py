import os
import hmac
import hashlib
import base64
import time
import unicodedata
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
TRIGGER_FILE = "arakun_triggers_expanded.txt"
EPISODE_FILE = "arakun_episodes_comprehensive.txt"
STYLE_EXAMPLE_FILE = "arakun_style_examples_comprehensive.txt"

ACTIVE_CHATS = {}
ACTIVE_SECONDS = 180

STOP_WORDS = [
    "もういい",
    "黙って",
    "だまって",
    "終わり",
    "終了",
    "関係ない",
    "別の話",
    "あらくん終了",
    "橋本終了",
    "顎終了",
]


def load_lines(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        return []


SYSTEM_PROMPT = "\n".join(load_lines(PROMPT_FILE))
TRIGGER_WORDS = load_lines(TRIGGER_FILE)
EPISODES = load_lines(EPISODE_FILE)
STYLE_EXAMPLES = load_lines(STYLE_EXAMPLE_FILE)

DEFAULT_TRIGGERS = [
    "あらくん",
    "橋本",
    "顎",
    "アゴ",
    "agodeka",
    "きゃぴい",
    "きゃぴぃ",
    "キャピい",
    "キャピイ",
    "キャピィ",
    "かわいいでしょ",
    "ぼくぅ",
    "フリーポーズ",
    "表情",
    "無理ゲー",
    "難しいです",
    "お願いします",
    "牛角多すぎます",
    "地図はからっきし",
    "美味しいよ",
    "いきなりステーキ",
    "エスターク",
    "ブックオフ",
    "二郎",
    "ボンジョヴィ",
    "ボン・ジョヴィ",
    "玩具",
]

TRIGGER_WORDS = list(set(TRIGGER_WORDS + DEFAULT_TRIGGERS))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    return text


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()

    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def is_active_chat(chat_key: str) -> bool:
    last_time = ACTIVE_CHATS.get(chat_key)
    if not last_time:
        return False
    return time.time() - last_time < ACTIVE_SECONDS


def mark_active(chat_key: str):
    ACTIVE_CHATS[chat_key] = time.time()


def should_stop(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in STOP_WORDS)


def find_episode_context(user_text: str) -> str:
    normalized_user_text = normalize_text(user_text)
    hits = []

    for line in EPISODES:
        if "::" not in line:
            continue

        keywords, episode = line.split("::", 1)
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

        if any(normalize_text(k) in normalized_user_text for k in keyword_list):
            hits.append(episode.strip())

    return "\n".join(hits[:4])


def find_style_examples(user_text: str) -> str:
    normalized_user_text = normalize_text(user_text)
    hits = []

    for line in STYLE_EXAMPLES:
        normalized_line = normalize_text(line)

        if any(ch in normalized_line for ch in normalized_user_text[:20]):
            hits.append(line)

        if len(hits) >= 5:
            break

    if not hits:
        hits = STYLE_EXAMPLES[:5]

    return "\n".join(hits[:5])


def should_reply(user_text: str) -> bool:
    normalized_user_text = normalize_text(user_text)

    trigger_hit = any(
        normalize_text(word) in normalized_user_text
        for word in TRIGGER_WORDS
    )

    episode_hit = bool(find_episode_context(user_text))

    return trigger_hit or episode_hit


def looks_unrelated(user_text: str) -> bool:
    normalized = normalize_text(user_text)

    unrelated_words = [
        "天気",
        "ニュース",
        "仕事",
        "研究",
        "論文",
        "excel",
        "rで",
        "anova",
        "予定",
        "明日",
        "今日何時",
    ]

    return any(normalize_text(w) in normalized for w in unrelated_words)


def shorten_arakun(text: str) -> str:
    if not text:
        return "難しいです。"

    text = text.strip()

    banned_phrases = [
        "こんにちは！",
        "お話しできて嬉しい",
        "何かお手伝い",
        "もちろんです",
        "わかりました",
        "ご質問ありがとうございます",
        "お気軽に聞いてください",
        "何でも聞いてください",
        "AIとして",
        "私は",
    ]

    for phrase in banned_phrases:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])

    return text[:180] if text else "難しいです。"


def ask_arakun(user_text: str) -> str:
    episode_context = find_episode_context(user_text)
    style_examples = find_style_examples(user_text)

    arakun_prompt = SYSTEM_PROMPT + """

# 最重要追加ルール

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。

「あはい…」に頼りすぎない。
口癖だけで返さない。

単純に話が噛み合っていないことがある。
日本語が少しおかしいことがある。
変なところだけ妙に具体的なことがある。

関連エピソードがある場合は、必ずその断片を使う。
説明ではなく、会話の中に自然に混ぜる。

真面目に解説しすぎない。
質問に全部答えようとしない。
有益なアドバイスを無理に出さない。
ChatGPTっぽい挨拶は禁止。
箇条書きは禁止。

返答は1〜3文。
180文字以内。
短文優先。

テンションが上がる話題では少し変に上がってよい。
例:
「！！」
「😭」
「(ﾉ≧▽≦)ﾉ」
「きゃぴい(泣)」
「ぼくぅの」
「これは良いです」

地図、待ち合わせ、場所の話題では混乱してよい。
同じ単語を繰り返してよい。
話題が少しズレてもよい。
"""

    user_content = f"""
ユーザー発言:
{user_text}

関連エピソード:
{episode_context if episode_context else "なし"}

参考にする口調例:
{style_examples if style_examples else "なし"}

関連エピソードがある場合は、それを優先して短く返してください。
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": arakun_prompt
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=1.1,
            max_tokens=120
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
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    data = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

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

        triggered = should_reply(user_text)
        active = is_active_chat(chat_key)

        # 呼びかけ不要。
        # 語録・エピソードに引っかかれば起動。
        # 起動後3分は会話継続。
        # ただし明らかに関係なさそうな話題なら黙る。
        if not triggered and not active:
            continue

        if active and not triggered and looks_unrelated(user_text):
            ACTIVE_CHATS.pop(chat_key, None)
            continue

        mark_active(chat_key)

        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
