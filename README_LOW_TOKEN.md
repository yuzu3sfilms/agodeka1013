# AI橋本新 v2.1 low-token

Groq無料枠のTPD節約版。

変更点:
- prompt量を圧縮
- TOP_REPLY_PAIRS/TOP_MESSAGES/TOP_STYLEを減量
- MAX_TOKENS=80
- Groq 429/TPD時はLLMを呼ばず、過去ログから近い返答をローカル返答

環境変数で調整可能:
- TOP_REPLY_PAIRS=2
- TOP_MESSAGES=2
- TOP_STYLE=2
- MAX_TOKENS=60
- HISTORY_LEN=3

さらに節約したい場合はRenderのEnvironmentで:
GROQ_MODEL=llama-3.1-8b-instant
を試す。ただしGroq側でそのモデルが使える場合のみ。
