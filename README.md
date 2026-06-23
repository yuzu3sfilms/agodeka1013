# AI橋本新 v5 presence engine

## 目的

これは単なるLINE Botではなく、かつてLINEグループにいた橋本 新（はしもと あらた）が抜けた穴を、過去ログとExcel由来データからできる限り自然に埋めるAIアカウント。

v4からさらに、感情だけでなく「反応機能」まで再現するようにした。

## v5の強化点

### 1. presence_profile.json

本人の存在感をデータ化。

- 返答ペア数
- 発言数
- 返答長
- 感情分布
- 反応機能分布
- ふるまいタグ分布

### 2. response_function

各返答に以下のような機能ラベルを付与。

- plain_reply
- ask_back
- difficulty
- appeal
- positive
- high_reaction
- tease
- correction

これにより、単語が似ている返答ではなく、
「この場面では橋本新は質問返しするのか、弱るのか、普通に返すのか」を選びやすくした。

### 3. behavior_tags

各返答に以下のようなタグを追加。

- very_short
- short
- medium
- question
- period
- ellipsis
- exclamation
- deferential
- difficulty
- crying_marker
- laugh
- signature_high

### 4. 感情トーン

v4の emotion を維持しつつ、response_function と合わせて検索スコアに入れた。

### 5. 全返信保証

Groq制限時はローカル返答。
ローカル返答も、文脈・感情・反応機能に近い過去返答を優先する。

## ファイル構成

```text
app.py
bot.py
store.py
utils.py
profile.txt
requirements.txt
Procfile
README.md
build_report.json
data/
  pairs.jsonl
  messages.jsonl
  keywords.txt
  style_profile.json
  emotion_profile.json
  presence_profile.json
  source_dataset_report.json
```

## Render環境変数

必須:

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

任意:

```text
GROQ_MODEL=llama-3.3-70b-versatile
MAX_TOKENS=80
HISTORY_LEN=4
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/` フォルダも必須。
