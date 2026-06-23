import unicodedata
from difflib import SequenceMatcher


CALL_NAMES = ["橋本新", "橋本", "あらた", "あらくん", "顎", "agodeka", "AGODEKA"]


def normalize(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


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
    return SequenceMatcher(None, u, r).ratio() >= 0.76 and len(r) <= len(u) + 20


def remove_ai_phrases(reply: str) -> str:
    banned = [
        "こんにちは", "もちろんです", "ご質問ありがとうございます", "AIとして",
        "何かお手伝い", "以下の", "ポイントは", "要するに", "まとめると",
        "橋本新として", "私はAI", "申し訳ありません",
    ]
    for b in banned:
        reply = reply.replace(b, "")
    return reply.strip()


def clean_reply(user_text: str, reply: str) -> str:
    reply = remove_ai_phrases(reply or "").strip()
    if not reply:
        return ""
    if too_similar(user_text, reply):
        return ""
    return reply
