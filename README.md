# AI橋本新 v9 keyword episode engine

## 何を直したか

今回の設計はこれ。

```text
キーワードを拾う
↓
過去LINEログからそのキーワード周辺のエピソードを探す
↓
そのエピソードをGroqに渡す
↓
エピソードに基づいて返事する
```

v8までは「trigger→短い返答例」寄りだった。
v9では「trigger→過去ログ会話窓」に変えた。

## データ

### data/episodes.json

キーワードごとに、実際のLINEログ周辺の会話窓を保存。

形式:

```text
keyword
  └ episodes
      ├ 会話窓
      └ 橋本新系アカウントの返答
```

### data/episode_keywords.txt

エピソードが見つかったキーワード一覧。

### data/all_keywords.txt

検出用の全キーワード一覧。
エピソードがないキーワードも含む。

## 件数

```text
元LINEログ: 108,530発言
キーワード総数: 9,901
エピソード付きキーワード: 7,897
```

## ログ

成功時:

```text
episode_check hits=['ムタ'] episode_counts=[4]
generation path: groq_episode
reply: ...
```

キーワードはあるがエピソードなし:

```text
episode_check hits=['ボンジョヴィ'] episode_counts=[0]
generation path: keyword_no_episode_capyi
reply: ｷｬﾋﾟｨ
```

キーワードなし:

```text
episode_check hits=[]
generation path: no_keyword_ignore
ignored: no keyword
```

Groqエラー/429:

```text
generation path: groq_429_capyi
reply: ｷｬﾋﾟｨ
```

## 怒りの切り離し

エピソード抽出時に、怒り・罵倒っぽい行は材料から外している。
人格として怒りを再現しない。

## ファイル構成

```text
app.py
bot.py
episode_engine.py
utils.py
persona.md
requirements.txt
Procfile
data/
  episodes.json
  episode_keywords.txt
  all_keywords.txt
```

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_EPISODE_HITS=4
MAX_EPISODES_PER_TRIGGER=3
MAX_TOKENS=140
TEMPERATURE=0.95
HISTORY_LEN=4
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/episodes.json` が本体。
