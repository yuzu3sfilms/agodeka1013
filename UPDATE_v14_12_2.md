# v14.12.2 — Training context leak fix

## Fixed

A previous training conversation no longer causes every later question to be treated as a workout follow-up.

Before:
- Previous context was training
- Current text contained `?`
- Current text was classified as `training_followup_question`

This caused ordinary messages such as `ぽつお日本橋？` to receive cable-row advice.

Now:
- The current message must contain an explicit training signal, or
- It must be one of a very small set of genuine context-only follow-ups such as `それで？` or `他の日は？`.

Arbitrary questions no longer inherit training mode.
