import base64
import hashlib
import hmac
import requests
from flask import Flask, request, abort

import config
from bot_core import HashimotoArataBot
from memory import ConversationMemory
from text_utils import normalize_text

app = Flask(__name__)
bot = HashimotoArataBot()
memory = ConversationMemory()

STOP_WORDS = ["もういい", "黙って", "だまって", "終了", "停止", "橋本終了", "橋本停止", "あらくん停止"]
STOP_N = [normalize_text(x) for x in STOP_WORDS]


def log(*args):
    if config.DEBUG_LOG:
        print(*args)


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(config.LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def should_stop(text: str) -> bool:
    nt = normalize_text(text)
    return any(x in nt for x in STOP_N)


def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"}
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text or "難しいです。"}]}
    res = requests.post(url, headers=headers, json=payload, timeout=10)
    log("LINE reply status:", res.status_code)
    if res.status_code >= 300:
        log("LINE reply error:", res.status_code, res.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Hashimoto Arata v2.2 guaranteed reply is running."


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
            chat_key = get_chat_key(event) or "unknown"
            if not reply_token:
                log("missing reply_token")
                continue
            context_text = memory.context(chat_key, user_text)
            memory.add(chat_key, user_text)
            if should_stop(user_text):
                log("stopped")
                continue
            reply = bot.generate_reply(user_text, context_text) or "難しいです。"
            log("received:", user_text)
            log("reply:", reply)
            reply_to_line(reply_token, reply)
        except Exception as e:
            log("callback event error:", repr(e))
            if reply_token:
                try:
                    reply_to_line(reply_token, "難しいです。")
                except Exception as e2:
                    log("fallback failed:", repr(e2))
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
