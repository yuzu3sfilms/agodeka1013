import os
import hmac
import hashlib
import base64
import random
import unicodedata
import requests
from collections import deque
from difflib import SequenceMatcher
from flask import Flask, request, abort
from openai import OpenAI

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

PROMPT_FILE = "AGODEKA1013_PROMPT.txt"
TRIGGER_FILE = "arakun_triggers_exhaustive.txt"
EPISODE_FILE = "arakun_episodes_exhaustive.txt"
STYLE_FILE = "arakun_style_examples_exhaustive.txt"
REPLY_PAIR_FILE = "arakun_reply_pairs_exhaustive.txt"
HASHIMOTO_SHIN_FILE = "hashimoto_shin_examples.txt"

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_REPLY_CHARS = 190

MAX_TRIGGERS = 12000
MAX_EPISODES = 9000
MAX_REPLY_PAIRS = 5000
MAX_STYLE = 1400
MAX_HASHIMOTO_SHIN = 700

SCAN_EPISODES = 2800
SCAN_REPLY_PAIRS = 2200
SCAN_STYLE = 1000
SCAN_HASHIMOTO_SHIN = 800

HISTORY_LEN = 5
CHAT_HISTORY = {}

CALL_WORDS = [
    "あらくん", "あら君", "橋本", "橋本新", "顎", "アゴ", "あご",
    "AGODEKA", "agodeka", "LIAR", "ARAKUN",
]

STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "あらくん停止", "あらくん終了", "橋本終了", "橋本新終了", "顎終了",
]

DEFAULT_TRIGGERS = [
    "あらくん", "橋本", "橋本新", "新橋本", "新橋本新", "顎", "アゴ",
    "あご", "agodeka", "きゃぴい", "きゃぴぃ", "キャピい", "キャピイ",
    "キャピィ", "きゃっぴい", "かわいいでしょ", "ぼくぅ", "フリーポーズ",
    "表情", "無理ゲー", "難しいです", "お願いします", "牛角多すぎます",
    "地図はからっきし", "美味しいよ", "いきなりステーキ", "エスターク",
    "ブックオフ", "二郎", "野猿", "ボンジョヴィ", "ボン・ジョヴィ",
    "玩具", "ｷﾞｬｵｫ", "ギャオ", "トーマス", "アナザーアラクン",
    "橋本新名言集", "筋トレ", "スクワット", "ベンチプレス", "デッドリフト",
    "ゴールドジム", "小杉湯", "高円寺", "阿佐ヶ谷", "サイゼ",
    "バーミヤン", "ムタァ", "ムタファ", "ポッツォ", "ポツォ",
]

GENERIC_WORDS = {
    "今日", "明日", "昨日", "予定", "仕事", "大丈夫", "了解", "はい",
    "いい", "そう", "これ", "それ", "どれ", "ここ", "そこ", "あれ",
    "です", "ます", "した", "する", "ある", "ない", "こと", "もの",
    "www", "wwww", "笑", "草", "w", "ok", "ng", "やばい", "まじ",
    "えぐい", "line", "twitter", "instagram", "(emoji)", "(thinking)",
}

AI_PHRASES = [
    "こんにちは！", "こんにちは。", "お話しできて嬉しい", "何かお手伝い",
    "もちろんです", "わかりました", "ご質問ありがとうございます",
    "お気軽に聞いてください", "何でも聞いてください", "AIとして",
    "私は", "以下の", "ポイントは", "要するに", "まとめると",
]


