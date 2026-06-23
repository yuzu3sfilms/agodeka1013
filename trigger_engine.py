import json
import os
from pathlib import Path

from utils import normalize, angerish


CALL_ONLY = {"橋本", "橋本新", "あらた", "あらくん", "顎", "アゴ", "AGODEKA", "LIAR", "ARAKUN", "Unknown", "unknown"}


class TriggerEngine:
    """
    v8 keyword-only trigger engine.

    - triggers.jsonだけを見る
    - triggerがなければ返信しない
    - triggerがあれば関連例を返す
    - 怒りっぽい例はプロンプトへ渡さない
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.trigger_path = self.data_dir / "triggers.json"
        self.max_hits = int(os.environ.get("MAX_TRIGGER_HITS", "6"))
        self.max_examples = int(os.environ.get("MAX_TRIGGER_EXAMPLES", "5"))

        self.triggers = self._load()
        self.keys = sorted(self.triggers.keys(), key=len, reverse=True)
        self.norm_keys = [(k, self.triggers[k].get("norm") or normalize(k)) for k in self.keys]

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
                strength = 10000 + len(nk) * 10 + int(self.triggers[key].get("docfreq", 0))
            elif len(nk) >= 4 and nk in nc:
                strength = 2000 + len(nk) * 5 + int(self.triggers[key].get("docfreq", 0))
            else:
                continue

            item = self.triggers[key]
            examples = []
            for ex in item.get("examples", []):
                rep = (ex.get("reply") or "").strip()
                if not rep or angerish(rep):
                    continue
                examples.append(ex)
                if len(examples) >= self.max_examples:
                    break

            if not examples:
                continue

            hits.append({
                "trigger": key,
                "strength": strength,
                "docfreq": item.get("docfreq", 0),
                "freq": item.get("freq", 0),
                "call_only": key in CALL_ONLY,
                "examples": examples,
            })

        # If there are content triggers, suppress pure call-name triggers.
        content = [h for h in hits if not h.get("call_only")]
        if content:
            hits = content

        hits.sort(key=lambda h: (h["strength"], h["docfreq"], len(h["trigger"])), reverse=True)
        return hits[:self.max_hits]

    def format_hits(self, hits):
        if not hits:
            return "なし"

        blocks = []
        for h in hits:
            ex_lines = []
            for ex in h.get("examples", []):
                ctx = (ex.get("context") or "").strip()
                lo = (ex.get("last_other") or "").strip()
                rep = (ex.get("reply") or "").strip()

                parts = []
                if ctx:
                    parts.append(f"文脈:{ctx}")
                if lo:
                    parts.append(f"直前:{lo}")
                if rep:
                    parts.append(f"橋本新:{rep}")
                if parts:
                    ex_lines.append("\n".join(parts))

            blocks.append(
                f"## trigger: {h['trigger']} (docfreq={h.get('docfreq',0)})\n"
                + "\n---\n".join(ex_lines)
            )
        return "\n\n".join(blocks)
