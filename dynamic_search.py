import gzip
import json
import os
import re
from pathlib import Path

from utils import normalize, angerish


PERSONA_SPEAKERS = {"LIAR  OF  ARAKUN", "Unknown", "橋本新", "Arata Hashimoto"}
CRITICAL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "牛角", "二郎", "野猿", "ムタ", "ムタソ", "きゃぴ", "ｷｬﾋﾟｨ", "ぼくぅ"]

BAD_QUERY_CHUNKS = {
    "お前", "早く", "来い", "遅れる", "何に", "使うの", "作ってるの",
    "あるの", "いるの", "なの", "です", "ます", "した", "して", "から", "ので",
}


class DynamicSearch:
    """
    v10.3:
    - 雑な全n-gram検索を廃止
    - 固有名詞/カタカナ/英数字/漢字語/critical term中心に検索
    - 文章全体の断片で無理やりヒットさせない
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.corpus_path = self.data_dir / "line_corpus.jsonl.gz"
        self.max_hits = int(os.environ.get("MAX_SEARCH_HITS", "6"))
        self.max_windows = int(os.environ.get("MAX_EPISODE_WINDOWS", "4"))
        self.window_before = int(os.environ.get("EPISODE_WINDOW_BEFORE", "4"))
        self.window_after = int(os.environ.get("EPISODE_WINDOW_AFTER", "6"))
        self.min_score = int(os.environ.get("MIN_SEARCH_SCORE", "55"))

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

        for t in CRITICAL_TERMS:
            if normalize(t) in nt:
                terms.add(t)

        # Proper-ish chunks only. No arbitrary sentence ngrams.
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

        # Mixed chunks, but reject sentence-like Japanese.
        for tok in re.findall(r"[A-Za-z0-9一-龥々〆ヵヶァ-ヴｦ-ﾟぁ-んー]{3,}", raw):
            tok = tok.strip()
            if self._good_mixed_term(tok):
                terms.add(tok)

        # Short known/quoted-looking katakana/person terms are important.
        terms = sorted(terms, key=lambda x: (len(normalize(x)), x), reverse=True)
        return terms[:14]

    def _good_term(self, term: str):
        nt = normalize(term)
        if not nt or nt in BAD_QUERY_CHUNKS:
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

        # Reject long sentence-like chunks with particles/auxiliary unless they include katakana/latin/critical term.
        has_katakana_or_latin = bool(re.search(r"[A-Za-zァ-ヴｦ-ﾟ]", term))
        has_critical = any(normalize(t) in nt for t in CRITICAL_TERMS)

        if len(nt) >= 7 and not has_katakana_or_latin and not has_critical:
            return False

        # Reject chunks that look like whole questions/instructions rather than searchable nouns.
        if re.search(r"(から|ので|なら|して|した|れる|られる|たい|来い|何に|使う|作って|遅れる)", term):
            if not has_katakana_or_latin and not has_critical:
                return False

        return True

    def search(self, user_text: str):
        terms = self.extract_terms(user_text)
        norm_terms = [(t, normalize(t)) for t in terms if normalize(t)]

        hits = []
        if not norm_terms:
            return {"terms": [], "hits": [], "episodes": [], "style": self.sample_style([])}

        for i, m in enumerate(self.messages):
            ntext = m.get("n", "")
            if not ntext:
                continue

            score = 0
            matched = []
            for orig, nt in norm_terms:
                if nt in ntext:
                    l = len(nt)
                    score += l * l + 20
                    matched.append(orig)

            if score <= 0:
                continue

            if m.get("p"):
                score += 500
            if i + 1 < len(self.messages) and self.messages[i + 1].get("p"):
                score += 450
            if i + 2 < len(self.messages) and self.messages[i + 2].get("p"):
                score += 250

            # Penalize hits that do not include a strong explicit term.
            if not any(len(normalize(x)) >= 3 for x in matched):
                score -= 80

            if score >= self.min_score:
                hits.append({"i": i, "score": score, "matched": matched[:8], "speaker": m.get("s"), "text": m.get("x")})

        hits.sort(key=lambda h: h["score"], reverse=True)
        hits = hits[:self.max_hits]

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
        return {"terms": terms, "hits": hits, "episodes": episodes, "style": style}

    def sample_style(self, episodes):
        # Prefer persona lines from retrieved episodes.
        lines = []
        for ep in episodes or []:
            for x in ep.get("persona_lines", []):
                if x and x not in lines:
                    lines.append(x)
                if len(lines) >= 10:
                    return lines

        # Fallback: stable style examples from corpus.
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
            if len(line) > 150:
                line = line[:150] + "…"
            lines.append(line)
            if sp in PERSONA_SPEAKERS and 2 <= len(tx.strip()) <= 100:
                persona_lines.append(tx.strip())

        if not lines:
            return None

        return {
            "start": start,
            "end": end,
            "score": hit["score"],
            "matched": hit["matched"],
            "window": "\n".join(lines)[-1000:],
            "persona": " / ".join(persona_lines[:4])[:300],
            "persona_lines": persona_lines[:8],
        }

    def format_episodes(self, result: dict):
        episodes = result.get("episodes", [])
        if not episodes:
            return "なし"

        blocks = []
        for ep in episodes:
            blocks.append(
                f"matched:{', '.join(ep.get('matched', []))}\n"
                f"score:{ep.get('score')}\n"
                f"会話窓:\n{ep.get('window','')}\n"
                f"橋本新系発言:{ep.get('persona','') or 'なし'}"
            )
        return "\n\n---\n\n".join(blocks)

    def format_style(self, result: dict):
        lines = result.get("style", [])[:10]
        return "\n".join(f"- {x}" for x in lines) if lines else "なし"
