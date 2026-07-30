from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, asdict

from japanese_analysis import analyze_content
from conversation_context import set_context


REPAIR_RE = re.compile(
    r"^(?:え|えっ|え？|え\?|は|は？|は\?|何それ|なにそれ|それ何|どういうこと|どゆこと|意味わからん|意味わからない|違う|ちがう|いや|いやいや)[。！!？?]*$",
    re.I,
)
REFERENCE_RE = re.compile(
    r"(?:それ|その|あれ|これ|さっき|今の|今言った|今の話|その話|その種目|その言葉|それって|これは|これって|彼|あいつ)",
    re.I,
)
FOLLOWUP_RE = re.compile(
    r"(?:で[、,]?(?:どう|何|なに|いつ|どこ|誰|なんで)?|それで|じゃあ|なら|他は|ほかは|具体的に|例えば|たとえば|どれ|どっち|何回|何セット|週何回|どのくらい|どうやる|やり方|何キロ|重さ|回数|頻度|強くなった|どうだった|届いた|買った|写真ある|どこ変わった)[？?。！!]*$",
    re.I,
)
ELLIPTICAL_QUESTION_RE = re.compile(
    r"^(?:強くなった|どうだった|どうなった|届いた|買った|見た|やった|行った|食べた|使った|写真ある|どこ変わった|何が変わった|良かった|うまかった|大丈夫|本当|マジ)[？?。！!]*$",
    re.I,
)
CONTINUATION_RE = re.compile(r"(?:続き|その後|それから|もっと詳しく|他には|ほかには|で？|それで？)", re.I)
TOPIC_SHIFT_RE = re.compile(r"^(?:ところで|話変わるけど|別の話|関係ないけど|そういえば)", re.I)
QUESTION_RE = re.compile(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|どれ|どっち|いくつ|何回|何セット|何キロ")
GENERIC_TOPICS = {
    "どう", "何", "なに", "誰", "だれ", "どこ", "いつ", "これ", "それ", "あれ",
    "今", "さっき", "話", "質問", "本当", "マジ",
}

# These are predicates / elliptical questions, not conversation subjects.
# Japanese analysis may expose chunks such as 「写真ある」 as topics, so block
# them before subject inheritance is decided.
NON_SUBJECT_QUESTION_RE = re.compile(
    r"^(?:"
    r"強くなった|どうだった|どうなった|届いた|買った|見た|やった|行った|"
    r"食べた|使った|写真ある|写真ない|どこ変わった|何が変わった|"
    r"良かった|うまかった|大丈夫|本当|マジ|"
    r".*(?:ある|ない|なった|だった|変わった|届いた|買った|見た|やった|"
    r"行った|食べた|使った)"
    r")[？?。！!]*$",
    re.I,
)


@dataclass
class DialogueRelation:
    relation: str
    use_previous_assistant: bool
    use_previous_user: bool
    topic_shift: bool
    confidence: float
    reason: str


class DialogueManager:
    """Conversation continuity and omitted-subject resolution for v14.25."""

    def __init__(self, max_turns: int = 12):
        self.max_turns = max(6, int(max_turns))
        self._turns = defaultdict(lambda: deque(maxlen=self.max_turns))
        self._topic_stacks = defaultdict(lambda: deque(maxlen=6))
        self._current_subject = defaultdict(str)

    def add(self, chat_id: str, role: str, text: str):
        text = (text or "").strip()
        if text and role in {"user", "assistant"}:
            self._turns[chat_id].append({"role": role, "text": text})
            if role == "user":
                self._remember_explicit_subject(chat_id, text)

    def turns(self, chat_id: str) -> list[dict]:
        return list(self._turns[chat_id])

    def last(self, chat_id: str, role: str) -> str:
        for turn in reversed(self._turns[chat_id]):
            if turn["role"] == role:
                return turn["text"]
        return ""

    def context(self, chat_id: str, current_user_text: str | None = None, limit: int = 8) -> str:
        turns = self.turns(chat_id)[-max(2, limit):]
        lines = [f"{t['role']}: {t['text']}" for t in turns]
        current = (current_user_text or "").strip()
        if current:
            lines.append(f"user: {current}")
        return "\n".join(lines)

    def _topics(self, text: str) -> list[str]:
        try:
            topics = list(analyze_content(text).topics)
        except Exception:
            topics = []
        cleaned = []
        for topic in topics:
            topic = str(topic or "").strip()
            if not topic or topic in GENERIC_TOPICS or len(topic) <= 1:
                continue
            if topic not in cleaned:
                cleaned.append(topic)
        return cleaned[:6]

    def _looks_followup(self, text: str, has_history: bool) -> bool:
        if not has_history or TOPIC_SHIFT_RE.search(text):
            return False
        if REFERENCE_RE.search(text) or CONTINUATION_RE.search(text):
            return True
        if FOLLOWUP_RE.search(text) or ELLIPTICAL_QUESTION_RE.fullmatch(text):
            return True
        return len(text) <= 18 and bool(QUESTION_RE.search(text))

    def _explicit_subject(self, text: str) -> str:
        # An omitted predicate question must inherit the previous subject.
        # Example: 「写真ある？」 must not become subject=「写真ある」.
        if NON_SUBJECT_QUESTION_RE.fullmatch((text or "").strip()):
            return ""

        topics = self._topics(text)
        if not topics:
            return ""
        # Prefer the longest informative term. This turns
        # 「新あらくん着弾」 into 「新あらくん」 when the analyzer exposes both.
        topics.sort(key=lambda x: (len(x), x), reverse=True)
        for topic in topics:
            if not QUESTION_RE.search(topic) and topic not in GENERIC_TOPICS:
                return topic
        return ""

    def _remember_subject(self, chat_id: str, subject: str):
        subject = (subject or "").strip()
        if not subject:
            return
        self._current_subject[chat_id] = subject
        stack = self._topic_stacks[chat_id]
        try:
            stack.remove(subject)
        except ValueError:
            pass
        stack.appendleft(subject)

    def _remember_explicit_subject(self, chat_id: str, text: str):
        if TOPIC_SHIFT_RE.search(text):
            self._topic_stacks[chat_id].clear()
            self._current_subject[chat_id] = ""
        subject = self._explicit_subject(text)
        if subject and not self._looks_followup(text, bool(self.turns(chat_id))):
            self._remember_subject(chat_id, subject)

    def classify(self, chat_id: str, user_text: str) -> dict:
        text = (user_text or "").strip()
        last_assistant = self.last(chat_id, "assistant")
        last_user = self.last(chat_id, "user")
        has_history = bool(last_assistant or last_user)

        if TOPIC_SHIFT_RE.search(text):
            rel = DialogueRelation("topic_shift", False, False, True, 0.98, "explicit_topic_shift")
        elif last_assistant and REPAIR_RE.fullmatch(text):
            rel = DialogueRelation("repair_request", True, True, False, 0.99, "short_reaction_to_previous_answer")
        elif has_history and REFERENCE_RE.search(text):
            relation = "repair_request" if last_assistant and REPAIR_RE.fullmatch(text) else "followup"
            rel = DialogueRelation(relation, bool(last_assistant), bool(last_user), False, 0.96, "explicit_reference")
        elif has_history and CONTINUATION_RE.search(text):
            rel = DialogueRelation("continuation_request", bool(last_assistant), bool(last_user), False, 0.94, "explicit_continuation")
        elif has_history and (FOLLOWUP_RE.search(text) or ELLIPTICAL_QUESTION_RE.fullmatch(text)):
            rel = DialogueRelation("followup", bool(last_assistant), bool(last_user), False, 0.94, "elliptical_followup")
        elif last_assistant and len(text) <= 24 and QUESTION_RE.search(text):
            rel = DialogueRelation("followup", True, bool(last_user), False, 0.80, "short_question_after_answer")
        else:
            rel = DialogueRelation("new_topic", False, False, False, 0.72, "independent_utterance")

        if rel.topic_shift:
            self._topic_stacks[chat_id].clear()
            self._current_subject[chat_id] = ""

        explicit_subject = self._explicit_subject(text)
        follow_up = rel.relation in {"followup", "continuation_request", "repair_request"}
        current_subject = self._current_subject[chat_id]

        # Explicit references and omitted questions inherit the latest subject.
        inherited = bool(follow_up and current_subject and not explicit_subject)
        resolved_subject = explicit_subject or (current_subject if follow_up else "")
        resolved_query = text

        if inherited and resolved_subject:
            resolved_query = f"{resolved_subject} {text}".strip()
        elif explicit_subject and not follow_up:
            self._remember_subject(chat_id, explicit_subject)
            resolved_subject = explicit_subject

        # v14.25:
        # bot.py's legacy v14.20 continuity branch intercepts plain "followup"
        # before DynamicSearch. Once an omitted subject was successfully inherited,
        # mark it as contextual_followup so it proceeds to resolved-query search and
        # Replay selection. Repair requests still use the correction route.
        routing_relation = rel.relation
        if inherited and rel.relation in {"followup", "continuation_request"}:
            routing_relation = "contextual_followup"

        data = asdict(rel)
        data["relation"] = routing_relation
        data.update({
            "follow_up_question": follow_up,
            "subject_inherited": inherited,
            "explicit_subject": explicit_subject,
            "resolved_subject": resolved_subject,
            "resolved_query": resolved_query,
            "topic_stack": list(self._topic_stacks[chat_id]),
        })

        set_context({
            "chat_id": chat_id,
            "raw_query": text,
            "resolved_query": resolved_query,
            "resolved_subject": resolved_subject,
            "follow_up_question": follow_up,
            "subject_inherited": inherited,
            "topic_shift": rel.topic_shift,
            "topic_stack": list(self._topic_stacks[chat_id]),
            "relation": routing_relation,
            "confidence": rel.confidence,
        })
        return data