def normalize_text(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


def load_lines(filename: str, max_lines: int | None = None) -> list[str]:
    try:
        result = []
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.lstrip().startswith("#"):
                    continue
                result.append(line)
                if max_lines and len(result) >= max_lines:
                    break
        return result
    except FileNotFoundError:
        return []


def unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


SYSTEM_PROMPT = "\n".join(load_lines(PROMPT_FILE))

RAW_TRIGGERS = load_lines(TRIGGER_FILE, MAX_TRIGGERS)
RAW_EPISODES = load_lines(EPISODE_FILE, MAX_EPISODES)
RAW_REPLY_PAIRS = load_lines(REPLY_PAIR_FILE, MAX_REPLY_PAIRS)
RAW_STYLE = load_lines(STYLE_FILE, MAX_STYLE)
RAW_HASHIMOTO_SHIN = load_lines(HASHIMOTO_SHIN_FILE, MAX_HASHIMOTO_SHIN)

NORMALIZED_STOP_WORDS = [normalize_text(w) for w in STOP_WORDS]
NORMALIZED_CALL_WORDS = [normalize_text(w) for w in CALL_WORDS]
NORMALIZED_GENERIC = {normalize_text(w) for w in GENERIC_WORDS}

ALL_TRIGGERS = sorted(set(RAW_TRIGGERS + DEFAULT_TRIGGERS), key=len, reverse=True)
TRIGGER_PAIRS = []
for word in ALL_TRIGGERS:
    nw = normalize_text(word)
    if not nw or nw in NORMALIZED_GENERIC:
        continue
    if 2 <= len(nw) <= 40:
        TRIGGER_PAIRS.append((nw, word))
TRIGGER_PAIRS = sorted(set(TRIGGER_PAIRS), key=lambda x: len(x[0]), reverse=True)

REPLY_ENTRIES = [(normalize_text(line), line) for line in RAW_REPLY_PAIRS]
STYLE_ENTRIES = [(normalize_text(line), line) for line in RAW_STYLE]

EPISODE_ENTRIES = []
for line in RAW_EPISODES:
    if "::" in line:
        keywords, episode = line.split("::", 1)
        keys = [normalize_text(k.strip()) for k in keywords.split(",") if k.strip()]
        EPISODE_ENTRIES.append((keys, normalize_text(episode), episode.strip()))
    else:
        EPISODE_ENTRIES.append(([normalize_text(line)], normalize_text(line), line.strip()))

HASHIMOTO_SHIN_ENTRIES = [(normalize_text(line), line) for line in RAW_HASHIMOTO_SHIN]
for line in RAW_REPLY_PAIRS:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))
for line in RAW_EPISODES:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))
for line in RAW_STYLE:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def get_history(chat_key: str) -> list[str]:
    return list(CHAT_HISTORY.get(chat_key, deque(maxlen=HISTORY_LEN)))


def add_history(chat_key: str, text: str):
    if chat_key not in CHAT_HISTORY:
        CHAT_HISTORY[chat_key] = deque(maxlen=HISTORY_LEN)
    CHAT_HISTORY[chat_key].append(text)


def build_context(chat_key: str, user_text: str) -> str:
    return "\n".join(get_history(chat_key) + [user_text])


def should_stop(text: str) -> bool:
    nt = normalize_text(text)
    return any(w in nt for w in NORMALIZED_STOP_WORDS)


def get_trigger_hits(context_text: str, limit: int = 20) -> list[tuple[str, str]]:
    nt = normalize_text(context_text)
    hits = []
    for nw, original in TRIGGER_PAIRS:
        if nw in nt:
            hits.append((nw, original))
        if len(hits) >= limit:
            break
    return hits


def score_line(context_text: str, normalized_line: str, hits: list[tuple[str, str]]) -> int:
    nt = normalize_text(context_text)
    score = 0

    for nw, _original in hits:
        if nw in normalized_line:
            score += 100 + min(len(nw), 20)

    base = nt[:90]
    chunks = set()
    for n in (2, 3, 4):
        for i in range(max(0, len(base) - n + 1)):
            chunks.add(base[i:i+n])

    for c in chunks:
        if c and c in normalized_line:
            score += len(c)

    return score


def top_entries(context_text: str, entries: list[tuple[str, str]], hits: list[tuple[str, str]], limit: int, scan_limit: int, min_score: int = 45) -> list[str]:
    if not entries:
        return []

    if not hits:
        sample = entries[:min(len(entries), scan_limit)]
        return [line for _nt, line in random.sample(sample, min(limit, len(sample)))]

    scored = []
    for normalized_line, line in entries[:scan_limit]:
        if not any(nw in normalized_line for nw, _o in hits):
            continue
        score = score_line(context_text, normalized_line, hits)
        if score >= min_score:
            scored.append((score, line))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [line for _score, line in scored[:limit]]


