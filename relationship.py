import json
from pathlib import Path


class RelationshipProfile:
    def __init__(self, data_dir: str = "data"):
        path = Path(data_dir) / "relationship_profile.json"
        if path.exists():
            self.profile = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.profile = {}

    def format(self, max_examples: int = 4):
        p = self.profile
        if not p:
            return "なし"

        lines = []

        top = p.get("top_speakers", [])[:8]
        if top:
            lines.append("主要発言者:")
            lines.append(", ".join(f"{name}({count})" for name, count in top))

        persona = p.get("persona_speakers", [])
        if persona:
            lines.append("橋本新系として扱う発言者:")
            lines.append(", ".join(f"{name}({count})" for name, count in persona))

        mentions = p.get("top_name_mentions", [])[:20]
        if mentions:
            lines.append("よく出る人物・呼称:")
            lines.append(", ".join(f"{name}({count})" for name, count in mentions))

        interactions = p.get("persona_interaction_by_previous_speaker", [])[:6]
        if interactions:
            lines.append("橋本新系アカウントがよく反応していた相手:")
            for item in interactions:
                lines.append(
                    f"- {item['speaker']}: 直後返信{item['persona_replied_after_count']}回"
                )
                for ex in item.get("examples", [])[:max_examples]:
                    prev = ex.get("prev", "")
                    rep = ex.get("persona", "")
                    if prev and rep:
                        lines.append(f"  例: {item['speaker']}: {prev} / 橋本新: {rep}")

        return "\n".join(lines)

    def style_samples(self, n=16):
        samples = self.profile.get("style_samples", [])
        return samples[:n]
