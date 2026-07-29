# v14.23 Unified Behavior Policy

## Purpose
Make the offline Persona Compiler and runtime replay engine use one shared
behaviour taxonomy. v14.22 compiled labels such as `question` while runtime
requested labels such as `question_general`, causing some policy evidence to be
silently ignored.

## Changes
- Added `behavior_taxonomy.py` as the single source of truth for reply actions
  and stimulus classes.
- Persona Compiler schema upgraded to version 2.
- Runtime policy now combines three evidence-backed layers:
  - global action policy
  - situation-conditioned action policy
  - relationship-conditioned action policy
- Situation policy is still a soft reranking prior. It cannot open replay
  eligibility or invent an episode.
- Regenerated `data/persona_policy.json` from 5,075 usable scenes.
- Removed caches, compiled bytecode and superseded update notes from the
  release archive.

## Compatibility
Existing replay evidence gates, dialogue continuity, training advisor and
webhook handling remain intact.
