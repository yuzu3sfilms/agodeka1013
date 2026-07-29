from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, asdict

from japanese_analysis import analyze_content


REPAIR_RE = re.compile(
    r"^(?:え|えっ|え？|え\?|は|は？|は\?|何それ|なにそれ|それ何|どういうこと|どゆこと|意味わからん|意味わからない|違う|ちがう|いや|いやいや)[。！!？?]*$",
    re.I,
)
REFERENCE_RE = re.compile(
    r"(?:それ|その|さっき|今の|今言った|今の話|その話|その種目|その言葉|それって|これは|これって)",
    re.I,
)
FOLLOWUP_RE = re.compile(
    r"(?:で[、,]?(?:どう|何|なに|いつ|どこ|誰|なんで)?|それで|じゃあ|なら|他は|ほかは|具体的に|例えば|たとえば|どれ|どっち|何回|何セット|週何回|どのくらい|どうやる|やり方|何キロ|重さ|回数|頻度)[？?。！!]*$",
    re.I,
)
CONTINUATION_RE = re.compile(r"(?:続き|その後|それから|もっと詳しく|他には|ほかには|で？|それで？)", re.I)
TOPIC_SHIFT_RE = re.compile(r"^(?:ところで|話変わるけど|別の話|関係ないけど|そういえば)", re.I)
QUESTION_RE = re.compile(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|どれ|どっち|いくつ|何回|何セット|何キロ")


@dataclass
class DialogueRelation:
    relation: str
    use_previous_assistant: bool
    use_previous_user: bool
    topic_shift: bool
    confidence: float
    reason: str


class DialogueManager:
    """Single source of truth for conversational continuity.

    It stores role-labelled turns and determines how the current utterance
    relates to the immediately preceding exchange before domain routing.
    """

    def __init__(self, max_turns: int = 12):
        self.max_turns = max(6, int(max_turns))
        self._turns = defaultdict(lambda: deque(maxlen=self.max_turns))

    def add(self, chat_id: str, role: str, text: str):
        text = (text or "").strip()
        if text and role in {"user", "assistant"}:
            self._turns[chat_id].append({"role": role, "text": text})

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

    def classify(self, chat_id: str, user_text: str) -> dict:
        text = (user_text or "").strip()
        last_assistant = self.last(chat_id, "assistant")
        last_user = self.last(chat_id, "user")

        if TOPIC_SHIFT_RE.search(text):
            rel = DialogueRelation("topic_shift", False, False, True, 0.98, "explicit_topic_shift")
        elif last_assistant and REPAIR_RE.fullmatch(text):
            rel = DialogueRelation("repair_request", True, True, False, 0.99, "short_reaction_to_previous_answer")
        elif last_assistant and REFERENCE_RE.search(text):
            relation = "repair_request" if QUESTION_RE.search(text) else "followup"
            rel = DialogueRelation(relation, True, True, False, 0.94, "explicit_reference_to_previous_exchange")
        elif last_assistant and CONTINUATION_RE.search(text):
            rel = DialogueRelation("continuation_request", True, True, False, 0.93, "explicit_continuation")
        elif last_assistant and FOLLOWUP_RE.search(text):
            rel = DialogueRelation("followup", True, True, False, 0.88, "elliptical_followup")
        elif last_assistant and len(text) <= 24 and QUESTION_RE.search(text):
            current_topics = set(analyze_content(text).topics)
            previous_topics = set(analyze_content(last_assistant).topics)
            overlap = current_topics & previous_topics
            if overlap:
                rel = DialogueRelation("followup", True, True, False, 0.86, "topic_overlap_with_previous_answer")
            else:
                rel = DialogueRelation("new_utterance", False, bool(last_user), False, 0.70, "short_question_without_context_link")
        else:
            rel = DialogueRelation("new_utterance", False, bool(last_user), False, 0.70, "no_strong_link_to_previous_answer")

        data = asdict(rel)
        data["last_assistant"] = last_assistant
        data["last_user"] = last_user
        data["history_size"] = len(self._turns[chat_id])
        return data
