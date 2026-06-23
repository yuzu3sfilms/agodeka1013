import json
import os
from pathlib import Path

from utils import normalize


GENERIC_BAD = {"んー", "うん", "はい", "えー", "あー", "まあ", "いや", "そう", "ん？", "え？"}


class Retriever:
    """
    v6.1 lite retriever.

    DB同梱をやめ、JSONLを軽くスキャンする。
    返答そのものはGroq生成に任せるので、ここは「参考例」を返すだけ。
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.pairs_path = self.data_dir / "pairs.jsonl"
        self.messages_path = self.data_dir / "messages.jsonl"
        self.keywords_path = self.data_dir / "keywords.txt"

        self.max_pair_scan = int(os.environ.get("MAX_PAIR_SCAN", "3200"))
        self.max_message_scan = int(os.environ.get("MAX_MESSAGE_SCAN", "2400"))
        self.max_keywords = int(os.environ.get("MAX_KEYWORDS", "4500"))

        self.keywords = self._load_keywords()

    def _load_keywords(self):
        if not self.keywords_path.exists():
            return []
        out = []
        with self.keywords_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    n = normalize(line)
                    if len(n) >= 2:
                        out.append(n)
                if len(out) >= self.max_keywords:
                    break
        return out

    def _iter_jsonl(self, path: Path, limit: int):
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _terms(self, text: str):
        nt = normalize(text)
        terms = set()

        for kw in self.keywords:
            if kw and kw in nt:
                terms.add(kw)

        for n in (10, 9, 8, 7, 6, 5, 4, 3):
            for i in range(max(0, len(nt) - n + 1)):
                g = nt[i:i+n]
                if len(g) >= 3:
                    terms.add(g)

        return set(sorted(terms, key=len, reverse=True)[:120])

    def _score(self, query_terms, text: str):
        nt = normalize(text)
        score = 0
        has_long = False

        for t in query_terms:
            if t in nt:
                l = len(t)
                if l >= 7:
                    score += 100 + l
                    has_long = True
                elif l >= 5:
                    score += 55 + l
                    has_long = True
                elif l >= 3:
                    score += 20 + l

        if not has_long:
            score = int(score * 0.4)

        if text.strip() in GENERIC_BAD:
            score -= 120

        return score

    def search(self, context: str, top_pairs: int = 7, top_messages: int = 6):
        q = self._terms(context)

        pair_hits = []
        for p in self._iter_jsonl(self.pairs_path, self.max_pair_scan):
            reply = (p.get("reply") or "").strip()
            if not reply:
                continue

            combined = "\n".join([
                p.get("context_text", ""),
                p.get("last_other", ""),
                reply,
            ])
            score = self._score(q, combined) + self._score(q, p.get("last_other", ""))

            if score > 35:
                pair_hits.append((score, p))

        pair_hits.sort(key=lambda x: x[0], reverse=True)

        msg_hits = []
        for m in self._iter_jsonl(self.messages_path, self.max_message_scan):
            text = (m.get("text") or "").strip()
            if not text:
                continue
            score = self._score(q, text)
            if score > 28:
                msg_hits.append((score, m))

        msg_hits.sort(key=lambda x: x[0], reverse=True)

        return {
            "pairs": [p for s, p in pair_hits[:top_pairs]],
            "messages": [m for s, m in msg_hits[:top_messages]],
            "pair_scores": [s for s, p in pair_hits[:top_pairs]],
            "message_scores": [s for s, m in msg_hits[:top_messages]],
        }
