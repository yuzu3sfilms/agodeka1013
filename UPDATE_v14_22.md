# v14.22 Persona Compiler Foundation

v14.22 begins the migration from a replay-centred bot to a corpus-derived personality architecture.

## Added

- `persona_compiler.py`
  - deterministically compiles the 5,075 usable Hashimoto scenes
  - extracts language distribution, observable situation→action policy, and nearest-speaker relationship policy
  - preserves sample counts and probabilities instead of inventing traits
- `data/persona_policy.json`
  - compiled runtime artifact generated from the bundled LINE corpus
- `persona_policy.py`
  - confidence-aware runtime reader
  - applies only capped soft priors after replay eligibility is established

## Changed

- `ActualReplyEngine` loads the compiled persona policy.
- The old constant `same_corpus_group:+3` bonus was removed because it could not change ranking in a single-group corpus.
- Runtime version is now v14.22.

## Safety of the architecture

Persona statistics never open the replay evidence gate and never replace current conversational evidence. They only break ties among already-grounded candidates. This avoids turning frequent behaviour into a rigid stereotype.
