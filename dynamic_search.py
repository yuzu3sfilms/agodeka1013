import gzip
import json
import os
import re
from pathlib import Path

from utils import normalize, angerish


PERSONA_SPEAKERS = {"LIAR  OF  ARAKUN", "Unknown", "橋本新", "Arata Hashimoto"}

CRITICAL_TERMS = [
    "顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた",
    "牛角", "二郎", "野猿", "ムタ", "ムタソ", "ペヤング",
    "きゃぴ", "ｷｬﾋﾟｨ", "ぼくぅ",
]

# These can be searched only when no concrete topic exists.
GENERIC_TERMS = {
    "今日", "明日", "昨日", "何個", "何人", "何枚", "何回", "何時",
    "お前", "俺", "僕", "私", "それ", "これ", "あれ",
    "する", "なる", "いる", "ある", "ない", "できる", "来る", "行く",
    "食べる", "食う", "使う", "作る", "やる", "見る", "言う", "思う",
}

BAD_QUERY_CHUNKS = {
    "お前", "何に", "なの", "です", "ます", "した", "して", "から", "ので",
    "あるの", "いるの", "それ", "これ", "あれ",
}

PREDICATE_VARIANTS = {
    "遅れる": ["遅れ", "遅刻", "遅い", "遅れる", "遅れて", "遅れた"],
    "遅れ": ["遅れ", "遅刻", "遅い", "遅れる"],
    "遅刻": ["遅刻", "遅れ", "遅い"],
    "早く来い": ["早く", "来い", "来て", "集合", "遅れ", "遅刻"],
    "来い": ["来い", "来て", "来る", "来た", "集合"],
    "来る": ["来る", "来た", "来て", "来い", "集合"],
    "行きたい": ["行きたい", "行く", "行った", "行こ", "行け"],
    "行く": ["行く", "行った", "行きたい", "行こ"],
    "使う": ["使う", "使った", "使って", "用途", "何に使"],
    "使った": ["使う", "使った", "使って"],
    "作る": ["作る", "作った", "作って", "組み立て"],
    "作って": ["作る", "作った", "作って", "組み立て"],
    "作ってる": ["作る", "作った", "作って", "組み立て"],
    "欲しい": ["欲しい", "ほしい", "欲し", "いる", "要る"],
    "いる": ["いる", "要る", "必要"],
    "要る": ["要る", "いる", "必要"],
    "買う": ["買う", "買った", "買って", "購入"],
    "買った": ["買う", "買った", "購入"],
    "好き": ["好き", "すき", "好み"],
    "嫌い": ["嫌い", "きらい", "苦手"],
    "やる": ["やる", "やった", "やって"],
    "やった": ["やる", "やった", "やって"],
    "見る": ["見る", "見た", "見て"],
    "見た": ["見る", "見た", "見て"],
    "知ってる": ["知ってる", "知る", "知った"],
    "知る": ["知ってる", "知る", "知った"],
    "呼ぶ": ["呼ぶ", "呼ん", "呼ばれ", "名乗"],
    "名乗": ["名乗", "呼ばれ", "呼ぶ"],
    "食べる": ["食べる", "食べた", "食う", "食った", "何個", "ペヤング"],
    "食う": ["食う", "食った", "食べる", "食べた"],
}

KATAKANA_RE = re.compile(r"[ァ-ヴｦ-ﾟー]{2,}")
ALNUM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")
KANJI_RE = re.compile(r"[一-龥々〆ヵヶ]{2,}")


