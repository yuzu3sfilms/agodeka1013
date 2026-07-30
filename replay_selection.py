from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ReplayScore:
    semantic: float = 0.0
    topic: float = 0.0
    conversation_state: float = 0.0
    relationship: float = 0.0
    persona: float = 0.0
    episode: float = 0.0

    def total(self) -> float:
        weights = {
            "semantic": 0.22,
            "topic": 0.20,
            "conversation_state": 0.22,
            "relationship": 0.08,
            "persona": 0.13,
            "episode": 0.15,
        }
        values = asdict(self)
        return sum(max(0.0, min(1.0, values[k])) * w for k, w in weights.items())


def should_use_replay(score: ReplayScore, threshold: float = 0.78) -> bool:
    """Replay wins only when both context and overall evidence are credible."""
    return (
        score.total() >= threshold
        and score.conversation_state >= 0.65
        and max(score.topic, score.episode) >= 0.60
    )