def find_episodes(context_text: str, hits: list[tuple[str, str]]) -> str:
    nt = normalize_text(context_text)
    scored = []

    for keys, normalized_episode, episode in EPISODE_ENTRIES[:SCAN_EPISODES]:
        score = 0

        for key in keys[:10]:
            if key and key not in NORMALIZED_GENERIC and key in nt:
                score += 120 + min(len(key), 20)

        for nw, _o in hits:
            if nw in normalized_episode:
                score += 80 + min(len(nw), 20)

        if score > 0:
            scored.append((score, episode))

    scored.sort(key=lambda x: x[0], reverse=True)
    return "\n".join(unique([episode for _score, episode in scored[:5]]))


def find_reply_pairs(context_text: str, hits: list[tuple[str, str]]) -> str:
    if not hits:
        return ""
    return "\n".join(top_entries(context_text, REPLY_ENTRIES, hits, 5, SCAN_REPLY_PAIRS, 50))


def find_style_examples(context_text: str, hits: list[tuple[str, str]]) -> str:
    examples = top_entries(context_text, STYLE_ENTRIES, hits, 4, SCAN_STYLE, 45)
    if not examples and RAW_STYLE:
        examples = random.sample(RAW_STYLE, min(4, len(RAW_STYLE)))
    return "\n".join(examples[:4])


def find_hashimoto_shin(context_text: str, hits: list[tuple[str, str]]) -> str:
    if not HASHIMOTO_SHIN_ENTRIES:
        return ""

    local_hits = list(hits)
    if "橋本新" in context_text:
        local_hits.append((normalize_text("橋本新"), "橋本新"))

    if not local_hits:
        return ""

    return "\n".join(top_entries(context_text, HASHIMOTO_SHIN_ENTRIES, local_hits, 4, SCAN_HASHIMOTO_SHIN, 35))


def simplify_for_echo(text: str) -> str:
    nt = normalize_text(text)
    for w in NORMALIZED_CALL_WORDS:
        nt = nt.replace(w, "")
    for ch in "!?！？。、,.…・「」『』（）()[]【】\n\r\t":
        nt = nt.replace(ch, "")
    return nt


def is_echo(user_text: str, reply_text: str) -> bool:
    user_core = simplify_for_echo(user_text)
    reply_core = simplify_for_echo(reply_text)

    if not user_core or not reply_core:
        return False

    if user_core == reply_core:
        return True

    if len(user_core) <= 5 and user_core in reply_core and len(reply_core) <= len(user_core) + 6:
        return True

    if len(user_core) >= 4 and user_core in reply_core:
        return True

    if len(reply_core) >= 4 and reply_core in user_core:
        return True

    ratio = SequenceMatcher(None, user_core, reply_core).ratio()
    if ratio >= 0.60 and len(reply_core) <= int(len(user_core) * 1.8) + 8:
        return True

    chunks = set()
    for i in range(max(0, len(user_core) - 2)):
        chunks.add(user_core[i:i+3])

    if chunks:
        overlap = sum(1 for c in chunks if c in reply_core)
        if overlap / len(chunks) >= 0.55 and len(reply_core) <= len(user_core) + 30:
            return True

    return False


