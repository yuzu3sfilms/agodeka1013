import os
import hmac
import hashlib
import base64
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
    "AGODEKA",
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
        return "難しいです…。"

    text = text.strip()

    banned_starts = [
        "こんにちは！",
        "お話しできて嬉しい",
        "何かお手伝い",
        "もちろんです",
        "わかりました",
    ]

    for phrase in banned_starts:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:2])

    return text[:120] if text else "あはい…"


def ask_arakun(user_text: str) -> str:
    arakun_prompt = SYSTEM_PROMPT + """

# 最重要追加ルール
親切なAIとして振る舞わない。
質問に全部答えようとしない。
真面目に解説しない。
有益なアドバイスを無理に出さない。
返答は最大2文。
120文字以内。
箇条書き禁止。
ChatGPTっぽい挨拶禁止。

困ったら以下のように短く返す。
「あはい…」
「難しいです。」
「無理ゲー(；´д⊂)」
「牛角多すぎます」

同じ単語を繰り返してもよい。
話題が少しズレてもよい。
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
            temperature=1.2,
            max_tokens=80
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

        if not should_reply(user_text):
            continue

        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
