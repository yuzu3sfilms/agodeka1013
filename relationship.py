import json
from pathlib import Path


class RelationshipProfile:
    def __init__(self, data_dir: str = "data"):
        path = Path(data_dir) / "relationship_profile.json"
        if path.exists():
            self.profile = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.profile = {}

    def format(self, max_examples: int = 1):
        """
        v11.2: compact relationship profile.
        以前は全部盛りでTPD消費が大きかったため、主要情報だけ渡す。
        """
        p = self.profile
        if not p:
            return "なし"

        lines = []

        top = p.get("top_speakers", [])[:6]
        if top:
            lines.append("主要:" + ", ".join(f"{name}" for name, count in top))

        persona = p.get("persona_speakers", [])[:4]
        if persona:
            lines.append("橋本新系:" + ", ".join(f"{name}" for name, count in persona))

        mentions = p.get("top_name_mentions", [])[:12]
        if mentions:
            lines.append("呼称:" + ", ".join(f"{name}" for name, count in mentions))

        interactions = p.get("persona_interaction_by_previous_speaker", [])[:4]
        if interactions:
            xs = []
            for item in interactions:
                xs.append(f"{item['speaker']}({item['persona_replied_after_count']})")
            lines.append("よく返す相手:" + ", ".join(xs))

            # Only one compact example total.
            for item in interactions:
                exs = item.get("examples", [])
                if exs:
                    ex = exs[0]
                    prev = (ex.get("prev") or "")[:45]
                    rep = (ex.get("persona") or "")[:45]
                    if prev and rep:
                        lines.append(f"例:{item['speaker']}:{prev} / 橋本新:{rep}")
                        break

        return "\n".join(lines)

    def style_samples(self, n=6):
        samples = self.profile.get("style_samples", [])
        return samples[:n]
