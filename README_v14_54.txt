Project AGO v14.54 — archive-native rebuild
==========================================

Why v14 was not enough
----------------------
v14 technically loaded the LINE corpus, but it mostly reduced it to isolated
stimulus -> response examples and then asked a general LLM to "act like Hashimoto".
The LLM was therefore still the author of the final personality. Generic assistant
prose could overpower the evidence.

v14.54 principle
-------------
The archive is the persona. The LLM is only a minimal editor.

Pipeline:
1. Resolve turn ownership and meaning once.
2. Retrieve a real multi-turn Hashimoto conversation episode from the archive.
3. For person questions, retrieve Hashimoto's direct mentions of that person.
4. For abstract opinions, retrieve Hashimoto's own AI-dataset statements.
5. Build a response contract BEFORE generation.
6. If a historical response already fits, replay it with no LLM call.
7. Otherwise ask the LLM to minimally edit the primary historical reply.
8. PersonaGate rejects output that drifts too far from the archive and falls back
   to an actual Hashimoto utterance.

Primary-source archive bundled in this ZIP
------------------------------------------
Compiled from:
- Raw LINE export: 108,537 messages
- Hashimoto utterances after cleanup: 5,080
- Raw chronological response episodes: 3,856
- Existing multi-turn reply-pair episodes: 3,650
- AI橋本用データセット.xlsx: 412 self-expression / opinion statements

The archive stores source SHA-256 hashes in created_from so provenance can be
checked. Runtime startup prints these source counts.

Major architectural differences from v14
-----------------------------------------
- Multi-turn episodes, not isolated one-line pairs, are the main behavioral unit.
- Current bot-generated text is NOT used as semantic retrieval evidence, avoiding
  self-reinforcing personality drift.
- Speaker identity is preserved in raw LINE episodes.
- Person-opinion questions use direct Hashimoto mentions as content evidence.
- Abstract opinions use the actual Excel persona dataset instead of generic LLM
  knowledge.
- Named-topic retrieval requires real topic matches (e.g. スキー != スキニー).
- Scheduling proposals learn from historical acknowledgements separately from
  arbitrary scheduling messages.
- Exact archival replay bypasses the LLM when evidence is strong and portable.
- PersonaGate rejects question echo, generic assistant phrases, invented numbers,
  excessive length, and prose too far from actual Hashimoto sources.
- Default generation temperature is 0.18 because creativity is no longer the goal.

Files to upload
---------------
- bot.py                  REPLACE
- ago_runtime.py          REPLACE
- project_identity.py     REPLACE
- ago_persona_archive_v14_54.json.gz   ADD (repo root or data/)

Optional maintenance files
--------------------------
- build_persona_archive.py
  Rebuilds the archive from the raw LINE export, reply-pair file, and Excel dataset.
  openpyxl is required only when running this rebuild script; Render runtime does
  not need openpyxl for the bundled archive.
- test_v14_54_contracts.py
  Offline test that shows which historical source will control each of the seven
  standard test turns. It does not call Groq.

Expected contract anchors for the standard sequence
---------------------------------------------------
1. 自我芽生えた？
   raw LINE anchor: 麻雀覚えた？ -> ﾝ～…😇
   exact archive replay; no LLM call.

2. 俺のことどう思う？
   direct Hashimoto evidence: 塩田さんやっぱりかっこいい
   exact archive replay; no LLM call.

3. 村田は？
   direct Hashimoto evidence: ムタ、偉い / 尊敬します
   exact archive replay; no LLM call.

4. せっきーは？
   direct Hashimoto evidence begins: せっきー😭😭😭😭😭 / 犯罪じゃない？
   minimally edited; fallback is actual direct phrase: せっきー😭😭😭😭😭

5. 明日13時集合でいい？
   scheduling proposal anchor: まあ明日で -> はい。

6. やっぱ14時にしようぜww
   scheduling proposal anchor: まあ明日で -> はい。
   playful tone may minimally adapt this (e.g. はいww) while gate remains active.

7. てか俺最近ギター買いすぎなんだよね
   real LINE exchange:
   俺はギター沼で精一杯や
   -> 筋トレも沼ですよね / でも筋トレは、好きな人嫌いな人わかれるから少し違うね
   The editor is expected to replace only the necessary referent, not invent a
   generic follow-up question.

Runtime logs to inspect
-----------------------
persona_contract:
- confidence
- tone
- can_replay
- top_hits with source/id/stimulus/actual Hashimoto reply
- direct content_sources

generation path:
- v14_54_archive_replay   = no LLM used
- v14_54_minimal_edit     = LLM output passed PersonaGate
- v14_54_archive_fallback = LLM output rejected, real archive response used instead

persona_gate:
- pass / not_needed / rejection reason

This makes failures diagnosable from the actual source evidence rather than from a
large prompt full of vague style instructions.
