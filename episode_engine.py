import json
import os
from pathlib import Path

from utils import normalize


IDENTITY_TRIGGERS = {"橋本", "橋本新", "あらた", "あらくん", "顎", "アゴ", "AGODEKA", "LIAR", "ARAKUN", "Unknown", "unknown"}
CRITICAL_SHORT = {"顎", "アゴ", "ムタ", "土居", "牛角", "二郎", "野猿", "LIAR", "Ryo"}


class EpisodeEngine:
    """
    v9 keyword -> episode -> reply engine.

    - episodes.json: keyword -> actual LINE episode windows
    - all_keywords.txt: fallback keyword list, including keywords without episodes
    - no keyword: no reply
    - keyword with no episode: ｷｬﾋﾟｨ
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.episodes_path = self.data_dir / "episodes.json"
        self.all_keywords_path = self.data_dir / "all_keywords.txt"
        self.max_hits = int(os.environ.get("MAX_EPISODE_HITS", "4"))
        self.max_episodes = int(os.environ.get("MAX_EPISODES_PER_TRIGGER", "3"))

        self.episodes = self._load_episodes()
        self.all_keywords = self._load_keywords()

        self.norm_to_key = {}
        for k in self.all_keywords:
            nk = normalize(k)
            if self._usable_keyword(k, nk):
                self.norm_to_key.setdefault(nk, k)
        for k in self.episodes.keys():
            nk = normalize(k)
            if self._usable_keyword(k, nk):
                self.norm_to_key.setdefault(nk, k)

        self.length_buckets = {}
        for nk in self.norm_to_key:
            self.length_buckets.setdefault(len(nk), set()).add(nk)
        self.lengths = sorted(self.length_buckets)

    def _load_episodes(self):
        if not self.episodes_path.exists():
            return {}
        return json.loads(self.episodes_path.read_text(encoding="utf-8"))

    def _load_keywords(self):
        if not self.all_keywords_path.exists():
            return list(self.episodes.keys())
        return [x.strip() for x in self.all_keywords_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def _usable_keyword(self, key: str, nk: str):
        if not nk:
            return False
        if key in CRITICAL_SHORT:
            return True
        if len(nk) <= 2:
            return False
        return True

    def match(self, user_text: str, recent_context: str = ""):
        nt = normalize(user_text)
        nc = normalize(recent_context)
        found = {}

        def scan(text_norm, base_strength):
            L = len(text_norm)
            for l in self.lengths:
                if l > L:
                    break
                bucket = self.length_buckets[l]
                for i in range(0, L - l + 1):
                    sub = text_norm[i:i+l]
                    if sub in bucket:
                        key = self.norm_to_key[sub]
                        item = self.episodes.get(key)
                        has_episode = item is not None and bool(item.get("e"))
                        score = base_strength + l * 10 + (int(item.get("h", 0)) if item else 0)
                        if key in IDENTITY_TRIGGERS:
                            score += 300
                        if has_episode:
                            score += 1000
                        prev = found.get(key)
                        if not prev or score > prev["score"]:
                            found[key] = {
                                "trigger": key,
                                "score": score,
                                "has_episode": has_episode,
                                "episodes": (item.get("e", [])[:self.max_episodes] if item else []),
                            }

        scan(nt, 10000)
        # context only for longer terms
        if recent_context:
            scan(nc, 1500)

        hits = list(found.values())

        # If content triggers exist, keep explicit identity too; avoid context-only call noise.
        hits.sort(key=lambda h: (h["score"], len(h["trigger"])), reverse=True)
        return hits[:self.max_hits]

    def format_episodes(self, hits):
        blocks = []
        for h in hits:
            eps = h.get("episodes", [])[:self.max_episodes]
            if not eps:
                blocks.append(f"trigger:{h['trigger']}\nエピソード:なし")
                continue

            lines = []
            for ep in eps:
                w = (ep.get("w") or "").strip()
                r = (ep.get("r") or "").strip()
                if w:
                    lines.append(f"会話窓:\n{w}")
                if r:
                    lines.append(f"橋本新っぽい返し:{r}")
            blocks.append(f"trigger:{h['trigger']}\n" + "\n---\n".join(lines))

        return "\n\n".join(blocks) if blocks else "なし"
