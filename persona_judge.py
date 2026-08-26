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
    "だわか", "んだわか", "だわか？", "んだわか？",
]


def _looks_cut_midword(text: str) -> bool:
    """Conservative backup guard for obviously cut generated fragments.

    Avoid rejecting normal casual Japanese without punctuation. Only flag a
    trailing kanji stem that is very likely the start of a longer verb/noun
    when the candidate is sentence-like and has no terminal punctuation.
    """
    t = (text or "").strip()
    if not t or re.search(r"[。！？!?…〜～♪♫♡♥☆]$", t):
        return False
    if len(t) < 8:
        return False
    # A final single kanji immediately following Japanese prose is a common
    # token-limit truncation shape (e.g. "...見落"). Keep this deliberately
    # narrow; finish_reason handling in bot.py is the primary guard.
    return bool(re.search(r"[ぁ-んァ-ヴ一-龥々ー][一-龥]$", t))


def _dialogue_act(text: str) -> str:
    t = text or ""
    if re.search(r"^(?:おい|ねえ|ねぇ|なあ|なぁ|ちょっと).*(?:顎|橋本|あらくん)?[！!。]*$", t):
        return "call"
    if re.search(r"何個|何人|何枚|何回|いくつ|何本|何杯", t):
        return "count_question"
    if re.search(r"どこ|何処", t):
        return "location_question"
    if re.search(r"なんで|なぜ|何故", t):
        return "reason_question"
    if re.search(r"[？?]", t):
        return "question"
    return "statement"


def _candidate_act_matches(candidate: str, user_text: str) -> bool:
    act = _dialogue_act(user_text)
    c = candidate or ""
    if act == "call":
        return bool(re.search(r"なん|何|なに|どうした|用|はい|あはい", c))
    if act == "count_question":
        return bool(re.search(r"[0-9０-９]+", c))
    if act == "location_question":
        return bool(re.search(r"ここ|そこ|あそこ|右|左|上|下|前|後ろ|中|外|わから|分から|知らな", c))
    if act == "reason_question":
        return bool(re.search(r"から|ので|せい|ため|わから|分から|知らな", c))
    if act == "question":
        return bool(re.search(
            r"はい|うん|そう|ある|ない|いる|いない|強|弱|増|減|変わ|"
            r"わから|分から|知らな|たぶん|多分|まだ|もう",
            c,
        ))
    return True


