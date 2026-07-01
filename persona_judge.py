import json
import re
from pathlib import Path

from utils import normalize


ASSERTION_WORDS = [
    "好き", "嫌い", "すき", "きらい", "苦手", "得意",
    "予定", "つもり", "食べました", "食べたこと", "行ったこと",
    "はず", "絶対", "いつも", "普段",
]

BAD_GENERATED_FRAGMENTS = [
    "だわか", "んだわか", "だわか？", "んだわか？"
]


class PersonaJudge:
    """
    v13.2:
    Global persona judge + grounding judge.

    Compactness alone is not enough.
    A candidate must be grounded in:
    - retrieved episode text
    - topic canon
    - user text / previous context
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
            lines = [x.strip() for x in re.split(r"[。！？!?]\s*", raw) if x.strip()]

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

    def _content_tokens(self, text: str):
        toks = re.findall(r"[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|[一-龥々〆ヵヶ]{2,}|[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)", text or "")
        bad = {"今日", "明日", "昨日", "何個", "何回", "何人", "何枚", "予定", "つもり", "好き", "嫌い"}
        out = []
        for t in toks:
            nt = normalize(t)
            if not nt or nt in {normalize(x) for x in bad}:
                continue
            out.append(t)
        return out

    def _episode_overlap(self, candidate: str, search_result: dict):
        ep = self.episode_text(search_result)
        nep = normalize(ep)
        toks = self._content_tokens(candidate)
        hits = []
        for t in toks:
            if normalize(t) in nep:
                hits.append(t)
        return hits, toks

    def _assertion_supported(self, candidate: str, search_result: dict):
        ep = self.episode_text(search_result)
        for w in ASSERTION_WORDS:
            if w in candidate and w not in ep:
                return False, w
        return True, None

    def score(self, candidate: str, user_text: str, search_result: dict):
        c = (candidate or "").strip()
        nc = normalize(c)
        score = 100
        reasons = []

        if not c:
            return -999, ["empty"]

        for bad in BAD_GENERATED_FRAGMENTS:
            if bad in c:
                score -= 90
                reasons.append(f"broken_fragment:{bad}")

        for bad in self.forbidden:
            if bad and bad in c:
                score -= 70
                reasons.append(f"forbidden:{bad}")

        tail = re.sub(r"[。！？!?、\s]+$", "", c)
        for bad_tail in ["だぜ", "ぜ", "ないよ", "だよ", "よな", "だよな", "だよね", "なんだよね", "です", "ます", "ですね"]:
            if tail.endswith(bad_tail):
                score -= 65
                reasons.append(f"bad_tail:{bad_tail}")

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

        explainers = ["つまり", "要するに", "ということ", "可能性", "予定", "つもり", "一般的", "文脈", "設定", "回答"]
        for x in explainers:
            if x in c:
                score -= 25
                reasons.append(f"explain_or_invent:{x}")

        topics = self.topic_terms(search_result)
        ep_text = self.episode_text(search_result)
        nep = normalize(ep_text)

        # Grounding check: candidates should echo episode facts/phrases, not just be short.
        overlap_hits, cand_tokens = self._episode_overlap(c, search_result)
        if overlap_hits:
            score += 18 + min(len(overlap_hits), 4) * 8
            reasons.append(f"episode_overlap:{','.join(overlap_hits[:4])}")
        elif cand_tokens and search_result.get("episodes"):
            score -= 28
            reasons.append("no_episode_overlap")

        if topics:
            topic_hit = any(normalize(t) in nc for t in topics)
            if topic_hit:
                score += 12
                reasons.append("mentions_topic")
            else:
                # Omission is okay only when candidate is direct canon number or known line.
                score -= 5
                reasons.append("omits_topic")

        supported, bad_assert = self._assertion_supported(c, search_result)
        if not supported:
            score -= 55
            reasons.append(f"unsupported_assertion:{bad_assert}")

        # Count questions: must preserve canon number.
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

        if any(x in c for x in ["予定", "つもり", "食べました", "食べたことある"]):
            score -= 60
            reasons.append("tense_invention")

        if re.search(r"(かなと思|と思う|でしょう|しましょう|してください)", c):
            score -= 40
            reasons.append("polished_ai")

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

        # Hard floor. Do not pick random compact nonsense.
        if best["score"] < 70:
            return None, {"chosen": None, "scored": scored[:6], "rejected": True}

        return best["text"], {"chosen": best, "scored": scored[:6], "rejected": False}
