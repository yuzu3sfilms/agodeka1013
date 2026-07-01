import json
import re
from pathlib import Path

from utils import normalize


class PersonaJudge:
    """
    v13:
    Global persona judge.

    The model is no longer trusted to return one answer.
    Candidates are judged against:
    - global Hashimoto profile
    - topic canon
    - retrieved episodes
    - style guard principles
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.profile = self._load_json(self.data_dir / "hashimoto_persona_profile.json", {})
        self.topic_canon = self._load_json(self.data_dir / "topic_canon_profile.json", {})

        self.forbidden = self.profile.get("forbidden_strong", [
            "私は", "俺は", "だぜ", "ないよ", "だよ", "よな", "です", "ます"
        ])
        self.median_len = self.profile.get("length", {}).get("median", 10)
        self.p75_len = self.profile.get("length", {}).get("p75", 18)
        self.common_lines = [x.get("text", "") for x in self.profile.get("common_lines", [])[:120]]

    def _load_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def topic_terms(self, search_result: dict):
        return [t for t in search_result.get("topic_terms", []) if t]

    def episode_text(self, search_result: dict):
        return "\n".join((ep.get("window", "") or "") for ep in search_result.get("episodes", []) or [])

    def _numbers_in_episode(self, search_result: dict):
        txt = self.episode_text(search_result)
        return re.findall(r"[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)", txt)

    def split_candidates(self, raw: str):
        """
        Ask Groq for several candidates, but accept messy output too.
        """
        if not raw:
            return []
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^[\-\*\d\.\)、\)]\s*", "", line).strip()
            line = re.sub(r"^候補[A-Da-d0-9]*[:：]\s*", "", line).strip()
            if line:
                lines.append(line)

        if not lines:
            # fallback split by Japanese sentences
            lines = [x.strip() for x in re.split(r"[。！？!?]\s*", raw) if x.strip()]

        # de-dup, keep short-ish
        out = []
        seen = set()
        for x in lines:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
            if len(out) >= 6:
                break
        return out

    def score(self, candidate: str, user_text: str, search_result: dict):
        c = (candidate or "").strip()
        nc = normalize(c)
        score = 100
        reasons = []

        if not c:
            return -999, ["empty"]

        # Forbidden words / endings
        for bad in self.forbidden:
            if bad and bad in c:
                score -= 70
                reasons.append(f"forbidden:{bad}")

        tail = re.sub(r"[。！？!?、\s]+$", "", c)
        for bad_tail in ["だぜ", "ぜ", "ないよ", "だよ", "よな", "だよな", "だよね", "なんだよね", "です", "ます", "ですね"]:
            if tail.endswith(bad_tail):
                score -= 65
                reasons.append(f"bad_tail:{bad_tail}")

        # Length: Hashimoto median is around 10, p75 around 18.
        l = len(c)
        if l <= 4:
            score += 8
            reasons.append("very_short")
        elif l <= self.p75_len + 4:
            score += 12
            reasons.append("compact")
        elif l <= 45:
            score -= 12
            reasons.append("slightly_long")
        else:
            score -= 45
            reasons.append("too_long")

        # Explanation smell
        explainers = ["つまり", "要するに", "ということ", "可能性", "予定", "つもり", "食べたこと", "一般的", "文脈", "設定", "回答"]
        for x in explainers:
            if x in c:
                score -= 25
                reasons.append(f"explain_or_invent:{x}")

        # Canon/topic grounding
        topics = self.topic_terms(search_result)
        ep_text = self.episode_text(search_result)
        nep = normalize(ep_text)

        if topics:
            topic_hit = any(normalize(t) in nc for t in topics)
            if topic_hit:
                score += 15
                reasons.append("mentions_topic")
            else:
                # Short answers like "25個" may omit topic, so do not over-penalize if number is canon.
                score -= 8
                reasons.append("omits_topic")

        # If episode has numbers and user asked count, prefer candidate that uses the same number.
        if any(x in user_text for x in ["何個", "何人", "何枚", "何回", "いくつ"]):
            nums = self._numbers_in_episode(search_result)
            if nums:
                clean_nums = [re.sub(r"\s+", "", x) for x in nums]
                if any(n in re.sub(r"\s+", "", c) for n in clean_nums):
                    score += 35
                    reasons.append("canon_number_match")
                else:
                    score -= 45
                    reasons.append("missing_canon_number")

        # Avoid inventing tense/action not in evidence
        if any(x in c for x in ["予定", "つもり", "食べました", "食べたことある"]):
            score -= 60
            reasons.append("tense_invention")

        # If candidate is too polished
        if re.search(r"(かなと思|と思う|でしょう|しましょう|してください)", c):
            score -= 40
            reasons.append("polished_ai")

        # Repetition exact common line can be okay if short
        if c in self.common_lines:
            score += 12
            reasons.append("known_line")

        return score, reasons

    def choose(self, candidates: list[str], user_text: str, search_result: dict):
        scored = []
        for cand in candidates:
            s, rs = self.score(cand, user_text, search_result)
            scored.append({"text": cand, "score": s, "reasons": rs})
        scored.sort(key=lambda x: x["score"], reverse=True)
        if not scored:
            return None, {"chosen": None, "scored": []}

        best = scored[0]
        # Hard floor: if all candidates are bad, reject.
        if best["score"] < 55:
            return None, {"chosen": None, "scored": scored[:6], "rejected": True}

        return best["text"], {"chosen": best, "scored": scored[:6], "rejected": False}
