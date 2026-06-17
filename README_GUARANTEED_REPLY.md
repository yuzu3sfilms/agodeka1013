# AI橋本新 v2.2 guaranteed reply

v2.1 low-tokenで「返事しなくなる」問題が出たため、全返信保証を最優先にした版。

## 変更点

- LINEテキストを受けたら、停止ワード以外は必ず返信
- Groqを呼ぶ前に、過去ログからローカル返答を必ず作る
- Groqが成功したらGroq返答
- Groqが429 / TPD / rate limitならローカル返答
- 429が出たら一定時間Groqを呼ばず、ローカル返答だけにする
- Renderログに `received:`, `reply:`, `LINE reply status:` を出す

## 導入

ZIPの中身をGitHubに丸ごと上書き。`data/` フォルダも必須。

## 環境変数

必須:

- LINE_CHANNEL_SECRET
- LINE_CHANNEL_ACCESS_TOKEN
- GROQ_API_KEY

節約したい場合:

- MAX_TOKENS=60
- TOP_REPLY_PAIRS=2
- TOP_MESSAGES=2
- TOP_STYLE=2
- HISTORY_LEN=3
- RATE_LIMIT_COOLDOWN_SECONDS=900
