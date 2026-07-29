import gzip
import json
from pathlib import Path

from behavior_taxonomy import classify_reply, classify_stimulus
from persona_compiler import compile_persona
from persona_policy import PersonaPolicy


def test_shared_taxonomy_uses_runtime_action_names():
    assert classify_reply("どこですか？") == "question_specific"
    assert classify_reply("笑") == "reaction_laugh"
    assert classify_reply("やめた方がいい") == "negative_advice"
    assert classify_stimulus("今日どこ行く？") == "question"


def test_compiler_and_runtime_share_action_keys(tmp_path: Path):
    scenes = tmp_path / "scenes.jsonl.gz"
    rows = [
        {"before": ["Reiji Shioda: どこ行く？"], "reply": "どこですか？"},
        {"before": ["Reiji Shioda: 何する？"], "reply": "どこですか？"},
        {"before": ["Reiji Shioda: いつ行く？"], "reply": "どこですか？"},
    ]
    with gzip.open(scenes, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    profile = compile_persona(scenes)
    assert "question_specific" in profile["global_action_policy"]
    assert "question_specific" in profile["situation_policy"]["question"]["actions"]


def test_situation_policy_contributes_bonus(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    payload = {
        "runtime": {"confidence_floor": 6, "max_policy_bonus": 14},
        "global_action_policy": {},
        "situation_policy": {
            "question": {
                "sample_count": 20,
                "actions": {"question_specific": {"count": 10, "probability": 0.5}},
            }
        },
        "relationship_policy": {},
    }
    (data / "persona_policy.json").write_text(json.dumps(payload), encoding="utf-8")
    policy = PersonaPolicy(str(data))
    bonus, reasons = policy.action_bonus("question_specific", situation="question")
    assert bonus > 0
    assert any("persona_situation_action" in reason for reason in reasons)