class DynamicSearch:
    """
    v12.4:
    Topic-first retrieval.

    If a concrete topic exists, such as ペヤング, 牛角, 二郎, ニッパー,
    do NOT fill the hit list with generic terms like 今日.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.corpus_path = self.data_dir / "line_corpus.jsonl.gz"
        self.max_hits = int(os.environ.get("MAX_SEARCH_HITS", "12"))
        self.max_windows = int(os.environ.get("MAX_EPISODE_WINDOWS", "6"))
        self.window_before = int(os.environ.get("EPISODE_WINDOW_BEFORE", "4"))
        self.window_after = int(os.environ.get("EPISODE_WINDOW_AFTER", "6"))
        self.min_score = int(os.environ.get("MIN_SEARCH_SCORE", "35"))

        self.messages = []
        self.persona_style_lines = []
        self._load_corpus()

    def _load_corpus(self):
        if not self.corpus_path.exists():
            return
        with gzip.open(self.corpus_path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                    self.messages.append(m)
                    if m.get("p") and m.get("x") and not angerish(m.get("x", "")):
                        tx = m["x"].strip()
                        if 2 <= len(tx) <= 80:
                            self.persona_style_lines.append(tx)
                except Exception:
                    continue

    def extract_terms(self, user_text: str):
        raw = user_text or ""
        nt = normalize(raw)

        terms = set()
        predicates = set()

        for t in CRITICAL_TERMS:
            if normalize(t) in nt:
                terms.add(t)

        patterns = [
            r"[A-Za-z][A-Za-z0-9_\-]{2,}",
            r"[ァ-ヴｦ-ﾟー]{2,}",
            r"[一-龥々〆ヵヶ]{2,}",
        ]
        for pat in patterns:
            for tok in re.findall(pat, raw):
                tok = tok.strip()
                if self._good_term(tok):
                    terms.add(tok)

        # Mixed chunks are dangerous. Keep only if they contain katakana/latin/critical.
        for tok in re.findall(r"[A-Za-z0-9一-龥々〆ヵヶァ-ヴｦ-ﾟぁ-んー]{3,}", raw):
            tok = tok.strip()
            if self._good_mixed_term(tok):
                terms.add(tok)

        predicates.update(self.extract_predicates(raw))

        terms = sorted(terms, key=lambda x: (len(normalize(x)), x), reverse=True)[:14]
        preds = sorted(predicates, key=lambda x: (len(normalize(x)), x), reverse=True)[:20]

        topic_terms = [t for t in terms if self._is_topic_term(t)]
        generic_terms = [t for t in terms if not self._is_topic_term(t)]

        return terms, preds, topic_terms, generic_terms

    def extract_predicates(self, raw: str):
        nt = normalize(raw)
        preds = set()

        for cue, variants in PREDICATE_VARIANTS.items():
            if normalize(cue) in nt:
                for v in variants:
                    if self._good_predicate(v):
                        preds.add(v)

        surfaces = re.findall(r"[一-龥々〆ヵヶぁ-んー]{2,}(?:る|た|てる|て|たい|ない|れる|られる|しい|い)", raw)
        for s in surfaces:
            if not self._good_predicate(s):
                continue
            preds.add(s)
            for suf in ["てる", "れる", "られる", "たい", "ない", "しい", "る", "た", "て", "い"]:
                if s.endswith(suf) and len(s) > len(suf) + 1:
                    stem = s[:-len(suf)]
                    if self._good_predicate(stem):
                        preds.add(stem)
                    break

        return preds

    def _good_predicate(self, term: str):
        nt = normalize(term)
        if not nt:
            return False
        if nt in {normalize(x) for x in BAD_QUERY_CHUNKS}:
            return False
        if len(nt) < 2:
            return False
        if nt in {"する", "なる", "いる", "ある"}:
            return False
        return True

    def _good_term(self, term: str):
        nt = normalize(term)
        if not nt:
            return False
        if nt in {normalize(x) for x in BAD_QUERY_CHUNKS}:
            return False
        if len(nt) <= 1:
            return False
        if re.fullmatch(r"\d+", nt):
            return False
        return True

    def _good_mixed_term(self, term: str):
        nt = normalize(term)
        if not self._good_term(term):
            return False

        has_katakana_or_latin = bool(re.search(r"[A-Za-zァ-ヴｦ-ﾟ]", term))
        has_critical = any(normalize(t) in nt for t in CRITICAL_TERMS)

        # Japanese sentence-like chunks are usually bad, e.g. 今日はペヤング何個食べるの
        if len(nt) >= 7 and not has_katakana_or_latin and not has_critical:
            return False

        if re.search(r"(から|ので|なら|して|した|れる|られる|たい|来い|何に|何個|使う|作って|食べる|遅れる)", term):
            if not has_katakana_or_latin and not has_critical:
                return False

        return True

    def _is_topic_term(self, term: str):
        t = term or ""
        nt = normalize(t)
        if not nt:
            return False
        if nt in {normalize(x) for x in GENERIC_TERMS}:
            return False
        if KATAKANA_RE.fullmatch(t):
            return True
        if ALNUM_RE.fullmatch(t):
            return True
        if any(normalize(c) == nt for c in CRITICAL_TERMS):
            return True
        # 2+ kanji names/places can be topic, but avoid broad temporal/count words
        if re.search(r"(何個|何回|何人|何枚|何時|食|飲|使|作|行|来|見る|買)", t):
            return False
        if KANJI_RE.fullmatch(t) and nt not in {normalize(x) for x in ["今日", "明日", "昨日", "何個", "何回"]}:
            return True
        return False

    def _score_message(self, i: int, m: dict, queries: list[tuple[str, str, str]], topic_mode: bool):
        ntext = m.get("n", "")
        if not ntext:
            return None

        score = 0
        matched = []
        has_topic_match = False

        for orig, nt, kind in queries:
            if nt in ntext:
                l = len(nt)
                if kind == "topic":
                    score += l * l + 120
                    has_topic_match = True
                elif kind == "term":
                    score += l * l + 18
                else:
                    score += max(12, l * 6)
                matched.append(f"{orig}" if kind != "predicate" else f"{orig}*")

        if score <= 0:
            return None

        # If topic mode is active, ignore hits that do not match the topic.
        if topic_mode and not has_topic_match:
            return None

        if m.get("p"):
            score += 500
        if i + 1 < len(self.messages) and self.messages[i + 1].get("p"):
            score += 450
        if i + 2 < len(self.messages) and self.messages[i + 2].get("p"):
            score += 250
        if i + 3 < len(self.messages) and self.messages[i + 3].get("p"):
            score += 150

        if score < self.min_score:
            return None

        return {"i": i, "score": score, "matched": matched[:10], "speaker": m.get("s"), "text": m.get("x"), "has_topic": has_topic_match}

    def _run_search(self, queries, topic_mode: bool):
        hits = []
        for i, m in enumerate(self.messages):
            h = self._score_message(i, m, queries, topic_mode=topic_mode)
            if h:
                hits.append(h)
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:self.max_hits]

    def search(self, user_text: str):
        terms, predicates, topic_terms, generic_terms = self.extract_terms(user_text)

        topic_queries = [(t, normalize(t), "topic") for t in topic_terms if normalize(t)]
        generic_queries = [(t, normalize(t), "term") for t in generic_terms if normalize(t)]
        pred_queries = [(t, normalize(t), "predicate") for t in predicates if normalize(t)]

        if not topic_queries and not generic_queries and not pred_queries:
            return {
                "terms": [], "predicates": [], "topic_terms": [], "generic_terms": [],
                "hits": [], "episodes": [], "style": self.sample_style([]),
                "search_mode": "empty",
            }

        # Topic-first:
        # 1) If concrete topic exists, search only topic terms first.
        # 2) If no topic hits, fallback to generic/predicate.
        search_mode = "topic_first" if topic_queries else "general"
        hits = []

        if topic_queries:
            hits = self._run_search(topic_queries, topic_mode=True)
            if not hits:
                # fallback, but log it explicitly
                search_mode = "topic_miss_fallback_general"
                hits = self._run_search(topic_queries + generic_queries + pred_queries, topic_mode=False)
        else:
            hits = self._run_search(generic_queries + pred_queries, topic_mode=False)

        episodes = []
        seen_ranges = set()
        for h in hits:
            ep = self._window(h["i"], h)
            if not ep:
                continue
            key = (ep["start"], ep["end"])
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            episodes.append(ep)
            if len(episodes) >= self.max_windows:
                break

        style = self.sample_style(episodes)
        return {
            "terms": terms,
            "predicates": predicates,
            "topic_terms": topic_terms,
            "generic_terms": generic_terms,
            "hits": hits,
            "episodes": episodes,
            "style": style,
            "search_mode": search_mode,
        }

    def sample_style(self, episodes):
        lines = []
        for ep in episodes or []:
            for x in ep.get("persona_lines", []):
                if x and x not in lines:
                    lines.append(x)
                if len(lines) >= 10:
                    return lines

        for x in self.persona_style_lines[:400]:
            if x and x not in lines:
                lines.append(x)
            if len(lines) >= 10:
                break
        return lines

    def _window(self, idx: int, hit: dict):
        start = max(0, idx - self.window_before)
        end = min(len(self.messages), idx + self.window_after + 1)
        lines = []
        persona_lines = []

        for j in range(start, end):
            m = self.messages[j]
            tx = m.get("x", "")
            if angerish(tx):
                continue
            sp = m.get("s", "")
            role = "橋本新" if sp in PERSONA_SPEAKERS else sp
            line = f"{role}: {tx}"
            if len(line) > 120:
                line = line[:120] + "…"
            lines.append(line)
            if sp in PERSONA_SPEAKERS and 2 <= len(tx.strip()) <= 120:
                persona_lines.append(tx.strip())

        if not lines:
            return None

        return {
            "start": start,
            "end": end,
            "score": hit["score"],
            "matched": hit["matched"],
            "has_topic": hit.get("has_topic", False),
            "window": "\n".join(lines)[-900:],
            "persona": " / ".join(persona_lines[:4])[:260],
            "persona_lines": persona_lines[:8],
        }

    def format_episodes(self, result: dict):
        episodes = result.get("episodes", [])
        if not episodes:
            return "なし"

        blocks = []
        for ep in episodes:
            blocks.append(
                f"hit:{', '.join(ep.get('matched', [])[:5])}\n"
                f"{ep.get('window','')}\n"
                f"橋本新:{ep.get('persona','') or 'なし'}"
            )
        return "\n\n---\n\n".join(blocks)

    def format_style(self, result: dict):
        lines = result.get("style", [])[:10]
        return "\n".join(f"- {x}" for x in lines) if lines else "なし"
