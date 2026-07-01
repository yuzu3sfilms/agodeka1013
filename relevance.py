import re
from utils import normalize


QUESTION_PATTERNS = {
    "usage": ["何に使", "用途", "使う", "使い道"],
    "person": ["誰", "だれ", "何者", "どいつ"],
    "place": ["どこ", "場所", "行く", "行った"],
    "reason": ["なんで", "なぜ", "理由"],
    "preference": ["好き", "嫌い", "すき", "きらい", "どう思"],
    "action": ["作って", "作る", "やって", "してる", "した", "行きたい", "食べる", "食う"],
}

GENERIC_TERMS = {
    "お前", "俺", "僕", "私", "今日", "明日", "昨日", "それ", "これ", "あれ",
    "する", "なる", "いる", "ある", "ない", "できる", "来る", "行く",
    "使う", "作る", "やる", "見る", "言う", "思う", "食べる", "食う",
}

KATAKANA_RE = re.compile(r"[ァ-ヴｦ-ﾟー]{2,}")
ALNUM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")
KANJI_RE = re.compile(r"[一-龥々〆ヵヶ]{2,}")


class RelevanceRanker:
    """
    v12.3:
    Search retrieves candidates.
    This ranker should NOT kill valuable episodes.
    Strong exact topic terms such as ペヤング / 牛角 / ニッパー must pass.
    """

    def __init__(self):
        self.min_keep_score = 45
        self.strong_score = 80
        self.topic_force_keep_score = 40

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

    def _is_predicate(self, term: str):
        return term.endswith("*")

    def _clean_term(self, term: str):
        return (term or "").replace("*", "").strip()

    def _is_generic(self, term: str):
        return normalize(self._clean_term(term)) in {normalize(x) for x in GENERIC_TERMS}

    def _is_topic_term(self, term: str):
        """
        Topic terms are the terms that should anchor an episode.
        Katakana/product/person/place-ish terms are especially important.
        """
        t = self._clean_term(term)
        nt = normalize(t)
        if not nt or self._is_generic(t):
            return False
        if len(nt) >= 4:
            return True
        if KATAKANA_RE.fullmatch(t):
            return True
        if ALNUM_RE.fullmatch(t):
            return True
        if KANJI_RE.fullmatch(t) and len(nt) >= 2:
            return True
        return False

    def _user_topic_chunks(self, user_text: str):
        chunks = []
        for pat in [KATAKANA_RE, ALNUM_RE, KANJI_RE]:
            chunks.extend(pat.findall(user_text))
        # remove generic / too broad
        out = []
        seen = set()
        for ch in chunks:
            nch = normalize(ch)
            if not nch or nch in seen:
                continue
            if self._is_generic(ch):
                continue
            # 今日みたいな一般語は除外
            if nch in {normalize(x) for x in ["今日", "明日", "昨日", "何個", "何人", "何枚", "何回"]}:
                continue
            seen.add(nch)
            out.append(ch)
        return out[:8]

    def score_episode(self, user_text: str, ep: dict, qtypes: list[str]):
        matched = ep.get("matched", []) or []
        window = ep.get("window", "") or ""
        persona = ep.get("persona", "") or ""

        score = 0
        reasons = []

        nw = normalize(window)
        topic_terms = [m for m in matched if self._is_topic_term(m)]
        pred_terms = [m for m in matched if self._is_predicate(m)]
        user_topics = self._user_topic_chunks(user_text)

        if topic_terms:
            score += 44 + min(len(topic_terms), 4) * 12
            reasons.append(f"topic_terms:{','.join(topic_terms[:4])}")

        # Most important v12.3 fix:
        # If the user's concrete topic appears in the episode window, keep it alive.
        exact_topic_hits = []
        for ch in user_topics:
            if normalize(ch) in nw:
                exact_topic_hits.append(ch)
        if exact_topic_hits:
            score += 42 + min(len(exact_topic_hits), 3) * 12
            reasons.append(f"exact_topic:{','.join(exact_topic_hits[:3])}")

        if pred_terms:
            score += min(len(pred_terms), 4) * 5
            reasons.append(f"predicates:{','.join(pred_terms[:4])}")

        # Predicate-only is weak, but do not punish if an exact topic hit exists.
        if pred_terms and not topic_terms and not exact_topic_hits:
            score -= 25
            reasons.append("predicate_only_penalty")

        if persona and persona != "なし":
            score += 18
            reasons.append("persona_nearby")
        else:
            # Still allow topic episodes, but prefer ones with persona lines.
            score -= 4
            reasons.append("no_persona_small_penalty")

        # Question type compatibility.
        for qt in qtypes:
            if qt == "usage":
                if any(x in nw for x in ["使", "用途", "組み立て", "ニッパ", "道具"]):
                    score += 18
                    reasons.append("usage_context")
            elif qt == "person":
                if any(x in nw for x in ["名前", "呼", "名乗", "誰", "人物"]):
                    score += 16
                    reasons.append("person_context")
            elif qt == "place":
                if any(x in nw for x in ["行", "店", "駅", "場所", "家", "牛角", "二郎"]):
                    score += 14
                    reasons.append("place_context")
            elif qt == "reason":
                if any(x in nw for x in ["から", "理由", "ため", "ので"]):
                    score += 12
                    reasons.append("reason_context")
            elif qt == "preference":
                if any(x in nw for x in ["好き", "嫌い", "いい", "微妙", "無理"]):
                    score += 14
                    reasons.append("preference_context")
            elif qt == "action":
                if any(x in nw for x in ["作", "やっ", "行", "買", "見", "使", "食", "食べ"]):
                    score += 16
                    reasons.append("action_context")

        if not topic_terms and not exact_topic_hits and len(pred_terms) <= 1:
            score -= 16
            reasons.append("weak_match_penalty")

        label = "high" if score >= self.strong_score else "mid" if score >= self.min_keep_score else "low"
        return score, label, reasons[:10]

    def _force_keep_topic_episode(self, user_text: str, ranked: list[dict], max_selected: int):
        """
        If the search found episodes and a concrete topic from the user appears,
        do not return selected_episodes=0. This was killing ペヤング-like cases.
        """
        user_topics = [normalize(x) for x in self._user_topic_chunks(user_text)]
        if not user_topics:
            return []

        kept = []
        for ep in ranked:
            window = normalize(ep.get("window", "") or "")
            matched = [normalize(self._clean_term(m)) for m in ep.get("matched", []) or []]
            if any(t in window or t in matched for t in user_topics):
                ep2 = dict(ep)
                if ep2.get("relevance_score", 0) < self.topic_force_keep_score:
                    ep2["relevance_score"] = self.topic_force_keep_score
                ep2["relevance_label"] = "topic"
                ep2.setdefault("relevance_reasons", []).append("force_keep_topic")
                kept.append(ep2)
            if len(kept) >= max_selected:
                break
        return kept

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

        # v12.3: if exact topic episodes exist, never drop all of them.
        force_kept = []
        if not selected and ranked:
            force_kept = self._force_keep_topic_episode(user_text, ranked, max_selected)
            selected = force_kept

        result = dict(search_result)
        result["candidate_episodes"] = episodes
        result["reranked_episodes"] = ranked
        result["episodes"] = selected
        result["question_types"] = qtypes
        result["relevance_scores"] = [e.get("relevance_score", 0) for e in selected]
        result["relevance_labels"] = [e.get("relevance_label", "low") for e in selected]
        result["relevance_reasons"] = [e.get("relevance_reasons", []) for e in selected]
        result["top_rejected_scores"] = [
            {
                "score": e.get("relevance_score", 0),
                "label": e.get("relevance_label", "low"),
                "matched": e.get("matched", [])[:6],
                "reasons": e.get("relevance_reasons", [])[:6],
            }
            for e in ranked[:5]
            if e not in selected
        ]
        result["force_kept"] = bool(force_kept)
        return result
