import gzip
import json
import os
import re
from pathlib import Path

from utils import normalize, angerish


PERSONA_SPEAKERS = {"LIAR  OF  ARAKUN", "Unknown", "橋本新", "Arata Hashimoto"}
CRITICAL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "牛角", "二郎", "野猿", "ムタ", "ムタソ", "きゃぴ", "ｷｬﾋﾟｨ", "ぼくぅ"]


class DynamicSearch:
    """
    v10:
    No fixed trigger list as the main mechanism.

    Runtime process:
    user text -> extract terms -> full corpus search -> episode windows -> Groq
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.corpus_path = self.data_dir / "line_corpus.jsonl.gz"
        self.max_hits = int(os.environ.get("MAX_SEARCH_HITS", "6"))
        self.max_windows = int(os.environ.get("MAX_EPISODE_WINDOWS", "4"))
        self.window_before = int(os.environ.get("EPISODE_WINDOW_BEFORE", "4"))
        self.window_after = int(os.environ.get("EPISODE_WINDOW_AFTER", "6"))
        self.min_score = int(os.environ.get("MIN_SEARCH_SCORE", "35"))

        self.messages = []
        self._load_corpus()

    def _load_corpus(self):
        if not self.corpus_path.exists():
            return
        with gzip.open(self.corpus_path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    self.messages.append(json.loads(line))
                except Exception:
                    continue

    def extract_terms(self, user_text: str):
        raw = user_text or ""
        nt = normalize(raw)
        terms = set()

        for t in CRITICAL_TERMS:
            if normalize(t) in nt:
                terms.add(t)

        # Extract visible chunks dynamically.
        patterns = [
            r"[A-Za-z][A-Za-z0-9_\-]{2,}",
            r"[ァ-ヴｦ-ﾟー]{2,}",
            r"[一-龥々〆ヵヶ]{2,}",
            r"[ぁ-んー]{3,}",
            r"[A-Za-z0-9一-龥々〆ヵヶァ-ヴｦ-ﾟぁ-んー]{3,}",
        ]
        for pat in patterns:
            for tok in re.findall(pat, raw):
                tok = tok.strip()
                if self._good_term(tok):
                    terms.add(tok)

        # Add Japanese character ngrams from normalized text as fallback.
        # This catches unknown proper nouns not in dictionaries.
        for n in (8, 7, 6, 5, 4, 3, 2):
            if len(nt) < n:
                continue
            for i in range(0, len(nt) - n + 1):
                g = nt[i:i+n]
                if self._good_norm_term(g):
                    terms.add(g)

        # Prefer longer terms; cap to prevent noisy huge prompts.
        terms = sorted(terms, key=lambda x: (len(normalize(x)), x), reverse=True)
        return terms[:30]

    def _good_term(self, term: str):
        return self._good_norm_term(normalize(term))

    def _good_norm_term(self, nt: str):
        if not nt:
            return False
        stop = {
            "です", "ます", "した", "して", "ない", "ある", "いる", "する", "なる",
            "これ", "それ", "あれ", "ここ", "そこ", "さん", "くん", "ちゃん",
            "今日", "明日", "昨日", "時間", "研究", "line", "http", "https", "www", "com",
            "の研究", "したい", "いの", "たいの",
        }
        if nt in stop:
            return False
        if len(nt) <= 1:
            return False
        if len(nt) <= 2 and nt not in {normalize(x) for x in CRITICAL_TERMS}:
            # avoid fragments like ティ
            if re.fullmatch(r"[ぁ-んァ-ヴーｦ-ﾟ]+", nt):
                return False
            if re.fullmatch(r"[a-z0-9]+", nt):
                return False
        if re.fullmatch(r"\d+", nt):
            return False
        return True

    def search(self, user_text: str):
        terms = self.extract_terms(user_text)
        norm_terms = [(t, normalize(t)) for t in terms if normalize(t)]

        hits = []
        if not norm_terms:
            return {"terms": [], "hits": [], "episodes": []}

        for i, m in enumerate(self.messages):
            ntext = m.get("n", "")
            if not ntext:
                continue

            score = 0
            matched = []
            for orig, nt in norm_terms:
                if nt in ntext:
                    l = len(nt)
                    score += l * l + 10
                    matched.append(orig)

            if score <= 0:
                continue

            # Prefer hits involving persona speakers or followed by persona.
            if m.get("p"):
                score += 500
            if i + 1 < len(self.messages) and self.messages[i + 1].get("p"):
                score += 400
            if i + 2 < len(self.messages) and self.messages[i + 2].get("p"):
                score += 200

            # Prefer longer exact user chunks.
            if normalize(user_text) in ntext:
                score += 300

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

        return {"terms": terms, "hits": hits, "episodes": episodes}

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
            if sp in PERSONA_SPEAKERS:
                persona_lines.append(tx[:130])

        if not lines:
            return None

        return {
            "start": start,
            "end": end,
            "score": hit["score"],
            "matched": hit["matched"],
            "window": "\n".join(lines)[-1000:],
            "persona": " / ".join(persona_lines[:4])[:300],
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
