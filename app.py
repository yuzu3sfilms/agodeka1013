import base64
import hashlib
import hmac
import os
import time

import requests
from flask import Flask, request, abort

from bot import HashimotoArataBot
from utils import normalize


LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
DEBUG = os.environ.get("DEBUG_LOG", "1") == "1"

app = Flask(__name__)
bot = HashimotoArataBot()
SENDER_NAME_CACHE = {}


STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "橋本停止", "橋本終了", "橋本新終了", "あらくん停止", "あらくん終了",
]
STOP_WORDS_N = [normalize(w) for w in STOP_WORDS]


def log(*args):
    if DEBUG:
        print(*args, flush=True)


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



def get_sender_id(event: dict) -> str:
    return event.get("source", {}).get("userId", "")


def get_sender_display_name(event: dict) -> str:
    source = event.get("source", {})
    user_id = source.get("userId", "")
    if not user_id:
        return ""
    if user_id in SENDER_NAME_CACHE:
        return SENDER_NAME_CACHE[user_id]

    source_type = source.get("type")
    if source_type == "group" and source.get("groupId"):
        url = f"https://api.line.me/v2/bot/group/{source['groupId']}/member/{user_id}"
    elif source_type == "room" and source.get("roomId"):
        url = f"https://api.line.me/v2/bot/room/{source['roomId']}/member/{user_id}"
    else:
        url = f"https://api.line.me/v2/bot/profile/{user_id}"

    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}, timeout=6)
        if 200 <= res.status_code < 300:
            name = (res.json().get("displayName") or "").strip()
            if name:
                SENDER_NAME_CACHE[user_id] = name
                return name
        log("LINE profile error:", res.status_code, res.text[:200])
    except Exception as e:
        log("LINE profile exception:", repr(e))
    return ""

def is_stop(text: str) -> bool:
    nt = normalize(text)
    return any(w in nt for w in STOP_WORDS_N)


def line_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def push_line(to_id: str, text: str) -> bool:
    if not to_id or to_id == "unknown" or not text:
        log("push skipped")
        return False
    url = "https://api.line.me/v2/bot/message/push"
    payload = {"to": to_id, "messages": [{"type": "text", "text": text}]}
    try:
        res = requests.post(url, headers=line_headers(), json=payload, timeout=10)
        log("LINE push status:", res.status_code)
        if res.status_code >= 300:
            log("LINE push error:", res.status_code, res.text)
        return 200 <= res.status_code < 300
    except Exception as e:
        log("LINE push exception:", repr(e))
        return False


def reply_line(reply_token: str, text: str, fallback_to_id: str | None = None) -> bool:
    if not text:
        log("reply skipped: empty answer")
        return False

    url = "https://api.line.me/v2/bot/message/reply"
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    try:
        res = requests.post(url, headers=line_headers(), json=payload, timeout=10)
        log("LINE reply status:", res.status_code)
        if 200 <= res.status_code < 300:
            return True
        log("LINE reply error:", res.status_code, res.text)
        if fallback_to_id:
            log("trying push fallback")
            return push_line(fallback_to_id, text)
        return False
    except Exception as e:
        log("LINE reply exception:", repr(e))
        if fallback_to_id:
            log("trying push fallback after exception")
            return push_line(fallback_to_id, text)
        return False


@app.route("/", methods=["GET"])
def index():
    return "AI Hashimoto Arata v14.12.2 shared shutdown state is running."


@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "version": "v14.12.2-shared-shutdown-state", "time": int(time.time())}


@app.route("/callback", methods=["GET"])
def callback_get():
    return "callback endpoint is alive. LINE must use POST."


@app.route("/callback", methods=["POST"])
def callback():
    log("callback POST hit")

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
            log("event type:", event.get("type"))
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            log("message type:", message.get("type"))
            if message.get("type") != "text":
                log("ignored non-text")
                continue

            user_text = message.get("text", "")
            chat_id = get_chat_id(event)
            log("received:", user_text)
            sender_id = get_sender_id(event)
            sender_display_name = get_sender_display_name(event)
            log("chat_id:", chat_id)
            log("sender:", sender_id, sender_display_name)

            if is_stop(user_text):
                bot.remember_user(chat_id, user_text)
                bot.set_shutdown(chat_id, True)
                log("stopped: shutdown_state=True")
                continue

            answer = bot.reply(chat_id, user_text, sender_id=sender_id, sender_display_name=sender_display_name)

            if answer is None:
                log("ignored: no episode")
                continue

            log("reply:", answer)
            if reply_token:
                reply_line(reply_token, answer, fallback_to_id=chat_id)
            else:
                push_line(chat_id, answer)

        except Exception as e:
            log("callback event error:", repr(e))
            if reply_token:
                reply_line(reply_token, "ｷｬﾋﾟｨ", fallback_to_id=get_chat_id(event))

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
