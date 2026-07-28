"""Lightweight Japanese utterance analysis without a morphological dependency.

The goal is not full linguistic parsing. It separates conversational function words
from content-bearing noun/predicate chunks consistently across routing and retrieval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


SEGMENT_RE = re.compile(
    r"[一-龥々〆ヵヶ]+[ぁ-んー]*|[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{1,}|[0-9０-９]+(?:個|人|枚|回|本|杯)?"
)

QUESTION_END_RE = re.compile(r"(?:[？?]+|ですか|ますか|なの|のか|か)$")
CONDITIONAL_END_RE = re.compile(r"(?:たら|なら|れば|えば|けば|せば|ば|と)$")
VERB_END_RE = re.compile(
    r"(?:して|した|する|される|された|させる|って|った|いて|いた|いだ|んだ|れて|れた|れる|られる|"
    r"てる|ていた|たい|ない|なかった|ます|ました|ません|よう|ろ|よ)$"
)
PARTICLE_ENDINGS = ("について", "として", "から", "まで", "より", "って", "は", "が", "を", "に", "で", "と", "も", "へ", "の")
FUNCTION_WORDS = {
    "これ", "それ", "あれ", "ここ", "そこ", "今日", "明日", "昨日", "何", "なに", "どう", "なんで",
    "です", "ます", "ください", "お聞かせ", "感想", "話", "説明", "意味", "場合", "とき", "時",
}


@dataclass(frozen=True)
class ContentAnalysis:
    topics: tuple[str, ...]
    predicates: tuple[str, ...]
    segments: tuple[str, ...]
    conditional_question: bool


def _strip_question_surface(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"[？?！!。．]+$", "", value)
    value = re.sub(r"(?:ください|下さい)$", "", value)
    return value


def _strip_particle(token: str) -> str:
    for ending in PARTICLE_ENDINGS:
        if token.endswith(ending) and len(token) >= len(ending) + 2:
            return token[: -len(ending)]
    return token


def _predicate_stem(token: str) -> str:
    value = token
    # Conditional suffix belongs to the utterance act, not to retrieval content.
    for suffix in ("たら", "なら", "れば", "えば", "けば", "せば"):
        if value.endswith(suffix) and len(value) >= len(suffix) + 2:
            value = value[: -len(suffix)]
            break
    # Preserve both a readable surface and a compact stem where possible.
    for suffix in ("して", "した", "する", "された", "される", "させる", "って", "った", "いて", "いた", "れて", "れた", "れる", "られる", "てる", "たい", "ない", "ます", "ました"):
        if value.endswith(suffix) and len(value) >= len(suffix) + 1:
            stem = value[: -len(suffix)]
            return stem if len(stem) >= 1 else value
    return value


def analyze_content(text: str) -> ContentAnalysis:
    raw = _strip_question_surface(text)
    conditional = bool(re.search(r"(?:たら|なら|れば|えば|けば|せば|ば)(?:どうなる|どう|いい|よい)?$", raw))
    segments = tuple(SEGMENT_RE.findall(raw))

    topics: list[str] = []
    predicates: list[str] = []
    for original in segments:
        token = _strip_particle(original)
        if not token or token in FUNCTION_WORDS or len(token) < 2:
            continue

        predicate_like = bool(VERB_END_RE.search(original)) or bool(CONDITIONAL_END_RE.search(original))
        if predicate_like:
            stem = _predicate_stem(original)
            if len(stem) >= 2 and stem not in FUNCTION_WORDS:
                predicates.append(stem)
            # A leading nominal portion such as 手すり in 手すり折って is already
            # separated by SEGMENT_RE when the next kanji starts, so do not guess here.
            continue

        if token not in FUNCTION_WORDS:
            topics.append(token)

    return ContentAnalysis(
        topics=tuple(dict.fromkeys(topics)),
        predicates=tuple(dict.fromkeys(predicates)),
        segments=segments,
        conditional_question=conditional,
    )
