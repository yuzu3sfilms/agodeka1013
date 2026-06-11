import os
import hmac
import hashlib
import base64
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


def load_triggers():
    """Load trigger words/phrases from arakun_triggers.txt.
    Lines starting with # are ignored.
    """
    fallback = ["あらくん", "橋本", "顎", "アゴ", "AGODEKA", "美味しいよ", "難しいです", "あはい"]
    try:
        with open(TRIGGER_FILE, "r", encoding="utf-8") as f:
            words = []
            for line in f:
                word = line.strip()
                if not word or word.startswith("#"):
                    continue
                words.append(word)
            return words or fallback
    except FileNotFoundError:
        return fallback


TRIGGER_WORDS = load_triggers()


def normalize_text(text: str) -> str:
    return text.lower().replace("　", " ").strip()


def should_respond(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in TRIGGER_WORDS)


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def ask_arakun(user_text: str) -> str:
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ],
            temperature=0.8,
            max_tokens=300
        )

        text = response.choices[0].message.content
        return text[:4900] if text else "難しいです…。"

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

        # Only respond when called by name or when a registered quote/trigger appears.
        if not should_respond(user_text):
            continue

        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