def clean_reply(text: str) -> str:
    text = (text or "").strip()
    for phrase in AI_PHRASES:
        text = text.replace(phrase, "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])
    return text[:MAX_REPLY_CHARS] if text else "難しいです。"


def fallback_reply(user_text: str, context_text: str) -> str:
    nt = normalize_text(context_text)
    candidates = []

    if normalize_text("橋本新") in nt:
        candidates += ["ｷﾞｬｵｫ。", "名言集です。", "それは新の方です。"]
    if normalize_text("きゃぴ") in nt:
        candidates += ["ぼくぅの表情です。", "それは良いです！！", "泣きます。"]
    if normalize_text("二郎") in nt or normalize_text("野猿") in nt:
        candidates += ["ブックオフのはずが違う所に着きました。", "そこは難しいです。", "もう着いてます。"]
    if normalize_text("牛角") in nt:
        candidates += ["多すぎます。", "探すのてこずりましたすみませんでした。", "地図はからっきしだめです。"]
    if normalize_text("エスターク") in nt:
        candidates += ["通常種ではないです。", "色が違います。", "それは良いです！！"]
    if normalize_text("フリーポーズ") in nt:
        candidates += ["表情が難しいです。", "かわいいでしょ(ﾉ≧▽≦)ﾉ", "お願いします。"]
    if normalize_text("地図") in nt or normalize_text("迷子") in nt:
        candidates += ["交番行きます。", "無理ゲー(；´д⊂)", "からっきしだめです。"]

    candidates += [
        "難しいです。",
        "それは違います。",
        "お願いします…。",
        "ちょっと分からないです。",
        "そういうことではないです。",
        "これは良いです。",
        "無理ゲーです。",
    ]

    random.shuffle(candidates)
    for c in candidates:
        if not is_echo(user_text, c):
            return c

    return "難しいです。"


def final_reply(user_text: str, raw_text: str, context_text: str) -> str:
    reply = clean_reply(raw_text)
    if not is_echo(user_text, reply):
        return reply
    return fallback_reply(user_text, context_text)


def build_prompt(user_text: str, context_text: str) -> tuple[str, str]:
    hits = get_trigger_hits(context_text, limit=20)
    matched = "、".join([original for _nw, original in hits]) if hits else "なし"

    episodes = find_episodes(context_text, hits)
    reply_pairs = find_reply_pairs(context_text, hits)
    style = find_style_examples(context_text, hits)
    hashimoto_shin = find_hashimoto_shin(context_text, hits)

    system_prompt = SYSTEM_PROMPT + """

# Runtime rules v8 clean

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。
このBotは全返信モードです。テキストが来たら必ず短く返します。

最重要:
- おうむ返しは禁止。
- ユーザー発言をそのまま繰り返さない。
- ユーザーの語尾だけ変えて返さない。
- ユーザーの文を主語にして「〜です」「〜ですね」と返さない。
- 一致ワードは検索用の手がかりであり、そのまま返答文へコピーしない。

返答方針:
- 一致ワードがある場合、そのワードに関係する過去例だけ使う。
- 一致ワードと関係ない過去例は無視する。
- 返答ペアがある場合は、その返し方を最優先で真似る。
- エピソードや橋本新文脈がある場合は、断片を自然に混ぜる。
- 一致ワードがない場合も無視せず、短い相づち・ズレた一言・質問返しで返す。
- 説明ではなくLINEの一言として返す。

キャラ:
- 「あはい…」に頼りすぎない。
- 口癖だけで返さない。
- 変なところだけ妙に具体的なことがある。
- 急にテンションが上がることがある。
- でも、まったく関係ない話に飛びすぎない。
- 真面目に解説しすぎない。
- 質問に全部答えようとしない。
- 有益なアドバイスを無理に出さない。
- ChatGPTっぽい挨拶は禁止。
- 箇条書きは禁止。

形式:
- 返答は1〜3文。
- 190文字以内。
- テンションが上がる話題では「！！」「😭」「きゃぴい」「ぼくぅの」「ｷﾞｬｵｫ。」などを使ってよい。
- 地図、待ち合わせ、場所の話題では少し混乱してよい。
"""

    recent = "\n".join(context_text.splitlines()[-HISTORY_LEN:])

    user_prompt = f"""
直近の会話:
{recent}

今回のユーザー発言:
{user_text}

一致した過去ログ/Excel由来ワード:
{matched}

関連エピソード:
{episodes if episodes else "なし"}

過去の似た返答ペア:
{reply_pairs if reply_pairs else "なし"}

橋本新として参照できる過去文脈:
{hashimoto_shin if hashimoto_shin else "なし"}

参考にする口調例:
{style if style else "なし"}

出力:
ユーザー発言をコピーせず、LINEの一言として短く返す。
"""

    return system_prompt, user_prompt


def ask_arakun(user_text: str, context_text: str) -> str:
    system_prompt, user_prompt = build_prompt(user_text, context_text)

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=1.02,
            max_tokens=130,
        )
        raw = response.choices[0].message.content or ""
        return final_reply(user_text, raw, context_text)
    except Exception as e:
        print("Groq error:", e)
        return fallback_reply(user_text, context_text)


def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    res = requests.post(url, headers=headers, json=data, timeout=10)
    if res.status_code >= 300:
        print("LINE reply error:", res.status_code, res.text)


@app.route("/", methods=["GET"])
def index():
    return "AI Arakun Bot v8 clean is running."


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
        chat_key = get_chat_key(event)

        if not reply_token or not chat_key:
            continue

        context_text = build_context(chat_key, user_text)

        if should_stop(user_text):
            add_history(chat_key, user_text)
            continue

        add_history(chat_key, user_text)

        ai_text = ask_arakun(user_text, context_text)
        reply_to_line(reply_token, ai_text)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
    )
