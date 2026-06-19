from difflib import SequenceMatcher
import random

import config
from text_utils import normalize_text


CALL_WORDS = [
    "橋本新", "橋本", "あらた", "あらくん", "あら君", "顎", "アゴ", "あご",
    "AGODEKA", "agodeka", "LIAR", "ARAKUN",
]

AI_PHRASES = [
    "こんにちは！", "こんにちは。", "お話しできて嬉しい", "何かお手伝い",
    "もちろんです", "わかりました", "ご質問ありがとうございます",
    "お気軽に聞いてください", "何でも聞いてください", "AIとして",
    "私はAI", "以下の", "ポイントは", "要するに", "まとめると",
]

# 強すぎる怒り・罵倒・攻撃性を抑えるための断片。
# 目的は人格改変ではなく、過去ログの怒り部分だけが過剰抽出されるのを防ぐこと。
HARSH_FRAGMENTS = [
    "黙", "うるさ", "ふざけ", "キレ", "怒", "キモ", "きも",
    "バカ", "馬鹿", "カス", "ゴミ", "クソ", "くそ",
    "消え", "殴", "殺", "死", "許さ", "最悪", "嫌い", "帰れ",
]

NORMALIZED_CALL_WORDS = [normalize_text(w) for w in CALL_WORDS]
NORMALIZED_HARSH_FRAGMENTS = [normalize_text(w) for w in HARSH_FRAGMENTS]


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
    if ratio >= 0.62 and len(reply_core) <= int(len(user_core) * 1.8) + 8:
        return True

    return False


def anger_score(text: str) -> int:
    nt = normalize_text(text)
    score = 0

    for frag in NORMALIZED_HARSH_FRAGMENTS:
        if frag and frag in nt:
            score += 2

    if text.count("!") + text.count("！") >= 4:
        score += 1
    if "!!!" in text or "！！！" in text:
        score += 1

    return score


def is_too_angry(reply_text: str, user_text: str = "") -> bool:
    if not getattr(config, "ANGER_FILTER_ENABLED", True):
        return False

    if getattr(config, "ALLOW_ANGRY_REPLY_WHEN_USER_ANGRY", False):
        if anger_score(user_text) >= 2:
            return False

    return anger_score(reply_text) >= 2


def clean_reply(text: str) -> str:
    text = (text or "").strip()

    for phrase in AI_PHRASES:
        text = text.replace(phrase, "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:3])

    if not text:
        return "難しいです。"

    return text[:config.MAX_REPLY_CHARS]


def calm_fallbacks(context_text: str = "") -> list[str]:
    nt = normalize_text(context_text)
    candidates = []

    if normalize_text("地図") in nt or normalize_text("迷子") in nt:
        candidates += ["難しいです。", "地図はからっきしだめです。", "お願いします…。"]

    if normalize_text("ゲロ") in nt or normalize_text("胃腸") in nt:
        candidates += ["胃腸が難しいです。", "ちょっと分からないです。", "お願いします…。"]

    if normalize_text("二郎") in nt or normalize_text("牛角") in nt:
        candidates += ["難しいです。", "これは良いです。", "お願いします…。"]

    candidates += [
        "難しいです。",
        "お願いします…。",
        "ちょっと分からないです。",
        "そういうことではないです。",
        "これは良いです。",
        "一旦落ち着きます。",
    ]

    return candidates


def fallback_reply(user_text: str, context_text: str = "") -> str:
    candidates = calm_fallbacks(context_text)
    random.shuffle(candidates)

    for c in candidates:
        if not is_echo(user_text, c) and not is_too_angry(c, user_text):
            return c

    return "難しいです。"


def finalize_reply(user_text: str, raw_text: str, context_text: str = "") -> str:
    reply = clean_reply(raw_text)

    if is_echo(user_text, reply):
        return fallback_reply(user_text, context_text)

    if is_too_angry(reply, user_text):
        return fallback_reply(user_text, context_text)

    return reply
