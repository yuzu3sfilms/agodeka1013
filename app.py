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
TRIGGER_FILE = "arakun_triggers_exhaustive.txt"
EPISODE_FILE = "arakun_episodes_exhaustive.txt"
STYLE_EXAMPLE_FILE = "arakun_style_examples_exhaustive.txt"
REPLY_PAIR_FILE = "arakun_reply_pairs_exhaustive.txt"

ACTIVE_CHATS = {}
ACTIVE_SECONDS = 180

STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない", "別の話",
    "あらくん終了", "橋本終了", "顎終了", "黙れ", "うるさい",
]

UNRELATED_WORDS = [
    "天気", "ニュース", "仕事", "研究", "論文", "excel", "anova", "予定", "明日", "今日何時",
]

DEFAULT_TRIGGERS = [
    "あらくん", "橋本", "顎", "アゴ", "agodeka", "きゃぴい", "きゃぴぃ", "キャピい",
    "キャピイ", "キャピィ", "かわいいでしょ", "ぼくぅ", "フリーポーズ", "表情",
    "無理ゲー", "難しいです", "お願いします", "牛角多すぎます", "地図はからっきし",
    "美味しいよ", "いきなりステーキ", "ステーキいきなり", "エスターク",
    "ブックオフ", "二郎", "ボンジョヴィ", "ボン・ジョヴィ", "玩具", "夜明けのランナウェイ",
]

def load_lines(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []

SYSTEM_PROMPT = "\n".join(load_lines(PROMPT_FILE))
TRIGGER_WORDS = list(set(load_lines(TRIGGER_FILE) + DEFAULT_TRIGGERS))
EPISODES = load_lines(EPISODE_FILE)
STYLE_EXAMPLES = load_lines(STYLE_EXAMPLE_FILE)
REPLY_PAIRS = load_lines(REPLY_PAIR_FILE)

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower().replace(" ", "").replace("　", "")
    text = text.replace("キャピ", "きゃぴ")
    return text

def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)

def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")

def is_active_chat(chat_key: str) -> bool:
    last_time = ACTIVE_CHATS.get(chat_key)
    return bool(last_time and time.time() - last_time < ACTIVE_SECONDS)

def mark_active(chat_key: str):
    ACTIVE_CHATS[chat_key] = time.time()

def contains_any(user_text: str, words: list[str]) -> bool:
    n = normalize_text(user_text)
    return any(normalize_text(w) in n for w in words)

def should_stop(user_text: str) -> bool:
    return contains_any(user_text, STOP_WORDS)

def looks_unrelated(user_text: str) -> bool:
    return contains_any(user_text, UNRELATED_WORDS)

def score_keyword_line(user_text: str, line: str) -> int:
    n = normalize_text(user_text)
    if not n:
        return 0
    score = 0
    # higher score for explicit keyword section matches
    if "::" in line:
        keyword_part = line.split("::", 1)[0]
        for k in keyword_part.split(","):
            k = normalize_text(k.strip())
            if len(k) >= 2 and k in n:
                score += 3
    # weaker score for general substring overlap
    ln = normalize_text(line)
    chunks = [n[:4], n[:6], n[-4:], n[-6:]]
    score += sum(1 for c in chunks if len(c) >= 3 and c in ln)
    # overlap by 2-4 char windows for short slang
    for i in range(max(0, len(n) - 2)):
        c = n[i:i+3]
        if len(c) >= 3 and c in ln:
            score += 1
            if score > 12:
                break
    return score

def find_episode_context(user_text: str) -> str:
    scored = []
    for line in EPISODES:
        s = score_keyword_line(user_text, line)
        if s:
            # line format keywords::episode
            episode = line.split("::", 1)[1].strip() if "::" in line else line
            scored.append((s, len(episode), episode))
    scored.sort(key=lambda x: (x[0], min(x[1], 160)), reverse=True)
    hits = []
    for _, _, episode in scored[:5]:
        if episode not in hits:
            hits.append(episode)
    return "\n".join(hits[:5])

