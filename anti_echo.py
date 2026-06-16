from difflib import SequenceMatcher
import random
import config
from text_utils import normalize_text

CALL_NAMES = ["橋本新", "橋本 新", "橋本", "あらた", "あらくん", "顎", "アゴ", "AGODEKA"]
CALL_NAMES_N = [normalize_text(x) for x in CALL_NAMES]

AI_PHRASES = [
    "こんにちは", "お手伝い", "ご質問ありがとうございます", "もちろんです", "わかりました",
    "お気軽に", "何でも聞いて", "AIとして", "私はAI", "要するに", "まとめると",
]


def simplify(text: str) -> str:
    nt = normalize_text(text)
    for n in CALL_NAMES_N:
        nt = nt.replace(n, "")
    for ch in "!?！？。、,.…・「」『』（）()[]【】\n\r\t":
        nt = nt.replace(ch, "")
    return nt


def is_echo(user_text: str, reply_text: str) -> bool:
    u = simplify(user_text)
    r = simplify(reply_text)
    if not u or not r:
        return False
    if u == r:
        return True
    if len(u) <= 5 and u in r and len(r) <= len(u) + 6:
        return True
    if len(u) >= 4 and u in r:
        return True
    if len(r) >= 4 and r in u:
        return True
    ratio = SequenceMatcher(None, u, r).ratio()
    return ratio >= 0.64 and len(r) <= int(len(u) * 1.8) + 8


def clean_reply(text: str) -> str:
    text = (text or "").strip()
    for p in AI_PHRASES:
        text = text.replace(p, "")
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    text = "\n".join(lines[:3])
    if not text:
        return "難しいです。"
    return text[:config.MAX_REPLY_CHARS]


def fallback_reply(user_text: str = "") -> str:
    # Minimal generic Hashimoto-ish short replies. Used only when model fails or echoes.
    options = [
        "難しいです。",
        "お願いします…",
        "それは違います。",
        "ちょっと分からないです。",
        "これは良いです。",
        "そういうことではないです。",
    ]
    random.shuffle(options)
    for x in options:
        if not is_echo(user_text, x):
            return x
    return "難しいです。"


def finalize(user_text: str, raw_reply: str) -> str:
    reply = clean_reply(raw_reply)
    if is_echo(user_text, reply):
        return fallback_reply(user_text)
    return reply
