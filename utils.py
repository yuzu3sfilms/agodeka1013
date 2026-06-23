import unicodedata
from difflib import SequenceMatcher


CALL_NAMES = ["橋本新", "橋本", "あらた", "あらくん", "顎", "agodeka", "AGODEKA"]


def normalize(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


def trim_reply(text: str, limit: int = 120) -> str:
    text = (text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines[:2])
    return text[:limit] if text else "難しいです。"


def strip_call_names(text: str) -> str:
    t = normalize(text)
    for name in CALL_NAMES:
        t = t.replace(normalize(name), "")
    for ch in "!?。、,.…・「」『』（）()[]【】\n\r\t":
        t = t.replace(ch, "")
    return t


def too_similar(user_text: str, reply: str) -> bool:
    u = strip_call_names(user_text)
    r = strip_call_names(reply)
    if not u or not r:
        return False
    if u == r:
        return True
    if len(u) >= 4 and u in r:
        return True
    if len(r) >= 4 and r in u:
        return True
    return SequenceMatcher(None, u, r).ratio() >= 0.66 and len(r) <= len(u) + 20


HARSH = [
    "黙", "うるさ", "ふざけ", "キレ", "怒", "キモ", "きも",
    "バカ", "馬鹿", "カス", "ゴミ", "クソ", "くそ",
    "消え", "殴", "殺", "死", "許さ", "最悪", "嫌い", "帰れ",
]


def harsh_score(text: str) -> int:
    nt = normalize(text)
    score = sum(1 for w in HARSH if normalize(w) in nt)
    if text.count("!") + text.count("！") >= 4:
        score += 1
    return score


def too_harsh(text: str) -> bool:
    return harsh_score(text) >= 2


def remove_ai_phrases(reply: str) -> str:
    banned = [
        "こんにちは", "もちろんです", "ご質問ありがとうございます", "AIとして",
        "何かお手伝い", "以下の", "ポイントは", "要するに", "まとめると",
        "橋本新として", "私は", "申し訳ありません",
    ]
    for b in banned:
        reply = reply.replace(b, "")
    return reply.strip()


def clean_reply(user_text: str, reply: str, limit: int = 120) -> str:
    reply = trim_reply(remove_ai_phrases(reply), limit=limit)
    if too_similar(user_text, reply):
        return "難しいです。"
    if too_harsh(reply):
        return "難しいです。"
    return reply or "難しいです。"
