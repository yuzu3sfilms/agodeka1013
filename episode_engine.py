import json
import os
from pathlib import Path

from utils import normalize


IDENTITY_TRIGGERS = {"橋本", "橋本新", "あらた", "あらくん", "顎", "アゴ", "AGODEKA", "LIAR", "ARAKUN", "Unknown", "unknown"}
CRITICAL_SHORT = {"顎", "アゴ", "ムタ", "土居", "牛角", "二郎", "野猿", "LIAR", "Ryo", "きゃぴ", "ｷｬﾋﾟｨ"}


class EpisodeEngine:
    """
    v9.1 reaction boost.

    v9の問題:
    - 短い/汎用triggerが混ざる
    - 長いキーワードより部分語が勝つことがある
    - context由来triggerが反応を濁す
    - エピソードなしkeywordで即ｷｬﾋﾟｨになりやすい

    v9.1:
    - ユーザー発言中の明示triggerを最優先
    - 長いkeyword優先
    - 長いhitに内包される短いhitを削除
    - identity trigger（顎など）は明示されていたら残す
    - エピソードなしhitは、内包/被内包するepisode付きkeywordを探して補完
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

        # Longest first is important.
        self.norm_items = sorted(self.norm_to_key.items(), key=lambda x: len(x[0]), reverse=True)
        self.episode_norm_items = sorted(
            [(normalize(k), k) for k in self.episodes.keys() if self._usable_keyword(k, normalize(k))],
            key=lambda x: len(x[0]),
            reverse=True,
        )

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
        # Runtime guard against garbage fragments.
        if len(nk) <= 3 and key not in CRITICAL_SHORT and key not in IDENTITY_TRIGGERS:
            return False
        return True

    def _make_hit(self, key: str, base_score: int, explicit: bool):
        item = self.episodes.get(key)
        has_episode = item is not None and bool(item.get("e"))
        nk = normalize(key)
        score = base_score + len(nk) * 30 + (int(item.get("h", 0)) if item else 0)
        if key in IDENTITY_TRIGGERS:
            score += 500
        if has_episode:
            score += 2000
        return {
            "trigger": key,
            "norm": nk,
            "score": score,
            "explicit": explicit,
            "has_episode": has_episode,
            "episodes": (item.get("e", [])[:self.max_episodes] if item else []),
        }

    def _prune_contained(self, hits):
        # Keep explicit identity. For content, if shorter hit is contained in a longer hit, drop shorter.
        hits = sorted(hits, key=lambda h: (len(h["norm"]), h["score"]), reverse=True)
        kept = []
        for h in hits:
            if h["trigger"] in IDENTITY_TRIGGERS and h.get("explicit"):
                kept.append(h)
                continue

            contained = False
            for kh in kept:
                if h["norm"] != kh["norm"] and h["norm"] in kh["norm"]:
                    contained = True
                    break
            if not contained:
                kept.append(h)

        kept.sort(key=lambda h: (h["score"], len(h["norm"])), reverse=True)
        return kept

    def _episode_supplement(self, hit):
        # If a keyword has no episode, try to find an episode keyword that contains it or is contained by it.
        if hit.get("episodes"):
            return hit

        hn = hit["norm"]
        best = None
        for en, ek in self.episode_norm_items[:8000]:
            if not en:
                continue
            if hn in en or en in hn:
                item = self.episodes.get(ek)
                if item and item.get("e"):
                    score = abs(len(en) - len(hn))
                    cand = (score, ek, item)
                    if best is None or cand[0] < best[0]:
                        best = cand
        if best:
            _, ek, item = best
            hit = dict(hit)
            hit["trigger"] = f"{hit['trigger']}→{ek}"
            hit["episodes"] = item.get("e", [])[:self.max_episodes]
            hit["has_episode"] = True
            hit["score"] += 1000
        return hit

    def match(self, user_text: str, recent_context: str = ""):
        nt = normalize(user_text)
        nc = normalize(recent_context)

        explicit_hits = []
        for nk, key in self.norm_items:
            if nk in nt:
                explicit_hits.append(self._make_hit(key, 10000, True))

        explicit_hits = self._prune_contained(explicit_hits)

        # If there are explicit non-identity hits, do not let context dominate.
        if explicit_hits:
            hits = explicit_hits
        else:
            context_hits = []
            for nk, key in self.norm_items:
                if len(nk) >= 4 and nk in nc:
                    context_hits.append(self._make_hit(key, 1200, False))
            hits = self._prune_contained(context_hits)

        # Supplement episode for no-episode hits.
        hits = [self._episode_supplement(h) for h in hits]
        hits.sort(key=lambda h: (h["has_episode"], h["score"], len(h["norm"])), reverse=True)
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
                    # Keep prompt lighter and more direct.
                    lines.append(f"会話窓:\n{w[-700:]}")
                if r:
                    lines.append(f"橋本新っぽい返し:{r[:220]}")
            blocks.append(f"trigger:{h['trigger']}\n" + "\n---\n".join(lines))

        return "\n\n".join(blocks) if blocks else "なし"
