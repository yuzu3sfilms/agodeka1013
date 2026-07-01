import re
from utils import normalize


COUNT_PATTERNS = [
    r"([0-9０-９]+)\s*(個|人|枚|回|本|杯|兆個)",
    r"([0-9０-９]+)\s*(兆)\s*(個)?",
]

COUNT_QUESTION_CUES = ["何個", "何人", "何枚", "何回", "何本", "何杯", "いくつ", "どれくらい"]
BAD_COUNT_CONTEXT = ["今日", "明日", "昨日", "何時", "時", "分"]


def _zen_to_han(s: str) -> str:
    table = str.maketrans("０１２３４５６７８９", "0123456789")
    return s.translate(table)


class CanonAnswer:
    """
    v12.5:
    If the retrieved episode already contains the answer,
    do not let Groq invent tense or explanation.

    Example:
    User: 今日はペヤング何個食べるの？
    Episode: ペヤング25個食べてる途中なんでしょ
    Reply: 25個
    """

    def is_count_question(self, user_text: str) -> bool:
        nt = normalize(user_text)
        return any(normalize(cue) in nt for cue in COUNT_QUESTION_CUES)

    def _topic_terms(self, search_result: dict):
        return [t for t in search_result.get("topic_terms", []) if t]

    def _episode_texts(self, search_result: dict):
        eps = search_result.get("episodes", []) or []
        for ep in eps:
            yield ep.get("window", "") or "", ep

    def _extract_counts_near_topic(self, text: str, topic_terms: list[str]):
        found = []
        lines = text.splitlines()

        for line_i, line in enumerate(lines):
            nline = normalize(line)
            topic_hit = any(normalize(t) in nline for t in topic_terms) if topic_terms else True
            if not topic_hit:
                continue

            # Prefer counts on the same line as the topic.
            for m in re.finditer(r"([0-9０-９]+)\s*(兆個|個|人|枚|回|本|杯|兆)", line):
                num = _zen_to_han(m.group(1))
                unit = m.group(2)
                if unit == "兆":
                    unit = "兆個"
                surface = f"{num}{unit}"
                start = max(0, m.start() - 16)
                end = min(len(line), m.end() + 16)
                context = line[start:end]
                found.append({
                    "surface": surface,
                    "num": int(num) if num.isdigit() else 0,
                    "unit": unit,
                    "line": line,
                    "context": context,
                    "line_i": line_i,
                    "same_line_topic": True,
                })

        return found

    def _rank_count(self, count: dict, episode_index: int):
        score = 1000 - episode_index * 50
        line = count.get("line", "")
        context = count.get("context", "")

        # Keep plausible group-lore counts. Avoid absurd exaggeration unless it is the only answer.
        if "兆" in count.get("surface", ""):
            score -= 350

        # If it has "途中" or direct eating context, boost.
        if any(x in line for x in ["途中", "食べ", "食う", "食った"]):
            score += 120

        # If it is phrased as someone else's direct joke about the topic, still useful.
        if any(x in line for x in ["なんでしょ", "でしょ", "じゃん"]):
            score += 30

        # Avoid unrelated timestamps.
        if any(x in context for x in ["時", "分"]) and count.get("unit") not in ["個", "人", "枚", "回", "本", "杯", "兆個"]:
            score -= 200

        return score

    def answer(self, user_text: str, search_result: dict):
        if not self.is_count_question(user_text):
            return None, {"used": False, "reason": "not_count_question"}

        topic_terms = self._topic_terms(search_result)
        if not topic_terms:
            return None, {"used": False, "reason": "no_topic_terms"}

        candidates = []
        for ep_i, (txt, ep) in enumerate(self._episode_texts(search_result)):
            for c in self._extract_counts_near_topic(txt, topic_terms):
                c["episode_index"] = ep_i
                c["score"] = self._rank_count(c, ep_i)
                c["matched"] = ep.get("matched", [])
                candidates.append(c)

        if not candidates:
            return None, {"used": False, "reason": "no_count_near_topic", "topic_terms": topic_terms}

        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        surface = best["surface"]

        # Keep it short. This is a canon answer, not a creative generation.
        if "途中" in best.get("line", "") and surface.endswith("個"):
            reply = f"{surface}の途中"
        else:
            reply = surface

        return reply, {
            "used": True,
            "type": "count",
            "topic_terms": topic_terms,
            "reply": reply,
            "best": {
                "surface": best["surface"],
                "line": best["line"][:160],
                "score": best["score"],
                "matched": best.get("matched", [])[:5],
            },
            "candidates": [
                {
                    "surface": c["surface"],
                    "score": c["score"],
                    "line": c["line"][:120],
                }
                for c in candidates[:5]
            ],
        }
