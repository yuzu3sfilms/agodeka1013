import gzip
import json
from pathlib import Path

from persona_compiler import compile_persona
from persona_policy import PersonaPolicy


def _write_scenes(path: Path):
    rows = [
        {"reply": "どこですか？", "before": ["Reiji Shioda: 今日行く？"]},
        {"reply": "何時ですか？", "before": ["Reiji Shioda: 今日行く？"]},
        {"reply": "無理です", "before": ["村田: これやる？"]},
        {"reply": "はい", "before": ["村田: おい"]},
    ]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_compiler_emits_evidence_backed_policy(tmp_path):
    scene_path = tmp_path / "scenes.jsonl.gz"
    _write_scenes(scene_path)
    result = compile_persona(scene_path)
    assert result["evidence"]["usable_scenes"] == 4
    assert result["global_action_policy"]["question"]["count"] == 2
    assert "Reiji Shioda" in result["relationship_policy"]
    assert result["relationship_policy"]["Reiji Shioda"]["weighted_sample_count"] > 0


def test_runtime_policy_is_soft_and_confidence_aware(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    payload = {
        "global_action_policy": {"short_statement": {"count": 30, "probability": 0.4}},
        "relationship_policy": {
            "Reiji Shioda": {
                "weighted_sample_count": 40,
                "action_policy": {"short_statement": {"count": 20, "probability": 0.5}},
            }
        },
        "runtime": {"confidence_floor": 12, "max_policy_bonus": 14},
    }
    (data / "persona_policy.json").write_text(json.dumps(payload), encoding="utf-8")
    policy = PersonaPolicy(str(data))
    bonus, reasons = policy.action_bonus("short_statement", "Reiji Shioda")
    assert 0 < bonus <= 14
    assert any("persona_relationship_action" in r for r in reasons)
    assert policy.action_bonus("unknown", "Reiji Shioda") == (0, [])
