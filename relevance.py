import re
from utils import normalize


QUESTION_PATTERNS = {
    "usage": ["何に使", "用途", "使う", "使い道"],
    "person": ["誰", "だれ", "何者", "どいつ"],
    "place": ["どこ", "場所", "行く", "行った"],
    "reason": ["なんで", "なぜ", "理由"],
    "preference": ["好き", "嫌い", "すき", "きらい", "どう思"],
    "action": ["作って", "作る", "やって", "してる", "した", "行きたい"],
}

GENERIC_TERMS = {
    "お前", "俺", "僕", "私", "今日", "明日", "昨日", "それ", "これ", "あれ",
    "する", "なる", "いる", "ある", "ない", "できる", "来る", "行く",
    "使う", "作る", "やる", "見る", "言う", "思う",
}


class RelevanceRanker:
    """
    v12:
    Search retrieves candidates.
    This ranker decides whether they are actually relevant enough to send to Groq.
    """

    def __init__(self):
        self.min_keep_score = 55
        self.strong_score = 85

    def question_type(self, user_text: str):
        nt = normalize(user_text)
        types = []
        for qtype, pats in QUESTION_PATTERNS.items():
            if any(normalize(p) in nt for p in pats):
                types.append(qtype)
        if "?" in user_text or "？" in user_text:
            if not types:
                types.append("question")
        return types

    def _is_strong_term(self, term: str):
        t = term.replace("*", "")
        nt = normalize(t)
        if not nt:
            return False
        if nt in {normalize(x) for x in GENERIC_TERMS}:
            return False
        if len(nt) >= 4:
            return True
        # 2-3 char kanji/katakana/person-ish terms can be strong
        if re.search(r"[一-龥ァ-ヴｦ-ﾟA-Za-z]", t) and len(nt) >= 2:
            return True
        return False

    def _is_predicate(self, term: str):
        return term.endswith("*")

    def score_episode(self, user_text: str, ep: dict, qtypes: list[str]):
        matched = ep.get("matched", []) or []
        window = ep.get("window", "") or ""
        persona = ep.get("persona", "") or ""

        score = 0
        reasons = []

        strong_terms = [m for m in matched if self._is_strong_term(m)]
        pred_terms = [m for m in matched if self._is_predicate(m)]

        if strong_terms:
            score += 38 + min(len(strong_terms), 4) * 10
            reasons.append(f"strong_terms:{','.join(strong_terms[:4])}")

        if pred_terms:
            score += min(len(pred_terms), 4) * 6
            reasons.append(f"predicates:{','.join(pred_terms[:4])}")

        # Penalty: predicate only is weak unless there is a persona line.
        if pred_terms and not strong_terms:
            score -= 28
            reasons.append("predicate_only_penalty")

        if persona and persona != "なし":
            score += 22
            reasons.append("persona_nearby")

        # Query type compatibility.
        nw = normalize(window)
        for qt in qtypes:
            if qt == "usage":
                if any(x in nw for x in ["使", "用途", "組み立て", "ニッパ", "道具"]):
                    score += 24
                    reasons.append("usage_context")
            elif qt == "person":
                if any(x in nw for x in ["名前", "呼", "名乗", "誰", "人物"]):
                    score += 20
                    reasons.append("person_context")
            elif qt == "place":
                if any(x in nw for x in ["行", "店", "駅", "場所", "家", "牛角", "二郎"]):
                    score += 18
                    reasons.append("place_context")
            elif qt == "reason":
                if any(x in nw for x in ["から", "理由", "ため", "ので"]):
                    score += 14
                    reasons.append("reason_context")
            elif qt == "preference":
                if any(x in nw for x in ["好き", "嫌い", "いい", "微妙", "無理"]):
                    score += 18
                    reasons.append("preference_context")
            elif qt == "action":
                if any(x in nw for x in ["作", "やっ", "行", "買", "見", "使"]):
                    score += 16
                    reasons.append("action_context")

        # Penalize very generic windows with no clear matched text.
        if not strong_terms and len(pred_terms) <= 1:
            score -= 18
            reasons.append("weak_match_penalty")

        # If user has a katakana/proper noun and it appears in the window, boost.
        user_chunks = re.findall(r"[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|[一-龥々〆ヵヶ]{2,}", user_text)
        for ch in user_chunks[:6]:
            if normalize(ch) in nw and self._is_strong_term(ch):
                score += 16
                reasons.append(f"user_chunk:{ch}")

        label = "high" if score >= self.strong_score else "mid" if score >= self.min_keep_score else "low"
        return score, label, reasons[:8]

    def rerank(self, user_text: str, search_result: dict, max_selected: int = 2):
        qtypes = self.question_type(user_text)
        episodes = search_result.get("episodes", []) or []

        ranked = []
        for ep in episodes:
            score, label, reasons = self.score_episode(user_text, ep, qtypes)
            ep2 = dict(ep)
            ep2["relevance_score"] = score
            ep2["relevance_label"] = label
            ep2["relevance_reasons"] = reasons
            ranked.append(ep2)

        ranked.sort(key=lambda e: e.get("relevance_score", 0), reverse=True)

        selected = [e for e in ranked if e.get("relevance_score", 0) >= self.min_keep_score][:max_selected]

        result = dict(search_result)
        result["candidate_episodes"] = episodes
        result["reranked_episodes"] = ranked
        result["episodes"] = selected
        result["question_types"] = qtypes
        result["relevance_scores"] = [e.get("relevance_score", 0) for e in selected]
        result["relevance_labels"] = [e.get("relevance_label", "low") for e in selected]
        return result
