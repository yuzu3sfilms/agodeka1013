Project AGO v14.51

Core:
conversation ownership
 -> one semantic resolution + stimulus classification
 -> person relationship evidence
 -> corpus-learned stimulus-response behavior evidence
 -> persistent conversation mode
 -> global Hashimoto persona evidence
 -> one grounded generation

New in v14.51:
- Learns only real non-Hashimoto -> immediately-following Hashimoto response pairs.
- Separates behavioral analogy from factual/person evidence.
- Stimulus classes: thanks, apology, offer_gift, joke_laughter, scheduling, surprise, complaint, opinion_request, question, greeting, short_reaction, statement.
- Partner-matched historical reactions receive retrieval priority.
- Response examples cannot override semantic target or invent facts.

Upload: bot.py, ago_runtime.py, project_identity.py
