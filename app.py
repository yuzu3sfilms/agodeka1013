import base64
import hashlib
import hmac
import os

import requests
from flask import Flask, request, abort

from bot import HashimotoArataBot
from utils import normalize


LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
DEBUG = os.environ.get("DEBUG_LOG", "1") == "1"

app = Flask(__name__)
bot = HashimotoArataBot()


STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "橋本停止", "橋本終了", "橋本新終了", "あらくん停止", "あらくん終了",
]
STOP_WORDS_N = [normalize(w) for w in STOP_WORDS]


def log(*args):
    if DEBUG:
        print(*args)


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def get_chat_id(event: dict) -> str:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId") or "unknown"


def is_stop(text: str) -> bool:
    nt = normalize(text)
    return any(w in nt for w in STOP_WORDS_N)


def reply_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text or "難しいです。"}],
    }
    res = requests.post(url, headers=headers, json=payload, timeout=10)
    log("LINE reply status:", res.status_code)
    if res.status_code >= 300:
        log("LINE reply error:", res.status_code, res.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Hashimoto Arata v4 high fidelity is running."


@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        log("signature verification failed")
        abort(400)

    events = request.json.get("events", [])
    log("events:", len(events))

    for event in events:
        reply_token = event.get("replyToken")

        try:
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            user_text = message.get("text", "")
            chat_id = get_chat_id(event)

            log("received:", user_text)

            if not reply_token:
                continue

            if is_stop(user_text):
                bot.remember(chat_id, user_text)
                log("stopped")
                continue

            answer = bot.reply(chat_id, user_text)
            log("reply:", answer)
            reply_line(reply_token, answer)

        except Exception as e:
            log("callback error:", repr(e))
            if reply_token:
                try:
                    reply_line(reply_token, "難しいです。")
                except Exception as e2:
                    log("fallback reply failed:", repr(e2))

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
