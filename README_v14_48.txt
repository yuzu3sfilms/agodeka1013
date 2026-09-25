Project AGO v14.48 — Person Model Layer

Replace:
- bot.py
- ago_runtime.py
- project_identity.py

Core path:
LINE -> one semantic resolution -> canonical person -> PersonModel -> query-ranked raw evidence -> one generation.

PersonModel is built automatically at startup from the existing LINE corpus. It stores aliases, interaction volume, direct-mention volume, recurring-topic hints, representative direct exchanges, direct mentions, and evidence strength. It does NOT hard-code likes/dislikes.

Important fix: group chatter that AGO correctly ignores is still retained in conversation history. Silence no longer destroys context for the next follow-up.
