import os
import hmac
import hashlib
import base64
import time
import random
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
TRIGGER_FILE = "arakun_triggers_exhaustive.txt"
EPISODE_FILE = "arakun_episodes_exhaustive.txt"
STYLE_EXAMPLE_FILE = "arakun_style_examples_exhaustive.txt"
REPLY_PAIR_FILE = "arakun_reply_pairs_exhaustive.txt"
HASHIMOTO_SHIN_FILE = "hashimoto_shin_examples.txt"

ACTIVE_CHATS = {}
ACTIVE_MIN_SECONDS = 45
ACTIVE_MAX_SECONDS = 180

RANDOM_JOIN_PROBABILITY = 0.16
ACTIVE_STRONG_CONTEXT_PROBABILITY = 0.82
ACTIVE_WEAK_CONTEXT_PROBABILITY = 0.38

CALL_WORDS = [
    "あらくん", "あら君", "橋本", "橋本新", "顎", "アゴ", "あご",
    "AGODEKA", "agodeka", "LIAR", "ARAKUN",
]

STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "あらくん終了", "橋本終了", "橋本新終了", "顎終了",
]

UNRELATED_WORDS = [
    "天気", "ニュース", "仕事", "研究", "論文", "excel", "エクセル",
    "rで", "anova", "統計", "予定", "明日何時", "今日何時", "病院",
    "学会", "メール",
]


def load_lines(filename: str) -> list[str]:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except FileNotFoundError:
        return []


SYSTEM_PROMPT = "\n".join(load_lines(PROMPT_FILE))
TRIGGER_WORDS = load_lines(TRIGGER_FILE)
EPISODES = load_lines(EPISODE_FILE)
STYLE_EXAMPLES = load_lines(STYLE_EXAMPLE_FILE)
REPLY_PAIRS = load_lines(REPLY_PAIR_FILE)
HASHIMOTO_SHIN_EXAMPLES = load_lines(HASHIMOTO_SHIN_FILE)

DEFAULT_TRIGGERS = [
    "あらくん", "橋本", "橋本新", "新橋本", "新橋本新", "顎", "アゴ",
    "あご", "agodeka", "きゃぴい", "きゃぴぃ", "キャピい", "キャピイ",
    "キャピィ", "きゃっぴい", "かわいいでしょ", "ぼくぅ", "フリーポーズ",
    "表情", "無理ゲー", "難しいです", "お願いします", "牛角多すぎます",
    "地図はからっきし", "美味しいよ", "いきなりステーキ", "エスターク",
    "ブックオフ", "二郎", "野猿", "ボンジョヴィ", "ボン・ジョヴィ",
    "玩具", "ｷﾞｬｵｫ", "ギャオ", "トーマス", "アナザーアラクン",
    "橋本新名言集",
]

TRIGGER_WORDS = sorted(set(TRIGGER_WORDS + DEFAULT_TRIGGERS))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
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


def is_called(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in CALL_WORDS)


def should_stop(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in STOP_WORDS)


def looks_unrelated(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in UNRELATED_WORDS)


def mark_active(chat_key: str):
    ACTIVE_CHATS[chat_key] = {
        "time": time.time(),
        "ttl": random.randint(ACTIVE_MIN_SECONDS, ACTIVE_MAX_SECONDS),
    }


def is_active_chat(chat_key: str) -> bool:
    state = ACTIVE_CHATS.get(chat_key)
    if not state:
        return False
    return time.time() - state["time"] < state["ttl"]


def expire_chat(chat_key: str):
    ACTIVE_CHATS.pop(chat_key, None)


def keyword_overlap_score(user_text: str, line: str) -> int:
    u = normalize_text(user_text)
    if not u:
        return 0

    line_n = normalize_text(line)
    score = 0

    chunks = set()
    for n in (2, 3, 4):
        for i in range(max(0, len(u) - n + 1)):
            chunks.add(u[i:i+n])

    for chunk in chunks:
        if chunk and chunk in line_n:
            score += len(chunk)

    for word in TRIGGER_WORDS[:5000]:
        w = normalize_text(word)
        if w and w in u and w in line_n:
            score += 20

    if "橋本新" in user_text and "橋本新" in line:
        score += 50

    return score


def top_matches(user_text: str, lines: list[str], limit: int = 5, min_score: int = 4) -> list[str]:
    scored = []
    for line in lines:
        score = keyword_overlap_score(user_text, line)
        if score >= min_score:
            scored.append((score, line))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [line for _, line in scored[:limit]]


def find_episode_context(user_text: str) -> str:
    hits = []
    normalized_user = normalize_text(user_text)

    for line in EPISODES:
        if "::" not in line:
            continue

        keywords, episode = line.split("::", 1)
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

        if any(normalize_text(k) in normalized_user for k in keyword_list):
            hits.append(episode.strip())

        if len(hits) >= 6:
            break

    if len(hits) < 4:
        for line in top_matches(user_text, EPISODES, limit=4):
            if "::" in line:
                hits.append(line.split("::", 1)[1].strip())
            else:
                hits.append(line.strip())

    seen = set()
    unique = []
    for h in hits:
        h2 = h.strip()
        if h2 and h2 not in seen:
            unique.append(h2)
            seen.add(h2)

    return "\n".join(unique[:6])


def find_reply_examples(user_text: str) -> str:
    matches = top_matches(user_text, REPLY_PAIRS, limit=6, min_score=6)
    return "\n".join(matches[:6])


