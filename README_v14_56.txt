Project AGO v14.56 — Participation Model

Upload every file in this patch to the existing repository root. Do not remove
ago_persona_archive_v14_55.json.gz: v14.56 intentionally reuses it unchanged.
Existing app.py, requirements.txt, Procfile, shutdown_state.py, speaker_resolver.py,
webhook_event_store.py remain unchanged. No new dependencies.

Flow: shutdown -> ParticipationModel -> semantic resolver -> existing v14.55
contract/generation. A silent turn is logged in history but ends semantic ownership.
Direct calls and same-speaker immediate continuations can reply; explicit other
addressees, ambiguous group questions and closing acknowledgements are suppressed.
Continuation expires after 180 seconds; semantic state expires after 30 minutes.
Spontaneous participation is only eligible with recent group context from multiple
speakers, a topic signal, no ambiguous question, and a cooldown. Rate estimates
are smoothed from actual LINE speaker transitions, scaled down for conservative
behavior and capped at 8% per eligible turn while recently active or 2.5% otherwise.
At least 10 minutes between spontaneous replies. AGO_SPONTANEOUS=0 disables them.

Training: 99,734 parsed messages; 36,164 training opportunities, 2,075 observed
next-turn AGO messages (5.74%); 7,821 held-out opportunities, 173 observed (2.21%).
Training opportunity = final turn of a non-AGO speaker followed by a distinct
speaker within 5 minutes, excluding explicit AGO calls. This is not a read receipt
or proof of the original person's intentional response. Topic categories, timeout,
probability scaling and cooldowns are design choices, not learned preferences.
The held-out sample is descriptive, not a validated predictive accuracy estimate.

Rebuild: python build_participation.py "path/to/LINE-export.txt"
Test: python test_v14_56_participation.py
Existing test_v14_55_contracts.py passed. Offline participation tests passed,
including bot.reply with a mock generation function. Groq/LINE live test not run.
No change to persona archive or generation quality logic.
