import re
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
    if len(r) <= len(u) + 2 and (u in r or r in u):
        return True
    if len(u) >= 8 and len(r) >= 8:
        ratio = SequenceMatcher(None, u, r).ratio()
        if ratio >= 0.86 and len(r) <= len(u) + 20:
            return True
    return False


def remove_ai_phrases(reply: str) -> str:
    banned = [
        "こんにちは", "もちろんです", "ご質問ありがとうございます", "AIとして",
        "何かお手伝い", "以下の", "ポイントは", "要するに", "まとめると",
        "橋本新として", "私はAI", "申し訳ありません",
    ]
    for b in banned:
        reply = reply.replace(b, "")
    return reply.strip()


def de_ai_tone(reply: str) -> str:
    """
    生成後に最低限AIっぽい丁寧語/説明語を落とす。
    過剰変換しすぎない。
    """
    r = reply or ""
    r = remove_ai_phrases(r)

    # Common AI-ish endings.
    r = r.replace("だよね", "だわ")
    r = r.replace("なんだよね", "なんだわ")
    r = r.replace("ですよね", "だわ")
    r = r.replace("ですね", "")
    r = r.replace("ます！", "るわ")
    r = r.replace("ます。", "るわ")
    r = r.replace("ます", "る")
    r = r.replace("です！", "だわ")
    r = r.replace("です。", "だわ")
    r = r.replace("です", "だわ")

    # Avoid safety-advice-ish phrase.
    r = r.replace("気を付けて使うよ", "使うやつ")
    r = r.replace("気を付けて", "")

    # Trim overly explanatory connective endings.
    r = re.sub(r"。.*(ということ|という感じ|というわけ).*", "。", r)

    # Too much punctuation.
    r = r.replace("！！", "!")
    r = r.replace("！", "")
    r = r.strip()
    return r


def clean_reply(user_text: str, reply: str) -> str:
    reply = remove_ai_phrases(reply or "").strip()
    if not reply:
        return ""
    if too_similar(user_text, reply):
        return ""
    return reply


ANGER_TERMS = ["黙", "うるさ", "ふざけ", "キレ", "怒", "バカ", "馬鹿", "カス", "ゴミ", "クソ", "くそ", "消え", "殴", "殺", "死", "帰れ"]

def angerish(text: str) -> bool:
    return any(t in (text or "") for t in ANGER_TERMS)
