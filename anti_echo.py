import random
from difflib import SequenceMatcher

from config import MAX_REPLY_CHARS
from text_utils import normalize_text


AI_PHRASES = [
    "こんにちは！", "こんにちは。", "お話しできて嬉しい", "何かお手伝い",
    "もちろんです", "わかりました", "ご質問ありがとうございます",
    "お気軽に聞いてください", "何でも聞いてください", "AIとして",
    "私は", "以下の", "ポイントは", "要するに", "まとめると",
]

CALL_WORDS = [
    "あらくん", "あら君", "橋本", "橋本新", "顎", "アゴ", "あご",
    "AGODEKA", "agodeka", "LIAR", "ARAKUN",
]

NORMALIZED_CALL_WORDS = [normalize_text(w) for w in CALL_WORDS]


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

    if len(user_core) <= 5:
        if user_core in reply_core and len(reply_core) <= len(user_core) + 6:
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

    if not text:
        return "難しいです。"

    return text[:MAX_REPLY_CHARS]


def fallback_reply(user_text: str, context_text: str = "") -> str:
    nt = normalize_text(context_text)
    candidates = []

    # ここは「特定語を強く拾う」ためではなく、おうむ返し回避時の逃げ先。
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


def finalize_reply(user_text: str, raw_text: str, context_text: str = "") -> str:
    reply = clean_reply(raw_text)

    if not is_echo(user_text, reply):
        return reply

    return fallback_reply(user_text, context_text)
