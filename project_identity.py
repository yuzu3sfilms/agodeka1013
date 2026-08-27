"""Canonical identity metadata for Project AGO."""

PROJECT_NAME = "Project AGO"
PROJECT_EXPANSION = "Alternative Generated Organism"
PROJECT_VERSION = "v14.37"
PROJECT_INSTANCE = "AGO-HASHIMOTO"
PROJECT_SLUG = "project-ago"


def runtime_label() -> str:
    return f"{PROJECT_NAME} {PROJECT_VERSION} ({PROJECT_INSTANCE})"


def health_payload() -> dict[str, str]:
    return {
        "project": PROJECT_NAME,
        "expansion": PROJECT_EXPANSION,
        "instance": PROJECT_INSTANCE,
        "version": PROJECT_VERSION,
    }
