Project AGO v14.47 — clean-core rebuild

REPLACE:
- bot.py
- project_identity.py

ADD:
- ago_runtime.py

DO NOT USE IN THE NEW RESPONSE PATH:
- persona_judge.py
- current_state_engine.py
- actual_reply_engine.py
- relationship_evidence.py
- dynamic_search.py
These files may remain in the repository temporarily, but v14.47 bot.py does not import them.

Design:
1. MeaningResolver resolves intent/target/predicate exactly once.
2. CorpusIndex is the single identity + relationship + style evidence source.
3. Retrieval uses that resolved meaning; no downstream alias/person re-guessing.
4. One model generation. No 4-candidate tournament, no score-based persona judge,
   no replay override, no retry loop rewriting semantics.
5. Narrow ellipsis only: recognized person + immediately preceding person-opinion
   can inherit the opinion predicate. Choice words such as 「どれ？」 never do.
6. Undirected group chatter is silent by default.

Expected diagnostic paths:
- generation path: v14_47_single_pass
- generation path: v14_47_silence