def find_style_examples(user_text: str) -> str:
    matches = top_matches(user_text, STYLE_EXAMPLES, limit=5, min_score=4)
    if not matches:
        matches = STYLE_EXAMPLES[:5]
    return "\n".join(matches[:5])


def find_hashimoto_shin_context(user_text: str) -> str:
    sources = []
    sources.extend(HASHIMOTO_SHIN_EXAMPLES)
    sources.extend([line for line in REPLY_PAIRS if "橋本新" in line][:400])
    sources.extend([line for line in EPISODES if "橋本新" in line][:400])
    sources.extend([line for line in STYLE_EXAMPLES if "橋本新" in line][:200])

    if not sources:
        return ""

    min_score = 3 if "橋本新" in user_text else 6
    matches = top_matches(user_text, sources, limit=5, min_score=min_score)
    return "\n".join(matches[:5])


def has_context_hit(user_text: str) -> bool:
    normalized = normalize_text(user_text)

    trigger_hit = any(
        normalize_text(word) in normalized
        for word in TRIGGER_WORDS
    )
    if trigger_hit:
        return True

    if find_episode_context(user_text):
        return True

    if find_hashimoto_shin_context(user_text):
        return True

    if top_matches(user_text, REPLY_PAIRS, limit=1, min_score=18):
        return True

    return False


def should_randomly_join(user_text: str) -> bool:
    if looks_unrelated(user_text):
        return False

    if not has_context_hit(user_text):
        return False

    normalized = normalize_text(user_text)
    strong_words = ["橋本新", "きゃぴ", "エスターク", "フリーポーズ", "牛角", "二郎"]
    if any(normalize_text(w) in normalized for w in strong_words):
        return random.random() < 0.30

    return random.random() < RANDOM_JOIN_PROBABILITY


def should_continue_active_chat(user_text: str) -> bool:
    if looks_unrelated(user_text):
        return False

    if has_context_hit(user_text):
        return random.random() < ACTIVE_STRONG_CONTEXT_PROBABILITY

    return random.random() < ACTIVE_WEAK_CONTEXT_PROBABILITY


def shorten_arakun(text: str) -> str:
    if not text:
        return "難しいです。"

    text = text.strip()

    banned_phrases = [
        "こんにちは！", "こんにちは。", "お話しできて嬉しい", "何かお手伝い",
        "もちろんです", "わかりました", "ご質問ありがとうございます",
        "お気軽に聞いてください", "何でも聞いてください", "AIとして",
        "私は", "以下の", "ポイントは",
    ]

    for phrase in banned_phrases:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])
    return text[:190] if text else "難しいです。"


def ask_arakun(user_text: str) -> str:
    episode_context = find_episode_context(user_text)
    reply_examples = find_reply_examples(user_text)
    style_examples = find_style_examples(user_text)
    hashimoto_shin_context = find_hashimoto_shin_context(user_text)

    arakun_prompt = SYSTEM_PROMPT + """

# Runtime rules

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。

ただし本人ではなく、会話データに基づくAIキャラクターです。
本人の現在地、連絡先、私生活、予定を事実として断定しない。

「あはい…」に頼りすぎない。
口癖だけで返さない。
過去ログにある返答パターンを優先する。

単純に話が噛み合っていないことがある。
日本語が少しおかしいことがある。
変なところだけ妙に具体的なことがある。
急にテンションが上がることがある。

関連エピソード、返答ペア、橋本新文脈がある場合は、それを優先して短く使う。
説明ではなく、LINEの返答として自然に混ぜる。

真面目に解説しすぎない。
質問に全部答えようとしない。
有益なアドバイスを無理に出さない。
ChatGPTっぽい挨拶は禁止。
箇条書きは禁止。

返答は1〜3文。
190文字以内。
短文優先。

テンションが上がる話題では使ってよい:
「！！」
「😭」
「(ﾉ≧▽≦)ﾉ」
「きゃぴい(泣)」
「ぼくぅの」
「ｷﾞｬｵｫ。」

地図、待ち合わせ、場所の話題では混乱してよい。
同じ単語を繰り返してよい。
話題が少しズレてもよい。
"""

    user_content = f"""
ユーザー発言:
{user_text}

関連エピソード:
{episode_context if episode_context else "なし"}

過去の似た返答ペア:
{reply_examples if reply_examples else "なし"}

橋本新として参照できる過去文脈:
{hashimoto_shin_context if hashimoto_shin_context else "なし"}

参考にする口調例:
{style_examples if style_examples else "なし"}

返答方針:
1. 直接呼ばれていたら必ず短く返す。
2. 過去の似た返答ペアがある場合は、それを最優先で真似る。
3. 関連エピソードや橋本新文脈がある場合は、断片を自然に混ぜる。
4. 解説ではなくLINEの一言として返す。
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": arakun_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=1.12,
            max_tokens=130
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
        "messages": [{"type": "text", "text": text}]
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
            expire_chat(chat_key)
            continue

        called = is_called(user_text)
        active = is_active_chat(chat_key)
        random_join = should_randomly_join(user_text)

        if called:
            mark_active(chat_key)
            ai_text = ask_arakun(user_text)
            reply_to_line(reply_token, ai_text)
            continue

        if active:
            if should_continue_active_chat(user_text):
                mark_active(chat_key)
                ai_text = ask_arakun(user_text)
                reply_to_line(reply_token, ai_text)
            continue

        if random_join:
            mark_active(chat_key)
            ai_text = ask_arakun(user_text)
            reply_to_line(reply_token, ai_text)
            continue

        continue

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
