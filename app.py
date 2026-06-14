import os
import hmac
import hashlib
import base64
import time
import random
import unicodedata
import requests
from collections import deque
from functools import lru_cache
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
HASHIMOTO_SHIN_FILE = "hashimoto_shin_examples.txt"

# ===== 返信頻度調整 =====
# うるさければ下げる。黙りすぎなら上げる。
RANDOM_JOIN_PROBABILITY = 0.52          # 通常の語録/Excel単語ヒット時の乱入率
STRONG_JOIN_PROBABILITY = 0.72          # 強い語録ヒット時の乱入率
EPISODE_JOIN_PROBABILITY = 0.62         # エピソード一致時の乱入率
ACTIVE_STRONG_CONTEXT_PROBABILITY = 0.94
ACTIVE_WEAK_CONTEXT_PROBABILITY = 0.72

ACTIVE_MIN_SECONDS = 75
ACTIVE_MAX_SECONDS = 240

ACTIVE_CHATS = {}
CHAT_HISTORY = {}

CALL_WORDS = [
    "あらくん", "あら君", "橋本", "橋本新", "顎", "アゴ", "あご",
    "AGODEKA", "agodeka", "LIAR", "ARAKUN",
]

STOP_WORDS = [
    "もういい", "黙って", "だまって", "終わり", "終了", "関係ない",
    "別の話", "あらくん停止", "あらくん終了", "橋本終了", "橋本新終了", "顎終了",
]

# 呼ばれていない時は、実務系に割り込まないための保険。
# ただし呼びかけられた場合は返す。
UNRELATED_WORDS = [
    "天気", "ニュース", "研究", "論文", "excel", "エクセル",
    "rで", "anova", "統計", "学会", "メール",
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

STRONG_WORDS = [
    "橋本新", "きゃぴ", "牛角", "二郎", "エスターク", "フリーポーズ",
    "ブックオフ", "美味しいよ", "ｷﾞｬｵｫ", "ギャオ", "ムタァ", "ポッツォ",
    "顎動画", "かわいいでしょ",
]

# これらだけでは起動しない。過去ログ由来でも一般語すぎるため。
GENERIC_TRIGGER_BLACKLIST = {
    "今日", "明日", "昨日", "予定", "仕事", "大丈夫", "了解", "はい",
    "いい", "そう", "これ", "それ", "どれ", "ここ", "そこ", "あれ",
    "です", "ます", "した", "する", "ある", "ない", "こと", "もの",
    "www", "wwww", "(emoji)", "(thinking)", "line", "twitter", "instagram",
}


def normalize_text(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


def load_lines(filename: str, max_lines: int | None = None) -> list[str]:
    try:
        lines = []
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.lstrip().startswith("#"):
                    continue
                lines.append(line)
                if max_lines and len(lines) >= max_lines:
                    break
        return lines
    except FileNotFoundError:
        return []


SYSTEM_PROMPT = "\n".join(load_lines(PROMPT_FILE))

# 無料Renderで落ちにくい範囲で、前回より参照量を増やす。
TRIGGER_WORDS = load_lines(TRIGGER_FILE, max_lines=7000)
EPISODES = load_lines(EPISODE_FILE, max_lines=7000)
STYLE_EXAMPLES = load_lines(STYLE_EXAMPLE_FILE, max_lines=1400)
REPLY_PAIRS = load_lines(REPLY_PAIR_FILE, max_lines=4000)
HASHIMOTO_SHIN_EXAMPLES = load_lines(HASHIMOTO_SHIN_FILE, max_lines=700)

TRIGGER_WORDS = sorted(set(TRIGGER_WORDS + DEFAULT_TRIGGERS))

NORMALIZED_CALL_WORDS = [normalize_text(w) for w in CALL_WORDS]
NORMALIZED_STOP_WORDS = [normalize_text(w) for w in STOP_WORDS]
NORMALIZED_UNRELATED_WORDS = [normalize_text(w) for w in UNRELATED_WORDS]
NORMALIZED_STRONG_WORDS = [normalize_text(w) for w in STRONG_WORDS]

# トリガーを正規化して保持。1通ごとに全件を見るのはOK。
# 重かった原因は「候補行ごとに全トリガーを回す」ことなので、それはしない。
NORMALIZED_TRIGGER_PAIRS = []
for w in TRIGGER_WORDS:
    nw = normalize_text(w)
    if not nw:
        continue
    if nw in {normalize_text(x) for x in GENERIC_TRIGGER_BLACKLIST}:
        continue
    if len(nw) < 2 or len(nw) > 40:
        continue
    NORMALIZED_TRIGGER_PAIRS.append((nw, w))

# 長い語を優先して拾う。短い語の誤爆を少し減らす。
NORMALIZED_TRIGGER_PAIRS = sorted(
    set(NORMALIZED_TRIGGER_PAIRS),
    key=lambda x: len(x[0]),
    reverse=True
)

# 事前正規化。毎回巨大ファイルをnormalizeしない。
REPLY_PAIR_ENTRIES = [(normalize_text(line), line) for line in REPLY_PAIRS]
STYLE_ENTRIES = [(normalize_text(line), line) for line in STYLE_EXAMPLES]

EPISODE_ENTRIES = []
for line in EPISODES:
    if "::" in line:
        keywords, episode = line.split("::", 1)
        keyword_list = [normalize_text(k.strip()) for k in keywords.split(",") if k.strip()]
        EPISODE_ENTRIES.append((keyword_list, normalize_text(episode), episode.strip()))
    else:
        EPISODE_ENTRIES.append(([normalize_text(line)], normalize_text(line), line.strip()))

HASHIMOTO_SHIN_ENTRIES = []
for line in HASHIMOTO_SHIN_EXAMPLES:
    HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))
