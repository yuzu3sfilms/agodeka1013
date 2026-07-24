# v14.15 — First-message and intent-first routing

- The first substantive message after shutdown is no longer consumed as a wake signal. It wakes the bot and continues through normal processing unchanged.
- Explicit stop messages remain silent and keep shutdown enabled.
- Each chat now records whether the current utterance is its first message in the running session; first messages are always considered for a response instead of being rejected for missing history.
- Training routing now separates conversational purpose from domain words.
- Generic body parts (`胸`, `肩`, `腹`, `尻`, etc.) no longer trigger training mode by themselves.
- A body part enters training mode only with a training request/log cue. Strong exercise names still count as direct training evidence.
