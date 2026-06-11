import os
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, abort
from google import genai

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

with open("AGODEKA1013_PROMPT.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def ask_arakun(user_text: str) -> str:
    prompt = f"{SYSTEM_PROMPT}\n\nユーザー: {user_text}\nあらくん:"

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt
    )

    text = response.text or "難しいです…。"
    return text[:4900]


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
    requests.post(url, headers=headers, json=data, timeout=10)


@app.route("/", methods=["GET"])
def index():
    return "Arakun is running."


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

        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
