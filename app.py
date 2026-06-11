import os
import hmac
import hashlib
import base64
import re
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
EXAMPLES_FILE = "arakun_style_examples.txt"

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def load_lines(path, fallback):
    try:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rows.append(line)
        return rows or fallback
    except FileNotFoundError:
        return fallback


TRIGGER_WORDS = load_lines(
    TRIGGER_FILE,
    ["あらくん", "橋本", "顎", "アゴ", "AGODEKA", "美味しいよ", "難しいです", "あはい"]
)

RAW_EXAMPLES = load_lines(
    EXAMPLES_FILE,
    [
        "core_quote\tあはい",
        "core_quote\t難しいです…",
        "core_quote\t美味しいよ！",
    ]
)


def parse_examples():
    examples = []
    for row in RAW_EXAMPLES:
        if "\t" in row:
            category, text = row.split("\t", 1)
        else:
            category, text = "example", row
        examples.append({"category": category, "text": text})
    return examples


STYLE_EXAMPLES = parse_examples()


def normalize_text(text: str) -> str:
    return text.lower().replace("　", " ").strip()


def should_respond(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in TRIGGER_WORDS)


def tokenize_ja(text: str):
    text = normalize_text(text)
    # Japanese-friendly rough tokens: chunks of letters/numbers plus 2-char slices
    words = re.findall(r"[a-z0-9A-Zぁ-んァ-ン一-龥ー]+", text)
    chars = [text[i:i+2] for i in range(max(0, len(text)-1))]
    return set(words + chars)


def select_style_examples(user_text: str, limit: int = 8):
    user_tokens = tokenize_ja(user_text)
    scored = []
    for ex in STYLE_EXAMPLES:
        text = ex["text"]
        tokens = tokenize_ja(text)
        score = len(user_tokens & tokens)
        # category boosts
        if any(k in user_text for k in ["筋", "ベンチ", "デッド", "スクワット", "ジム", "ダイエット"]):
            if ex["category"] == "training":
                score += 5
        if any(k in user_text for k in ["食", "寿司", "ラーメン", "酒", "美味"]):
            if ex["category"] == "food":
                score += 5
        if any(k in user_text for k in ["どこ", "駅", "出口", "待ち合わせ", "着いた"]):
            if ex["category"] == "confused_location":
                score += 5
        if any(k in user_text for k in ["あらくん", "橋本", "顎", "アゴ"]):
            if ex["category"] in ["core_quote", "greeting_short"]:
                score += 4
        if score > 0:
            scored.append((score, len(text), ex))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [x[2] for x in scored[:limit]]
    if not chosen:
        chosen = STYLE_EXAMPLES[:min(limit, len(STYLE_EXAMPLES))]
    return chosen


def build_user_prompt(user_text: str) -> str:
    examples = select_style_examples(user_text)
    example_text = "\n".join([f"- ({ex['category']}) {ex['text']}" for ex in examples])
    return f"""ユーザー発言:
{user_text}

文体参照例（内容を丸写しせず、語尾・短さ・テンションだけ寄せる）:
{example_text}

上の参照例に忠実なAIあらくんとして、1〜3文で返答してください。"""


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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(user_text)}
            ],
            temperature=0.65,
            top_p=0.9,
            max_tokens=180
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
    data = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}

    response = requests.post(url, headers=headers, json=data, timeout=10)
    if response.status_code >= 300:
        print("LINE reply error:", response.status_code, response.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Arakun Bot v3 is running."


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

        if not should_respond(user_text):
            continue

        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