class PersonaJudge:
    """
    Generated-candidate judge.

    Historical Replay length is handled by ActualReplyEngine and is length-neutral.
    This judge still keeps generated replies compact, but dialogue-act and grounding
    now outrank compactness.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.profile = self._load_json(
            self.data_dir / "hashimoto_persona_profile.json",
            {},
        )
        self.topic_canon = self._load_json(
            self.data_dir / "topic_canon_profile.json",
            {},
        )
        self.forbidden = self.profile.get(
            "forbidden_strong",
            ["私は", "俺は", "だぜ", "ないよ", "だよ", "よな", "です", "ます"],
        )
        self.median_len = self.profile.get("length", {}).get("median", 10)
        self.p75_len = self.profile.get("length", {}).get("p75", 18)
        self.common_lines = [
            x.get("text", "")
            for x in self.profile.get("common_lines", [])[:120]
        ]

    def _load_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def topic_terms(self, search_result: dict):
        return [t for t in search_result.get("topic_terms", []) if t]

    def episode_text(self, search_result: dict):
        return "\n".join(
            (episode.get("window", "") or "")
            for episode in search_result.get("episodes", []) or []
        )

    def _numbers_in_episode(self, search_result: dict):
        return re.findall(
            r"[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)",
            self.episode_text(search_result),
        )

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
            lines = [
                x.strip()
                for x in re.split(r"[。！？!?]\s*", raw)
                if x.strip()
            ]

        out = []
        seen = set()
        for candidate in lines:
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= 6:
                break
        return out

    def _content_tokens(self, text: str):
        toks = re.findall(
            r"[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|"
            r"[一-龥々〆ヵヶ]{2,}|[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)",
            text or "",
        )
        bad = {
            "今日", "明日", "昨日", "何個", "何回", "何人", "何枚",
            "予定", "つもり", "好き", "嫌い",
        }
        normalized_bad = {normalize(x) for x in bad}
        out = []
        for token in toks:
            nt = normalize(token)
            if not nt or nt in normalized_bad:
                continue
            out.append(token)
        return out

    def _episode_overlap(self, candidate: str, search_result: dict):
        normalized_episode = normalize(self.episode_text(search_result))
        tokens = self._content_tokens(candidate)
        hits = [
            token
            for token in tokens
            if normalize(token) in normalized_episode
        ]
        return hits, tokens

    def _assertion_supported(self, candidate: str, search_result: dict):
        episode = self.episode_text(search_result)
        for word in ASSERTION_WORDS:
            if word in candidate and word not in episode:
                return False, word
        return True, None

    def score(self, candidate: str, user_text: str, search_result: dict):
        c = (candidate or "").strip()
        nc = normalize(c)
        score = 100
        reasons = []

        if not c:
            return -999, ["empty"]

        if _looks_cut_midword(c):
            return -999, ["truncated_fragment"]

        for bad in BAD_GENERATED_FRAGMENTS:
            if bad in c:
                score -= 90
                reasons.append(f"broken_fragment:{bad}")

        for bad in self.forbidden:
            if bad and bad in c:
                score -= 70
                reasons.append(f"forbidden:{bad}")

        tail = re.sub(r"[。！？!?、\s]+$", "", c)
        for bad_tail in [
            "だぜ", "ぜ", "ないよ", "だよ", "よな", "だよな",
            "だよね", "なんだよね", "です", "ます", "ですね",
        ]:
            if tail.endswith(bad_tail):
                score -= 65
                reasons.append(f"bad_tail:{bad_tail}")

        # Generated replies remain compact, but this is now a soft prior.
        length = len(c)
        if length <= self.p75_len + 4:
            score += 4
            reasons.append("generated_compact_soft")
        elif length > 120:
            score -= 18
            reasons.append("generated_overlong")

        if _candidate_act_matches(c, user_text):
            score += 34
            reasons.append("dialogue_act_match")
        else:
            score -= 44
            reasons.append("dialogue_act_mismatch")

        for explainer in [
            "つまり", "要するに", "ということ", "可能性", "予定", "つもり",
            "一般的", "文脈", "設定", "回答",
        ]:
            if explainer in c:
                score -= 25
                reasons.append(f"explain_or_invent:{explainer}")

        topics = self.topic_terms(search_result)
        overlap_hits, candidate_tokens = self._episode_overlap(
            c,
            search_result,
        )
        if overlap_hits:
            score += 18 + min(len(overlap_hits), 4) * 8
            reasons.append(
                f"episode_overlap:{','.join(overlap_hits[:4])}"
            )
        elif candidate_tokens and search_result.get("episodes"):
            score -= 28
            reasons.append("no_episode_overlap")

        if topics:
            if any(normalize(topic) in nc for topic in topics):
                score += 12
                reasons.append("mentions_topic")
            else:
                score -= 5
                reasons.append("omits_topic")

        supported, bad_assertion = self._assertion_supported(
            c,
            search_result,
        )
        if not supported:
            score -= 55
            reasons.append(f"unsupported_assertion:{bad_assertion}")

        if any(
            key in user_text
            for key in ["何個", "何人", "何枚", "何回", "いくつ"]
        ):
            numbers = self._numbers_in_episode(search_result)
            if numbers:
                clean_numbers = [
                    re.sub(r"\s+", "", number)
                    for number in numbers
                ]
                clean_candidate = re.sub(r"\s+", "", c)
                if any(number in clean_candidate for number in clean_numbers):
                    score += 35
                    reasons.append("canon_number_match")
                else:
                    score -= 45
                    reasons.append("missing_canon_number")

        if any(
            phrase in c
            for phrase in ["予定", "つもり", "食べました", "食べたことある"]
        ):
            score -= 60
            reasons.append("tense_invention")

        if re.search(
            r"(かなと思|と思う|でしょう|しましょう|してください)",
            c,
        ):
            score -= 40
            reasons.append("polished_ai")

        if c in self.common_lines:
            score += 12
            reasons.append("known_line")

        return score, reasons

    def choose(
        self,
        candidates: list[str],
        user_text: str,
        search_result: dict,
    ):
        scored = []
        for candidate in candidates:
            score, reasons = self.score(
                candidate,
                user_text,
                search_result,
            )
            scored.append({
                "text": candidate,
                "score": score,
                "reasons": reasons,
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        if not scored:
            return None, {"chosen": None, "scored": []}

        best = scored[0]
        if best["score"] < 70:
            return None, {
                "chosen": None,
                "scored": scored[:6],
                "rejected": True,
            }

        return best["text"], {
            "chosen": best,
            "scored": scored[:6],
            "rejected": False,
            "evaluation_axes": [
                "semantic",
                "topic",
                "conversation_state",
                "relationship",
                "persona",
                "episode",
            ],
        }