for line in REPLY_PAIRS:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))
for line in EPISODES:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))
for line in STYLE_EXAMPLES:
    if "橋本新" in line:
        HASHIMOTO_SHIN_ENTRIES.append((normalize_text(line), line))


def verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


def get_chat_key(event: dict) -> str | None:
    source = event.get("source", {})
    return source.get("groupId") or source.get("roomId") or source.get("userId")


def get_history(chat_key: str) -> list[str]:
    return list(CHAT_HISTORY.get(chat_key, deque(maxlen=5)))


def add_history(chat_key: str, text: str):
    if chat_key not in CHAT_HISTORY:
        CHAT_HISTORY[chat_key] = deque(maxlen=5)
    CHAT_HISTORY[chat_key].append(text)


def recent_context_text(chat_key: str, user_text: str) -> str:
    history = get_history(chat_key)
    return "\n".join(history + [user_text])


def is_called(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(word in normalized for word in NORMALIZED_CALL_WORDS)


def should_stop(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(word in normalized for word in NORMALIZED_STOP_WORDS)


def looks_unrelated(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(word in normalized for word in NORMALIZED_UNRELATED_WORDS)


def mark_active(chat_key: str):
    ACTIVE_CHATS[chat_key] = {
        "time": time.time(),
        "ttl": random.randint(ACTIVE_MIN_SECONDS, ACTIVE_MAX_SECONDS),
    }


def is_active_chat(chat_key: str) -> bool:
    state = ACTIVE_CHATS.get(chat_key)
    if not state:
        return False
    return time.time() - state["time"] < state["ttl"]


def expire_chat(chat_key: str):
    ACTIVE_CHATS.pop(chat_key, None)


@lru_cache(maxsize=2048)
def make_chunks(normalized_text: str) -> tuple[str, ...]:
    chunks = set()
    text = normalized_text[:90]
    for n in (2, 3, 4):
        for i in range(max(0, len(text) - n + 1)):
            chunks.add(text[i:i+n])
    return tuple(chunks)


def get_trigger_hits(text: str, include_call_words: bool = False, limit: int = 12) -> list[tuple[str, str]]:
    normalized = normalize_text(text)
    hits = []

    call_norms = set(NORMALIZED_CALL_WORDS)

    for nw, original in NORMALIZED_TRIGGER_PAIRS:
        if not include_call_words and nw in call_norms:
            continue

        if nw in normalized:
            hits.append((nw, original))

        if len(hits) >= limit:
            break

    return hits


def score_entry_by_hits(normalized_text: str, normalized_line: str, hits: list[tuple[str, str]]) -> int:
    score = 0

    for nw, _original in hits:
        if nw and nw in normalized_line:
            score += 80 + min(len(nw), 20)

    # 実際の入力との文字チャンク一致。補助点に留める。
    for chunk in make_chunks(normalized_text):
        if chunk and chunk in normalized_line:
            score += len(chunk)

    return score


def top_entries_by_hits(text: str, entries: list[tuple[str, str]], hits: list[tuple[str, str]], limit: int = 5, min_score: int = 40, scan_limit: int = 2000) -> list[str]:
    if not hits:
        return []

    normalized_text = normalize_text(text)
    scored = []

    for normalized_line, line in entries[:scan_limit]:
        # まず一致語を含む行だけに絞る。これで噛み合わない例を減らす。
        if not any(nw in normalized_line for nw, _ in hits):
            continue

        score = score_entry_by_hits(normalized_text, normalized_line, hits)
        if score >= min_score:
            scored.append((score, line))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [line for _, line in scored[:limit]]


def find_episode_context(context_text: str, hits: list[tuple[str, str]]) -> str:
    normalized_context = normalize_text(context_text)
    scored = []

    for keyword_list, normalized_episode, episode in EPISODE_ENTRIES[:2500]:
        score = 0

        for nk in keyword_list[:10]:
            if nk and nk in normalized_context:
                score += 100 + min(len(nk), 20)

        for nw, _original in hits:
            if nw in normalized_episode:
                score += 70 + min(len(nw), 20)

        if score > 0:
            scored.append((score, episode))

    scored.sort(key=lambda x: x[0], reverse=True)

    seen = set()
    unique = []
    for _score, episode in scored:
        e = episode.strip()
        if e and e not in seen:
            unique.append(e)
            seen.add(e)
        if len(unique) >= 5:
            break

    return "\n".join(unique)


def find_reply_examples(context_text: str, hits: list[tuple[str, str]]) -> str:
    # 一致語を含む返答ペアだけ渡す。これで会話の噛み合わなさをかなり減らす。
    matches = top_entries_by_hits(
        context_text,
        REPLY_PAIR_ENTRIES,
        hits,
        limit=5,
        min_score=45,
        scan_limit=2200
    )
    return "\n".join(matches)


def find_style_examples(context_text: str, hits: list[tuple[str, str]]) -> str:
    matches = top_entries_by_hits(
        context_text,
        STYLE_ENTRIES,
        hits,
        limit=4,
        min_score=45,
        scan_limit=1000
    )
    return "\n".join(matches)


def find_hashimoto_shin_context(context_text: str, hits: list[tuple[str, str]]) -> str:
    if not HASHIMOTO_SHIN_ENTRIES:
        return ""

    normalized_context = normalize_text(context_text)

    # 橋本新が出ている時は橋本新行を積極採用
    if "橋本新" in context_text or normalize_text("橋本新") in normalized_context:
        local_hits = hits + [(normalize_text("橋本新"), "橋本新")]
    else:
        local_hits = hits

    matches = top_entries_by_hits(
        context_text,
        HASHIMOTO_SHIN_ENTRIES,
        local_hits,
        limit=4,
        min_score=35,
        scan_limit=700
    )
    return "\n".join(matches)


def has_episode_hit(context_text: str, hits: list[tuple[str, str]]) -> bool:
    return bool(find_episode_context(context_text, hits))


def has_context_hit(context_text: str) -> tuple[bool, list[tuple[str, str]], bool]:
    hits = get_trigger_hits(context_text, include_call_words=False, limit=12)

    if hits:
        episode_hit = has_episode_hit(context_text, hits)
        return True, hits, episode_hit

    return False, [], False


def should_randomly_join(user_text: str, context_text: str) -> bool:
    # 実務系は呼ばれてない限り黙る
    if looks_unrelated(user_text):
        return False

    has_hit, hits, episode_hit = has_context_hit(context_text)
    if not has_hit:
        return False

    normalized_context = normalize_text(context_text)
    strong_hit = any(word in normalized_context for word in NORMALIZED_STRONG_WORDS)

    if strong_hit:
        return random.random() < STRONG_JOIN_PROBABILITY

    if episode_hit:
        return random.random() < EPISODE_JOIN_PROBABILITY

    return random.random() < RANDOM_JOIN_PROBABILITY


def should_continue_active_chat(user_text: str, context_text: str) -> bool:
    if looks_unrelated(user_text):
        return False

    has_hit, _hits, episode_hit = has_context_hit(context_text)

    if has_hit or episode_hit:
        return random.random() < ACTIVE_STRONG_CONTEXT_PROBABILITY

    # 会話中は「それな」「何で？」みたいな短文にもそこそこ返す
    return random.random() < ACTIVE_WEAK_CONTEXT_PROBABILITY




def strip_call_words_for_echo(text: str) -> str:
    normalized = normalize_text(text)
    for word in NORMALIZED_CALL_WORDS:
        normalized = normalized.replace(word, "")
    return normalized


def is_echo_reply(user_text: str, reply_text: str) -> bool:
    """
    ユーザー発言の単純なおうむ返しを検出する。
    完全一致、ユーザー文の丸ごと含有、3-gram過剰一致を弾く。
    """
    user_core = strip_call_words_for_echo(user_text)
    reply_norm = normalize_text(reply_text)

    if not user_core or not reply_norm:
        return False

    if len(user_core) <= 3:
        return user_core == reply_norm

    if user_core == reply_norm:
        return True

    if len(user_core) >= 4 and user_core in reply_norm:
        return True

    if len(reply_norm) <= len(user_core) + 8 and reply_norm in user_core:
        return True

    chunks = set()
    for i in range(max(0, len(user_core) - 2)):
        chunk = user_core[i:i+3]
        if chunk:
            chunks.add(chunk)

    if not chunks:
        return False

    overlap = sum(1 for c in chunks if c in reply_norm)
    overlap_ratio = overlap / max(1, len(chunks))

    return overlap_ratio >= 0.72 and len(reply_norm) <= len(user_core) + 20


def remove_echo_lines(user_text: str, reply_text: str) -> str:
    user_core = strip_call_words_for_echo(user_text)
    kept = []

    for line in reply_text.splitlines():
        line = line.strip()
        if not line:
            continue

        line_norm = normalize_text(line)

        if user_core and len(user_core) >= 4:
            if line_norm == user_core:
                continue
            if user_core in line_norm and len(line_norm) <= len(user_core) + 12:
                continue

        kept.append(line)

    return "\n".join(kept).strip()


def anti_echo_fallback(user_text: str, context_text: str) -> str:
    """
    おうむ返しになった時の逃げ。
    文脈の強い単語に応じて、短くズラした返答を返す。
    """
    normalized_context = normalize_text(context_text)

    if normalize_text("橋本新") in normalized_context:
        return random.choice([
            "橋本新名言集です。",
            "ｷﾞｬｵｫ。",
            "それは橋本新の方です。",
        ])

    if normalize_text("きゃぴ") in normalized_context:
        return random.choice([
            "きゃぴい(泣)",
            "それは良いです！！",
            "ぼくぅの表情です。",
        ])

    if normalize_text("二郎") in normalized_context or normalize_text("野猿") in normalized_context:
        return random.choice([
            "二郎に着きました。",
            "ブックオフのはずが二郎です。",
            "野猿は難しいです。",
        ])

    if normalize_text("牛角") in normalized_context:
        return random.choice([
            "牛角多すぎます。",
            "探すのてこずりましたすみませんでした。",
            "地図はからっきしだめです。",
        ])

    if normalize_text("エスターク") in normalized_context:
        return random.choice([
            "エスターク青くないですか？",
            "エスタークです！！",
            "それは通常種ではないです。",
        ])

    if normalize_text("フリーポーズ") in normalized_context:
        return random.choice([
            "フリーポーズお願いします。",
            "表情が難しいです。",
            "かわいいでしょ(ﾉ≧▽≦)ﾉ",
        ])

    if normalize_text("地図") in normalized_context or normalize_text("迷子") in normalized_context:
        return random.choice([
            "自分は地図はからっきしだめです。",
            "交番行きます。",
            "無理ゲー(；´д⊂)",
        ])

    return random.choice([
        "難しいです。",
        "それは違います。",
        "お願いします…。",
        "ちょっと分からないです。",
        "そういうことではないです。",
    ])


def avoid_echo(user_text: str, reply_text: str, context_text: str) -> str:
    cleaned = remove_echo_lines(user_text, reply_text)

    if cleaned and not is_echo_reply(user_text, cleaned):
        return cleaned

    return anti_echo_fallback(user_text, context_text)


def shorten_arakun(text: str) -> str:
    if not text:
        return "難しいです。"

    text = text.strip()

    banned_phrases = [
        "こんにちは！", "こんにちは。", "お話しできて嬉しい", "何かお手伝い",
        "もちろんです", "わかりました", "ご質問ありがとうございます",
        "お気軽に聞いてください", "何でも聞いてください", "AIとして",
        "私は", "以下の", "ポイントは", "要するに", "まとめると",
    ]

    for phrase in banned_phrases:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])
    return text[:190] if text else "難しいです。"


def ask_arakun(user_text: str, context_text: str) -> str:
    hits = get_trigger_hits(context_text, include_call_words=True, limit=12)
    matched_words = "、".join(original for _nw, original in hits) if hits else "なし"

    episode_context = find_episode_context(context_text, hits)
    reply_examples = find_reply_examples(context_text, hits)
    style_examples = find_style_examples(context_text, hits)
    hashimoto_shin_context = find_hashimoto_shin_context(context_text, hits)

    arakun_prompt = SYSTEM_PROMPT + """

# Runtime rules

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。

最重要:
いまのユーザー発言・直近文脈に出ている一致単語だけを手がかりにする。
一致単語と関係ない過去例は無視する。
過去例を無理やり使わない。
ただし一致単語がある場合は、その単語に関係するエピソードや返答ペアを優先する。

おうむ返しは禁止。
ユーザー発言をそのまま繰り返さない。
ユーザーの語尾だけ変えて返さない。
「◯◯？」「◯◯です」みたいに、入力文をほぼコピーした返答は禁止。
同じ単語を使う場合でも、過去ログ由来の別フレーズ・エピソード断片に変換して返す。

「あはい…」に頼りすぎない。
口癖だけで返さない。
過去ログにある返答パターンを優先する。

変なところだけ妙に具体的なことがある。
急にテンションが上がることがある。
でも、まったく関係ない話に飛びすぎない。

真面目に解説しすぎない。
質問に全部答えようとしない。
有益なアドバイスを無理に出さない。
ChatGPTっぽい挨拶は禁止。
箇条書きは禁止。

返答は1〜3文。
190文字以内。
LINEの一言として返す。

テンションが上がる話題では使ってよい:
「！！」
「😭」
「きゃぴい」
「ぼくぅの」
「ｷﾞｬｵｫ。」

地図、待ち合わせ、場所の話題では少し混乱してよい。
同じ単語を少し繰り返してよい。
"""

    recent_lines = "\n".join(context_text.splitlines()[-5:])

    user_content = f"""
直近の会話:
{recent_lines}

今回のユーザー発言:
{user_text}

一致した過去ログ/Excel由来ワード:
{matched_words}

関連エピソード:
{episode_context if episode_context else "なし"}

過去の似た返答ペア:
{reply_examples if reply_examples else "なし"}

橋本新として参照できる過去文脈:
{hashimoto_shin_context if hashimoto_shin_context else "なし"}

参考にする口調例:
{style_examples if style_examples else "なし"}

返答方針:
1. 直接呼ばれていたら必ず短く返す。
2. 一致ワードがある場合は、そのワードに関係する過去例だけ使う。
3. 返答ペアがある場合は最優先で真似る。
4. エピソードや橋本新文脈がある場合は断片を自然に混ぜる。
5. 解説ではなくLINEの一言として返す。
6. ユーザー発言をそのまま繰り返さない。質問文をコピーして返さない。
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": arakun_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=1.05,
            max_tokens=130
        )

        text = response.choices[0].message.content
        return avoid_echo(user_text, shorten_arakun(text), context_text)

    except Exception as e:
        print("Groq error:", e)
        return "難しいです…。"


def reply_to_line(reply_token: str, text: str):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
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

        chat_key = get_chat_key(event)
        if not chat_key:
            continue

        context_text = recent_context_text(chat_key, user_text)

        if should_stop(user_text):
            expire_chat(chat_key)
            add_history(chat_key, user_text)
            continue

        called = is_called(user_text)
        active = is_active_chat(chat_key)
        random_join = should_randomly_join(user_text, context_text)

        # 先に履歴へ入れる。次の「それ」「これ」に効かせる。
        add_history(chat_key, user_text)

        if called:
            mark_active(chat_key)
            ai_text = ask_arakun(user_text, context_text)
            reply_to_line(reply_token, ai_text)
            continue

        if active:
            if should_continue_active_chat(user_text, context_text):
                mark_active(chat_key)
                ai_text = ask_arakun(user_text, context_text)
                reply_to_line(reply_token, ai_text)
            continue

        if random_join:
            mark_active(chat_key)
            ai_text = ask_arakun(user_text, context_text)
            reply_to_line(reply_token, ai_text)
            continue

        continue

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
