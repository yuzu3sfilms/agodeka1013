"""Runtime reader for corpus-derived layered persona policy."""
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

    @staticmethod
    def _item_bonus(item: dict, floor: int, scale: int, cap: int) -> int:
        if int(item.get("count", 0)) < floor:
            return 0
        return min(cap, round(float(item.get("probability", 0)) * scale))

    def action_bonus(
        self,
        action: str,
        current_speaker: str | None = None,
        situation: str | None = None,
    ) -> tuple[int, list[str]]:
        """Return confidence-aware global, situational and relationship priors.

        The policy is only applied after replay eligibility. It cannot create a
        candidate, invent a memory, or override the current-turn evidence gate.
        """
        if not self.loaded or not action:
            return 0, []

        runtime = self.profile.get("runtime", {})
        floor = int(runtime.get("confidence_floor", 12))
        cap = int(runtime.get("max_policy_bonus", 14))
        bonus = 0
        reasons: list[str] = []

        global_item = self.profile.get("global_action_policy", {}).get(action, {})
        b = self._item_bonus(global_item, floor, scale=10, cap=5)
        if b:
            bonus += b
            reasons.append(f"persona_global_action:{action}:+{b}")

        situation_node = self.profile.get("situation_policy", {}).get(situation or "", {})
        if int(situation_node.get("sample_count", 0)) >= floor:
            situation_item = situation_node.get("actions", {}).get(action, {})
            b = self._item_bonus(situation_item, max(3, floor // 3), scale=12, cap=7)
            if b:
                bonus += b
                reasons.append(f"persona_situation_action:{situation}:{action}:+{b}")

        rel = self.profile.get("relationship_policy", {}).get(current_speaker or "", {})
        rel_item = rel.get("action_policy", {}).get(action, {})
        if int(rel.get("weighted_sample_count", 0)) >= floor:
            b = self._item_bonus(rel_item, 3, scale=12, cap=9)
            if b:
                bonus += b
                reasons.append(f"persona_relationship_action:{current_speaker}:{action}:+{b}")

        return min(cap, bonus), reasons
