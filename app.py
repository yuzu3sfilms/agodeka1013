import base64
import hashlib
import hmac

import requests
from flask import Flask, request, abort

import config
from bot_core import ArakunBot
from conversation import ConversationMemory
from text_utils import normalize_text


app = Flask(__name__)

bot = ArakunBot()
memory = ConversationMemory()


def log(*args):
    if config.DEBUG_LOG:
        print(*args)


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        config.LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "あらくん停止", "あらくん終了", "橋本終了", "橋本新終了", "顎終了",
]
NORMALIZED_STOP_WORDS = [normalize_text(w) for w in STOP_WORDS]


def should_stop(text: str) -> bool:
    nt = normalize_text(text)
    return any(w in nt for w in NORMALIZED_STOP_WORDS)


def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
    }

    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }

    res = requests.post(url, headers=headers, json=payload, timeout=10)
    log("LINE reply status:", res.status_code)

    if res.status_code >= 300:
        log("LINE reply error:", res.status_code, res.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Arakun Bot v9 modular is running."


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
            chat_key = get_chat_key(event)

            log("received:", user_text)

            if not reply_token or not chat_key:
                log("missing reply_token or chat_key")
                continue

            context_text = memory.build_context(chat_key, user_text)

            # 停止ワードだけは返信しない
            if should_stop(user_text):
                memory.add(chat_key, user_text)
                log("stopped by stop word")
                continue

            # 全返信モード
            memory.add(chat_key, user_text)

            ai_text = bot.generate_reply(user_text, context_text)
            log("reply:", ai_text)
            reply_to_line(reply_token, ai_text)

        except Exception as e:
            log("callback event error:", repr(e))
            if reply_token:
                try:
                    reply_to_line(reply_token, "難しいです。")
                except Exception as e2:
                    log("fallback reply failed:", repr(e2))

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
    )
