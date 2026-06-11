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
TRIGGER_FILE = "arakun_triggers.txt"

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

try:
    with open(TRIGGER_FILE, "r", encoding="utf-8") as f:
        TRIGGER_WORDS = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]
except FileNotFoundError:
    TRIGGER_WORDS = []

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
    "あはい",
    "お願いします",
    "牛角多すぎます",
    "地図はからっきし",
    "美味しいよ",
    "いきなりステーキ",
]

TRIGGER_WORDS = list(set(TRIGGER_WORDS + DEFAULT_TRIGGERS))

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


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    return text


def should_reply(user_text: str) -> bool:
    normalized_user_text = normalize_text(user_text)

    return any(
        normalize_text(word) in normalized_user_text
        for word in TRIGGER_WORDS
    )


def should_stop(user_text: str) -> bool:
    normalized_user_text = normalize_text(user_text)
    return any(
        normalize_text(word) in normalized_user_text
        for word in STOP_WORDS
    )


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return (
        source.get("groupId")
        or source.get("roomId")
        or source.get("userId")
    )


def is_active_chat(chat_key: str) -> bool:
    last_time = ACTIVE_CHATS.get(chat_key)
    if not last_time:
        return False

    return time.time() - last_time < ACTIVE_SECONDS


def mark_active(chat_key: str):
    ACTIVE_CHATS[chat_key] = time.time()


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()

    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def shorten_arakun(text: str) -> str:
    if not text:
        return "あはい…。なんで？"

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
    ]

    for phrase in banned_phrases:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])

    return text[:180] if text else "あはい…。なんで？"


def ask_arakun(user_text: str) -> str:
    arakun_prompt = SYSTEM_PROMPT + """

# 最重要追加ルール

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。

真面目に解説しすぎない。
質問に全部答えようとしない。
有益なアドバイスを無理に出さない。
ChatGPTっぽい挨拶は禁止。
箇条書きは禁止。

返答は1〜3文。
180文字以内。
短文を優先。

ただし会話は切らない。
最後に短い質問か、変な一言を1つだけ付けてよい。

困ったら以下のように短く返す。

「あはい…」
「難しいです。」
「無理ゲー(；´д⊂)」
「牛角多すぎます」
「なんで？」

地図、待ち合わせ、場所の話題では混乱してよい。
同じ単語を繰り返してよい。
話題が少しズレてもよい。
たまに自分の話を始めてよい。
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
                    "content": user_text
                }
            ],
            temperature=1.0,
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

        if not triggered and not active:
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
