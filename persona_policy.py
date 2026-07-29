"""Runtime reader for corpus-derived persona policy."""
from __future__ import annotations

import json
from pathlib import Path


class PersonaPolicy:
    def __init__(self, data_dir: str = "data"):
        self.path = Path(data_dir) / "persona_policy.json"
        self.profile = {}
        if self.path.exists():
            try:
                self.profile = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.profile = {}

    @property
    def loaded(self) -> bool:
        return bool(self.profile)

    def action_bonus(self, action: str, current_speaker: str | None = None) -> tuple[int, list[str]]:
        """Return a capped, confidence-aware behavioural prior.

        This never makes a scene eligible. It only breaks ties after the replay
        evidence gate, preventing a statistical stereotype from replacing an
        observed episode.
        """
        if not self.loaded or not action:
            return 0, []
        runtime = self.profile.get("runtime", {})
        floor = int(runtime.get("confidence_floor", 12))
        cap = int(runtime.get("max_policy_bonus", 14))
        bonus = 0
        reasons = []

        global_item = self.profile.get("global_action_policy", {}).get(action, {})
        if int(global_item.get("count", 0)) >= floor:
            b = min(5, round(float(global_item.get("probability", 0)) * 10))
            bonus += b
            if b:
                reasons.append(f"persona_global_action:{action}:+{b}")

        rel = self.profile.get("relationship_policy", {}).get(current_speaker or "", {})
        rel_item = rel.get("action_policy", {}).get(action, {})
        if int(rel.get("weighted_sample_count", 0)) >= floor and int(rel_item.get("count", 0)) >= 3:
            b = min(9, round(float(rel_item.get("probability", 0)) * 12))
            bonus += b
            if b:
                reasons.append(f"persona_relationship_action:{current_speaker}:{action}:+{b}")

        return min(cap, bonus), reasons
