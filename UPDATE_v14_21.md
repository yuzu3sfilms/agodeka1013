# v14.21 Persona Replay Re-ranker

## Purpose
Improve replay selection without adding topic-specific exceptions or replacing the existing evidence gate.

## Changes
- Builds statistics from all 5,546 Hashimoto scenes at startup.
- Adds capped soft bonuses after a scene passes the exact-current-anchor gate:
  - repeated exact reply frequency
  - frequency of broad reply behavior/pattern
  - same conversation partner
  - overlap with recent conversation context
  - same imported LINE group corpus
- Retrieves up to 12 unique replay candidates before final selection.
- Keeps rare, specific episodes eligible; frequency never acts as a hard filter.
- Passes the resolved current speaker into the replay engine.
- Adds detailed reasons such as `same_partner`, `pattern_frequency`, and `conversation_continuity` to replay logs.

## Important limitation
The current dataset is one imported LINE group corpus, so there is no trustworthy per-group comparison yet. v14.21 applies only a small same-corpus prior and does not invent group labels.

## Version
- startup: `version=v14.21`
- health: `v14.21-persona-reranker`
