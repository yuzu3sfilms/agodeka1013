# Project AGO

**Alternative Generated Organism**  
Current implementation: **AGO-HASHIMOTO v14.24**

Project AGO reconstructs a conversational identity from real interaction data as an executable cognitive system. It does not present itself as the original person; AGO-HASHIMOTO is an alternative, data-derived conversational model.

## Current architecture

```text
LINE input
  ↓
Speaker Resolution / Dialogue State
  ↓
Reply Policy
  ↓
Persona Policy + Relationship Context
  ↓
Canon / Episodic Replay / Knowledge Fallback
  ↓
Persona Judge + Style Guard
  ↓
LINE reply
```

The long-term direction is **human simulation before language generation**: estimate situation, relationship, motivation, memory and action policy first, then express the selected action naturally.

## v14.24

- Project identity changed to **Project AGO**
- Official expansion fixed as **Alternative Generated Organism**
- First personality instance named **AGO-HASHIMOTO**
- Runtime and health-check version labels centralized in `project_identity.py`
- Old `HashimotoArataBot` import retained as a compatibility alias
- Existing v14.23 unified behavior policy preserved

## Main components

| Component | Role |
|---|---|
| `bot.py` | Main conversation orchestration |
| `dialogue_manager.py` | Short-term dialogue continuity |
| `current_state_engine.py` | Current-message and context interpretation |
| `reply_policy.py` | Reply/silence and route selection |
| `actual_reply_engine.py` | Evidence-first replay of real utterances |
| `persona_compiler.py` | Compiles observed behavior into persona policy |
| `persona_policy.py` | Applies behavior and relationship priors |
| `behavior_taxonomy.py` | Shared behavioral classification |
| `persona_judge.py` | Persona consistency evaluation |
| `relationship.py` | Relationship-specific context |
| `training_*` / `ai_training_advisor.py` | Training consultation subsystem |

## Data

`data/` contains the compressed conversation corpus, scene index and compiled profiles used at runtime. Do not remove these files unless the relevant loader and deployment process are also changed.

The generated persona policy can be rebuilt with:

```bash
python persona_compiler.py
```

## Local verification

```bash
pip install -r requirements.txt
python -m pytest -q
```

## Deployment

Required environment variables include:

```text
GROQ_API_KEY
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
```

The deployment entry point remains defined in `Procfile`; changing the project name does not require changing the LINE webhook URL or Render configuration.

## Identity and scope

- **Framework:** Project AGO
- **Meaning:** Alternative Generated Organism
- **Current instance:** AGO-HASHIMOTO
- **Version:** v14.24

AGO-HASHIMOTO is a computational reconstruction based on available records. It is not the original person and should not be represented as such.
