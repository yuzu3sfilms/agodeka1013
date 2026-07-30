from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

QUESTION_RE = re.compile(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|どれ|どっち|いくつ")
FOLLOW_UP_RE = re.compile(
    r"^(?:それ|これ|あれ|その|この|あの|彼|あいつ)?\s*"
    r"(?:強くなった|どうだった|どうなった|届いた|買った|見た|ある|いる|できた|変わった|何|なに|どう|どこ|いつ|誰|どれ|どっち)"
    r"(?:の|ん|か|っけ|ですか|ますか)?[？?。！!]*$",
    re.I,
)
REFERENCE_RE = re.compile(r"(?:それ|これ|あれ|その|この|あの|彼|あいつ|そいつ|例の)", re.I)
TOPIC_SHIFT_RE = re.compile(r"^(?:ところで|話変わるけど|別の話|関係ないけど|そういえば)", re.I)

GENERIC_TOPICS = {
    "今日", "明日", "昨日", "それ", "これ", "あれ", "どう", "何", "なに",
    "ある", "いる", "する", "なる", "できる", "強く", "強くなった",
}


@dataclass
class Entity:
    name: str
    kind: str = "unknown"
    aliases: list[str] = field(default_factory=list)
    turn_seen: int = 0


@dataclass
class ConversationState:
    topic_stack: list[str] = field(default_factory=list)
    current_subject: str = ""
    current_entity: Optional[Entity] = None
    last_user_text: str = ""
    last_question: str = ""
    dialogue_type: str = ""
    relationship_state: str = ""
    turn: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ConversationStateEngine:
    """Small, deterministic state layer used before retrieval.

    It deliberately avoids generating an answer.  Its job is to resolve what
    the current message is about, then expose a retrieval query that contains
    the inherited subject when the user omitted it.
    """

    def __init__(self, max_topics: int = 6, subject_ttl: int = 4):
        self.max_topics = max_topics
        self.subject_ttl = subject_ttl

    def update(
        self,
        user_text: str,
        previous: Optional[ConversationState] = None,
        topic_terms: Optional[Iterable[str]] = None,
        entity_kind: str = "unknown",
    ) -> tuple[ConversationState, dict]:
        previous = previous or ConversationState()
        text = (user_text or "").strip()
        turn = previous.turn + 1
        explicit_topics = self._clean_topics(topic_terms or [])
        topic_shift = bool(TOPIC_SHIFT_RE.search(text))
        follow_up = self.is_follow_up(text, explicit_topics)

        if topic_shift:
            inherited_subject = ""
            stack: list[str] = []
        else:
            inherited_subject = previous.current_subject
            stack = list(previous.topic_stack)

        explicit_subject = self._select_subject(explicit_topics, text)
        subject = explicit_subject or (inherited_subject if follow_up else "")

        if explicit_subject:
            stack = self._push_topic(stack, explicit_subject)
        elif follow_up and subject:
            stack = self._push_topic(stack, subject)

        current_entity = previous.current_entity
        if explicit_subject:
            current_entity = Entity(
                name=explicit_subject,
                kind=entity_kind,
                aliases=self._aliases_for(explicit_subject),
                turn_seen=turn,
            )
        elif current_entity and turn - current_entity.turn_seen > self.subject_ttl:
            current_entity = None
            if not explicit_subject:
                subject = ""

        resolved_text = self.resolve_query(text, subject, follow_up)
        dialogue_type = "follow_up_question" if follow_up else ("question" if QUESTION_RE.search(text) else "statement")

        state = ConversationState(
            topic_stack=stack[-self.max_topics :],
            current_subject=subject or explicit_subject,
            current_entity=current_entity,
            last_user_text=text,
            last_question=text if QUESTION_RE.search(text) else previous.last_question,
            dialogue_type=dialogue_type,
            relationship_state=previous.relationship_state,
            turn=turn,
        )
        metadata = {
            "follow_up_question": follow_up,
            "subject_inherited": bool(follow_up and not explicit_subject and subject),
            "explicit_subject": explicit_subject,
            "resolved_subject": subject,
            "resolved_query": resolved_text,
            "topic_shift": topic_shift,
        }
        return state, metadata

    def is_follow_up(self, text: str, explicit_topics: Iterable[str] = ()) -> bool:
        stripped = (text or "").strip()
        if not stripped or TOPIC_SHIFT_RE.search(stripped):
            return False
        topics = self._clean_topics(explicit_topics)
        concrete = [t for t in topics if t not in GENERIC_TOPICS]
        if concrete:
            return False
        if REFERENCE_RE.search(stripped):
            return True
        if FOLLOW_UP_RE.search(stripped):
            return True
        return bool(QUESTION_RE.search(stripped) and len(stripped) <= 14)

    def resolve_query(self, text: str, subject: str, follow_up: bool) -> str:
        text = (text or "").strip()
        if not follow_up or not subject:
            return text
        # Keep the original wording; prepend context instead of destructively
        # replacing pronouns. This gives retrieval both semantic signals.
        return f"{subject} {text}".strip()

    def _clean_topics(self, topics: Iterable[str]) -> list[str]:
        out: list[str] = []
        for topic in topics:
            t = str(topic or "").strip()
            if not t or t in GENERIC_TOPICS or t in out:
                continue
            out.append(t)
        return out

    def _select_subject(self, topics: list[str], text: str) -> str:
        if topics:
            # Longest term generally preserves a named entity such as
            # "新あらくん" over the nested alias "あらくん".
            return sorted(topics, key=len, reverse=True)[0]
        # Conservative fallback for short noun-like announcements.
        cleaned = re.sub(r"[？?。！!、,]", "", text).strip()
        cleaned = re.sub(r"(?:着弾|到着|届いた|買った|来た|完成)$", "", cleaned).strip()
        if 2 <= len(cleaned) <= 20 and not QUESTION_RE.search(text):
            return cleaned
        return ""

    def _push_topic(self, stack: list[str], topic: str) -> list[str]:
        return [x for x in stack if x != topic] + [topic]

    def _aliases_for(self, subject: str) -> list[str]:
        aliases = ["それ", "これ", "あれ", "その", "この", "あの"]
        if any(x in subject for x in ("くん", "さん", "君", "橋本", "あら")):
            aliases.extend(["彼", "あいつ", "そいつ"])
        return aliases
