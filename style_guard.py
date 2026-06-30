import re


BAD_PHRASES = [
    "私は", "わたしは", "私が", "わたしが", "俺は", "おれは", "俺が", "おれが",
    "AIとして", "私はAI", "わたしはAI", "橋本新では", "本人では",
    "だぜ", "するぜ", "いくぜ", "やるぜ", "ぜ。",
    "ないよ", "だよ", "よな", "だよな", "なんだよね", "だよね",
    "ですね", "です。", "ます。", "ましょう", "ください",
    "と思います", "と思うよ", "と思うんだ",
]

BAD_ENDINGS = [
    "だぜ", "ぜ", "ないよ", "だよ", "よな", "だよな", "なんだよね", "だよね",
    "ですね", "です", "ます", "ましょう",
]

AI_SMELL = [
    "〜", "ということ", "つまり", "要するに", "可能性がある",
    "適切", "文脈", "ユーザー", "生成", "回答", "説明",
    "まず", "次に", "一方で", "ただし",
]

SAFE_SHORTS = [
    "そう",
    "まあ",
    "無理",
    "あり",
    "ない",
    "それ",
    "え？",
    "なんで",
    "きゃぴい",
    "ｷｬﾋﾟｨ",
    "なるほど",
]


def _strip_bad_first_person(text: str) -> str:
    t = text
    # Remove explicit first-person subjects. Prefer subject omission.
    t = re.sub(r"(私は|わたしは|私が|わたしが|俺は|おれは|俺が|おれが)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _soft_replace_endings(text: str) -> str:
    t = text.strip()

    replacements = [
        ("だぜ", ""),
        ("するぜ", "する"),
        ("いくぜ", "行く"),
        ("やるぜ", "やる"),
        ("ないよ", "ない"),
        ("だよな", ""),
        ("よな", ""),
        ("なんだよね", ""),
        ("だよね", ""),
        ("だよ", ""),
        ("ですね", ""),
        ("です", ""),
        ("ます", ""),
        ("ましょう", ""),
        ("ください", ""),
        ("と思います", ""),
        ("と思うよ", ""),
        ("と思うんだ", ""),
    ]
    for a, b in replacements:
        t = t.replace(a, b)

    # Sentence final cleanup.
    t = re.sub(r"[。\.]+$", "", t).strip()
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(、、|。。)", "、", t)
    return t


def _shorten(text: str, max_chars: int = 34) -> str:
    t = text.strip()
    # Keep only first sentence-ish chunk.
    parts = re.split(r"[。！？!?]\s*", t)
    if parts and parts[0]:
        t = parts[0].strip()
    if len(t) > max_chars:
        # Cut at Japanese comma if possible.
        comma = t.find("、")
        if 4 <= comma <= max_chars:
            t = t[:comma].strip()
        else:
            t = t[:max_chars].strip()
    return t


def looks_bad(text: str) -> bool:
    if not text or not text.strip():
        return True
    t = text.strip()

    if any(p in t for p in BAD_PHRASES):
        return True

    tail = re.sub(r"[。！？!?、\s]+$", "", t)
    if any(tail.endswith(e) for e in BAD_ENDINGS):
        return True

    if len(t) >= 55:
        return True

    # Too explanatory / ChatGPT-ish.
    smell_count = sum(1 for p in AI_SMELL if p in t)
    if smell_count >= 2:
        return True

    # Multi-sentence tidy explanation smells bot-like for this persona.
    if len(re.findall(r"[。！？!?]", t)) >= 2:
        return True

    return False


def guard_reply(text: str, user_text: str = "") -> tuple[str, dict]:
    """
    Returns: cleaned_reply, info
    Does not try to be fancy. The goal is to avoid obvious non-Hashimoto outputs.
    """
    original = text or ""
    t = original.strip()

    info = {
        "changed": False,
        "bad_before": looks_bad(t),
        "reason": [],
    }

    if not t:
        return "ｷｬﾋﾟｨ", {**info, "changed": True, "reason": ["empty"]}

    # Never allow explicit AI/persona disclaimers.
    if any(x in t for x in ["AIとして", "私はAI", "橋本新では", "本人では"]):
        return "ｷｬﾋﾟｨ", {**info, "changed": True, "reason": ["ai_disclaimer"]}

    before = t
    t = _strip_bad_first_person(t)
    if t != before:
        info["changed"] = True
        info["reason"].append("first_person_removed")

    before = t
    t = _soft_replace_endings(t)
    if t != before:
        info["changed"] = True
        info["reason"].append("bad_ending_replaced")

    before = t
    t = _shorten(t)
    if t != before:
        info["changed"] = True
        info["reason"].append("shortened")

    # If it still smells too much, collapse to a safe short reaction.
    if looks_bad(t):
        # If user asked direct identity-ish question, answer as called.
        if any(x in user_text for x in ["誰", "だれ", "あらくん", "橋本", "顎", "お前"]):
            return "あらくん", {**info, "changed": True, "reason": info["reason"] + ["identity_fallback"]}
        return "ｷｬﾋﾟｨ", {**info, "changed": True, "reason": info["reason"] + ["fallback_capyi"]}

    if not t:
        return "ｷｬﾋﾟｨ", {**info, "changed": True, "reason": info["reason"] + ["blank_after_clean"]}

    info["bad_after"] = looks_bad(t)
    return t, info