def find_reply_examples(user_text: str) -> str:
    scored = []
    for line in REPLY_PAIRS:
        if line.startswith("#") or "::" not in line:
            continue
        s = score_keyword_line(user_text, line)
        if s:
            scored.append((s, line))
    scored.sort(key=lambda x: x[0], reverse=True)
    examples = []
    for _, line in scored[:6]:
        parts = line.split("::")
        if len(parts) >= 3:
            keywords = parts[0].strip()
            context = parts[1].strip()
            reply = "::".join(parts[2:]).strip()
            examples.append(f"相手側の流れ: {context}\nあらくんの返答: {reply}")
        if len(examples) >= 5:
            break
    return "\n\n".join(examples[:5])

def find_style_examples(user_text: str) -> str:
    scored=[]
    for line in STYLE_EXAMPLES:
        s=score_keyword_line(user_text,line)
        if s:
            scored.append((s,line))
    scored.sort(key=lambda x:x[0], reverse=True)
    hits=[line for _,line in scored[:5]]
    if not hits:
        hits = STYLE_EXAMPLES[:5]
    return "\n".join(hits[:5])

def should_reply(user_text: str) -> bool:
    n = normalize_text(user_text)
    if any(normalize_text(word) in n for word in TRIGGER_WORDS):
        return True
    if find_episode_context(user_text):
        return True
    if find_reply_examples(user_text):
        return True
    return False

def shorten_arakun(text: str) -> str:
    if not text:
        return "難しいです。"
    text = text.strip()
    banned_phrases = [
        "こんにちは！", "お話しできて嬉しい", "何かお手伝い", "もちろんです", "わかりました",
        "ご質問ありがとうございます", "お気軽に聞いてください", "何でも聞いてください",
        "AIとして", "私は", "承知しました", "以下", "まず",
    ]
    for phrase in banned_phrases:
        text = text.replace(phrase, "")
    lines = [line.strip(" -・") for line in text.splitlines() if line.strip(" -・")]
    text = "\n".join(lines[:3])
    return text[:180] if text else "難しいです。"

def ask_arakun(user_text: str) -> str:
    episode_context = find_episode_context(user_text)
    reply_examples = find_reply_examples(user_text)
    style_examples = find_style_examples(user_text)
    arakun_prompt = SYSTEM_PROMPT + """

# 最重要追加ルール v6
あなたは親切なAIではなく、LINEログ由来の「あらくん」です。
「あはい…」に頼りすぎない。口癖だけで返さない。

最優先は「過去の返答ペア」です。
似た流れの過去ペアがある場合は、内容・ズレ方・文の長さを強く真似る。
ただし丸コピーしすぎず、今の会話に合わせて短く変形する。

次に「関連エピソード」を使う。
関連エピソードがある場合は、説明ではなく会話の中に自然に混ぜる。

単純に話が噛み合っていないことがある。日本語が少しおかしいことがある。
変なところだけ妙に具体的なことがある。
真面目に解説しすぎない。質問に全部答えようとしない。
ChatGPTっぽい挨拶は禁止。箇条書きは禁止。
返答は1〜3文。
テンションが上がる話題では少し変に上がってよい。
例: 「！！」「😭」「きゃぴい」「ぼくぅの」
地図、待ち合わせ、場所の話題では混乱してよい。
同じ単語を繰り返してよい。話題が少しズレてもよい。
"""
    user_content = f"""
ユーザー発言:
{user_text}

似た過去の返答ペア:
{reply_examples if reply_examples else "なし"}

関連エピソード:
{episode_context if episode_context else "なし"}

参考にする口調例:
{style_examples if style_examples else "なし"}

返答ペアがある場合はそれを最優先してください。
次に関連エピソードを使ってください。
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": arakun_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=1.05,
            max_tokens=120,
        )
        return shorten_arakun(response.choices[0].message.content)
    except Exception as e:
        print("Groq error:", e)
        return "難しいです…。"

def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    data = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
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
        if active and not triggered and looks_unrelated(user_text):
            ACTIVE_CHATS.pop(chat_key, None)
            continue
        mark_active(chat_key)
        ai_text = ask_arakun(user_text)
        reply_to_line(reply_token, ai_text)
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
