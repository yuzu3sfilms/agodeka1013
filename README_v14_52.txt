Project AGO v14.52

Purpose
- Fix the remaining generic-LLM response behavior without adding canned answers.
- Keep the clean single-pass architecture introduced in v14.47+.

Root fixes in v14.52
1. Stimulus shape is now separate from topic semantics.
   Example: 「自我芽生えた？」 and historical 「麻雀覚えた？」 are both
   yesno_past_question, so the historical response form can guide cadence without
   pretending the topics are semantically identical.

2. Removed the v14.51 retrieval bias where every question received a similarity
   bonus and same-partner evidence got +18. Partner identity is now only a small
   tie-breaker; structural match and real lexical overlap dominate.

3. Conversation mode now represents AGO's own reply behavior.
   A user question no longer changes AGO to questioning mode merely because it
   ends with 「？」. User input may only nudge clearly social modes such as playful
   or practical; AGO's own previous reply is the main persistent-mode signal.

4. Duplicate LINE exports such as foo.txt / foo(1).txt are deduplicated at load
   time by keeping the largest copy, preventing persona/response frequencies from
   being silently double-counted.

5. Prompt priority is now explicit:
   facts/target -> historical stimulus-response form -> persistent AGO style.
   The model is told not to paraphrase the user's question, add caveats, or turn
   weird/self-referential banter into an AI/philosophy explanation.

6. Default temperature lowered from 0.72 to 0.58 for better evidence fidelity.

Validated against the actual LINE corpus available during development:
- only one canonical duplicate export loaded
- 自我芽生えた？ => stimulus_shape yesno_past_question
- top behavioral anchor: 麻雀覚えた？ -> ﾝ～…😇
- a user question leaves AGO interaction_mode ordinary
- scheduling/playful cues can still nudge practical/playful modes
- Python syntax checks passed
