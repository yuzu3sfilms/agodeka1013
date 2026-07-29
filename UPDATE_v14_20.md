# v14.20 Dialogue Continuity

## Purpose
Natural conversation continuity across training, replay, and fallback routes.

## Changes
- Added one central `DialogueManager` with role-labelled user/assistant turns.
- Every response route now updates the same conversation history through `finish()`.
- Added relation detection before domain routing:
  - repair request
  - follow-up
  - continuation request
  - topic shift
  - new utterance
- Training receives recent dialogue and relation metadata.
- Non-training repair/follow-up messages use the previous exchange instead of episode search.
- Short questions are inherited only when there is an explicit reference, an elliptical cue, or topic overlap.
- Unrelated short questions remain new utterances.
- Contextual generation is instructed to admit and correct its own typo, invention, or contradiction rather than fabricate a definition.

## Verification
- 21 tests passed, including all previous routing and training tests.
- Python compilation succeeded.
