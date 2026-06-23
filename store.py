import json
import os
import random
from pathlib import Path

from utils import normalize


class HashimotoStore:
    """
    v5.4 no tone limit.

    - 感情補正なし
    - テンション抑制なし
    - 文字数制限なし
    - 返答選択は文脈一致を最優先
    - 起動時巨大indexは作らずRender安全性は維持
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.pairs_path = self.data_dir / "pairs.jsonl"
        self.messages_path = self.data_dir / "messages.jsonl"
        self.keywords_path = self.data_dir / "keywords.txt"
        self.style_profile = self._load_json("style_profile.json", {})
        self.emotion_profile = self._load_json("emotion_profile.json", {})
        self.presence_profile = self._load_json("presence_profile.json", {})

        self.max_pair_scan = int(os.environ.get("MAX_PAIR_SCAN", "2200"))
        self.max_message_scan = int(os.environ.get("MAX_MESSAGE_SCAN", "2200"))
        self.max_keywords = int(os.environ.get("MAX_KEYWORDS", "3500"))

        self.keywords = self._load_keywords_small()
        self.fallback_replies = self._load_fallback_replies()

    def _load_json(self, name: str, default):
        path = self.data_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _load_keywords_small(self) -> list[str]:
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

    def _load_fallback_replies(self) -> list[str]:
        replies = []
        for p in self._iter_jsonl(self.pairs_path, 700):
            r = (p.get("reply") or "").strip()
            if r:
                replies.append(r)
        for m in self._iter_jsonl(self.messages_path, 700):
            t = (m.get("text") or "").strip()
            if t:
                replies.append(t)

        replies += ["難しいです。", "お願いします…。", "ちょっと分からないです。", "それは違います。", "これは良いです。"]

        out, seen = [], set()
        for r in replies:
            if r not in seen:
                out.append(r)
                seen.add(r)
        return out

    def _terms(self, text: str) -> set[str]:
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

        return set(sorted(terms, key=len, reverse=True)[:100])

    def _score(self, query_terms: set[str], candidate_text: str) -> int:
        nc = normalize(candidate_text)
        score = 0
        has_long = False

        for t in query_terms:
            if t in nc:
                l = len(t)
                if l >= 7:
                    score += 90 + l
                    has_long = True
                elif l >= 5:
                    score += 50 + l
                    has_long = True
                elif l >= 3:
                    score += 18 + l

        if not has_long:
            score = int(score * 0.4)

        return score

    def search(self, context: str, top_pairs: int = 8, top_messages: int = 6) -> dict:
        query_terms = self._terms(context)

        pair_hits = []
        for p in self._iter_jsonl(self.pairs_path, self.max_pair_scan):
            reply = p.get("reply", "")
            if not reply:
                continue

            candidate = "\n".join([
                p.get("context_text", ""),
                p.get("last_other", ""),
                reply,
                p.get("emotion", ""),
                p.get("response_function", ""),
                " ".join(p.get("behavior_tags", [])),
            ])

            score = 20 + self._score(query_terms, candidate)
            score += self._score(query_terms, p.get("last_other", ""))

            if score > 25:
                pair_hits.append((score, p))

        pair_hits.sort(key=lambda x: x[0], reverse=True)

        msg_hits = []
        for m in self._iter_jsonl(self.messages_path, self.max_message_scan):
            text = m.get("text", "")
            if not text:
                continue

            candidate = "\n".join([
                text,
                m.get("emotion", ""),
                m.get("response_function", ""),
                " ".join(m.get("behavior_tags", [])),
            ])

            score = self._score(query_terms, candidate)
            if score > 18:
                msg_hits.append((score, m))

        msg_hits.sort(key=lambda x: x[0], reverse=True)

        return {
            "pairs": [p for _s, p in pair_hits[:top_pairs]],
            "messages": [m for _s, m in msg_hits[:top_messages]],
            "pair_scores": [s for s, _p in pair_hits[:top_pairs]],
            "message_scores": [s for s, _m in msg_hits[:top_messages]],
        }

    def local_reply(self, context: str) -> str:
        hits = self.search(context, top_pairs=10, top_messages=8)
        candidates = []
        candidates += [p.get("reply", "") for p in hits["pairs"]]
        candidates += [m.get("text", "") for m in hits["messages"]]

        if self.fallback_replies:
            candidates += random.sample(self.fallback_replies, min(25, len(self.fallback_replies)))

        for c in candidates:
            c = str(c).strip()
            if c:
                return c

        return "難しいです。"
