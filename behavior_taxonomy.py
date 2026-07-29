"""Shared, deterministic behaviour taxonomy for persona compilation and runtime.

Keeping this classifier in one place prevents the offline compiler and replay
engine from silently assigning different names to the same behaviour.
"""
from __future__ import annotations

import re

MEDIA = {"[写真]", "[動画]", "[スタンプ]", ""}


def classify_reply(text: str) -> str:
    r = (text or "").strip()
    if not r:
        return "empty"
    if re.fullmatch(r"[wｗ笑]+", r, re.I) or any(x in r for x in ("笑", "草")):
        return "reaction_laugh"
    if re.fullmatch(r"(?:え|えっ|は|ん|何|なに)[？?！!。…]*", r):
        return "reaction_surprise"
    if re.search(r"ありがとう|あざ", r):
        return "thanks"
    if re.search(r"すみません|ごめん", r):
        return "apology"
    if re.search(r"どこ|何時|いつ|誰|だれ|なんで|なぜ|どう", r) and re.search(r"[？?]", r):
        return "question_specific"
    if re.search(r"[？?]", r):
        return "question_general"
    if re.search(r"やめ|無理|嫌|だめ|ダメ", r):
        return "negative_advice"
    if len(r) <= 4:
        return "very_short"
    if len(r) <= 12:
        return "short_statement"
    if len(r) <= 30:
        return "medium_statement"
    return "long_statement"


def classify_stimulus(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return "no_context"
    if value in MEDIA:
        return "media"
    if re.search(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう", value):
        return "question"
    if re.search(r"ごめん|すみません", value):
        return "apology"
    if re.search(r"ありがとう|あざ", value):
        return "thanks"
    if len(value) <= 5:
        return "short_reaction"
    return "statement"
