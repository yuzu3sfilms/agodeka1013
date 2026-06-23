import json
import os
from pathlib import Path

from utils import normalize, angerish


CALL_ONLY = {"橋本", "橋本新", "あらた", "あらくん", "顎", "アゴ", "AGODEKA", "LIAR", "ARAKUN", "Unknown", "unknown"}


class TriggerEngine:
    """
    v8.2 exhaustive keyword trigger engine.

    - triggers.json compact format
    - triggerがなければ返信しない
    - triggerがあれば関連例をGroqへ渡す
    - 怒りっぽい例は渡さない
    - 例が空でもtrigger自体は発火する
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.trigger_path = self.data_dir / "triggers.json"
        self.max_hits = int(os.environ.get("MAX_TRIGGER_HITS", "6"))
        self.max_examples = int(os.environ.get("MAX_TRIGGER_EXAMPLES", "3"))

        self.triggers = self._load()
        self.keys = sorted(self.triggers.keys(), key=len, reverse=True)
        self.norm_keys = [(k, self.triggers[k].get("n") or normalize(k)) for k in self.keys]

    def _load(self):
        if not self.trigger_path.exists():
            return {}
        return json.loads(self.trigger_path.read_text(encoding="utf-8"))

    def match(self, user_text: str, recent_context: str = ""):
        nt = normalize(user_text)
        nc = normalize(recent_context)
        hits = []

        for key, nk in self.norm_keys:
            if not nk:
                continue

            if nk in nt:
                strength = 10000 + len(nk) * 10 + int(self.triggers[key].get("d", 0))
            elif len(nk) >= 4 and nk in nc:
                strength = 2000 + len(nk) * 5 + int(self.triggers[key].get("d", 0))
            else:
                continue

            item = self.triggers[key]
            examples = []
            for ex in item.get("e", [])[:self.max_examples]:
                rep = (ex.get("r") or "").strip()
                if rep and not angerish(rep):
                    examples.append(ex)

            hits.append({
                "trigger": key,
                "strength": strength,
                "docfreq": item.get("d", 0),
                "freq": item.get("f", 0),
                "call_only": key in CALL_ONLY,
                "examples": examples,
            })

        content = [h for h in hits if not h.get("call_only")]
        if content:
            hits = content

        hits.sort(key=lambda h: (h["strength"], h["docfreq"], len(h["trigger"])), reverse=True)
        return hits[:self.max_hits]

    def _short(self, s: str, n: int):
        s = (s or "").replace("\n", " ").strip()
        return s[-n:] if len(s) > n else s

    def format_hits(self, hits):
        if not hits:
            return "なし"

        blocks = []
        for h in hits:
            ex_lines = []
            for ex in h.get("examples", [])[:self.max_examples]:
                lo = self._short(ex.get("l") or ex.get("c") or "", 80)
                rep = self._short(ex.get("r") or "", 120)
                if rep:
                    if lo:
                        ex_lines.append(f"直前:{lo} / 橋本新:{rep}")
                    else:
                        ex_lines.append(f"橋本新:{rep}")

            if ex_lines:
                blocks.append(f"trigger:{h['trigger']}\n" + "\n".join(ex_lines))
            else:
                blocks.append(f"trigger:{h['trigger']}\n関連例:なし")

        return "\n\n".join(blocks) if blocks else "なし"
