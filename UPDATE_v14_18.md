# v14.18 — Generalized Japanese routing and retrieval

This release replaces example-specific patches with shared utterance analysis.

## Architectural changes

- Added `japanese_analysis.py` as the single source of content-term analysis.
- Separated explicit episode continuation from ordinary/generic questions.
- Added `hypothetical_question` as a conversation act.
- Generic questions and conditional questions no longer imply `episode_expand`.
- `current_state_engine.py` and `dynamic_search.py` now share the same content analysis.
- Mixed Japanese words are preserved instead of being split into hiragana tails and kanji fragments.

## Routing behavior

- Explicit continuation cues such as `続き`, `その後`, and `もっと詳しく` use episode expansion.
- Conditional questions use `scene_then_fallback` and may still retrieve a relevant scene.
- Existing Scene Replay behavior for strong scene matches is preserved.

## Verification

- 10 routing and regression tests passed.
- All Python files compile.
- ZIP integrity verified.
