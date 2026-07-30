from pathlib import Path

from project_identity import (
    PROJECT_EXPANSION,
    PROJECT_INSTANCE,
    PROJECT_NAME,
    PROJECT_VERSION,
    health_payload,
)


def test_project_identity_is_canonical():
    assert PROJECT_NAME == "Project AGO"
    assert PROJECT_EXPANSION == "Alternative Generated Organism"
    assert PROJECT_INSTANCE == "AGO-HASHIMOTO"
    assert PROJECT_VERSION == "v14.24"


def test_health_payload_uses_canonical_identity():
    payload = health_payload()
    assert payload["project"] == PROJECT_NAME
    assert payload["expansion"] == PROJECT_EXPANSION
    assert payload["instance"] == PROJECT_INSTANCE
    assert payload["version"] == PROJECT_VERSION


def test_legacy_bot_class_name_remains_compatible():
    source = Path("bot.py").read_text(encoding="utf-8")
    assert "class AgoHashimotoBot:" in source
    assert "HashimotoArataBot = AgoHashimotoBot" in source
