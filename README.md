# AI橋本新 v8 keyword-only clean

## 目的

これまでの設計を根本的に畳み直した版。

v8は「全発言に返すBot」ではない。
橋本新関連のキーワード・語録・固有名・エピソード話題が出た時だけ反応する。

## 重要な方針

### 1. キーワードがない発言には反応しない

通常会話に無理に入らない。

ログ:

```text
trigger_check hits=[]
generation path: no_trigger_ignore
ignored: no trigger
```

この場合は仕様通り無視。

### 2. キーワードは網羅重視

元LINEログ、Excel、既存処理済みデータから再抽出し、
3000個のtriggerを作成。

```text
data/triggers.json
data/trigger_keywords.txt
```

### 3. 怒りの感情は切り離し

怒り・罵倒・攻撃的な返答例は、プロンプトへ渡す候補から除外。
trigger自体は拾えるが、怒り人格としては再現しない。

### 4. ファイル構成を最小化

中核はこれだけ。

```text
app.py
bot.py
trigger_engine.py
utils.py
persona.md
requirements.txt
Procfile
data/
  triggers.json
  trigger_keywords.txt
```

## 代表trigger

```text
牛角
二郎
野猿
きゃぴ
きゃぴい
ぼくぅ
かわいいでしょ
フリーポーズ
無理ゲー
玩具
ｷﾞｬｵ
トーマス
アナザーアラクン
橋本新名言集
顎
AGODEKA
ラーメン
焼肉
カラオケ
筋肉
スクワット
ゴールドジム
プロテイン
小杉湯
銭湯
ムタ
中山
富澤
貴文
土居
どいくん
塩田
```

## ログ確認

キーワードに反応した場合:

```text
trigger_check hits=['牛角']
generation path: groq_trigger
reply: ...
LINE reply status: 200
```

キーワードなし:

```text
trigger_check hits=[]
generation path: no_trigger_ignore
ignored: no trigger
```

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_TRIGGER_HITS=6
MAX_TRIGGER_EXAMPLES=5
MAX_TOKENS=260
TEMPERATURE=1.02
HISTORY_LEN=6
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/` フォルダも必須。
