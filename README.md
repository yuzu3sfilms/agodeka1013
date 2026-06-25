# AI橋本新 v10 dynamic search engine

## 設計

ユーザーの言う本来あるべきプロセスに合わせた版。

```text
発言を受ける
↓
その発言の中から検索語をその場で抽出
↓
過去LINEログ全文に検索をかける
↓
ヒットした発言と周辺エピソードを取得
↓
そのエピソードを元にGroqが返答
```

## 重要

v10では、事前に「反応するキーワード表」を本体として使わない。
`all_keywords.txt` や `trigger_keywords.txt` のような固定リスト方式をやめた。

## データ

```text
data/line_corpus.jsonl.gz
```

元LINEログ108,530発言をgzip圧縮した全文コーパス。

## ログ

```text
dynamic_search terms=[...] hits=... episodes=...
```

例:

```text
dynamic_search terms=['顎シンギュラリティ', 'シンギュラリティ', '顎', ...] hits=12 episodes=4
generation path: groq_dynamic_episode
```

### 見方

```text
terms=[]
```

→ 発言から検索語抽出できていない。

```text
hits=0
```

→ 検索語はあるが過去ログにヒットしていない。

```text
episodes=0
```

→ ヒットはあるが会話窓が作れていない。

```text
episodes>0
```

→ エピソードは拾えている。返答が悪ければGroqプロンプト側の問題。

## エラー時

Groq 429 / 例外 / 生成失敗時:

```text
ｷｬﾋﾟｨ
```

## 怒りの切り離し

エピソード窓を作る時に、怒り・罵倒っぽい行は材料から外す。

## ファイル構成

```text
app.py
bot.py
dynamic_search.py
utils.py
persona.md
requirements.txt
Procfile
data/
  line_corpus.jsonl.gz
  speakers.json
```

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_SEARCH_HITS=6
MAX_EPISODE_WINDOWS=4
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MIN_SEARCH_SCORE=35
MAX_TOKENS=160
TEMPERATURE=0.95
HISTORY_LEN=4
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/line_corpus.jsonl.gz` が本体。
