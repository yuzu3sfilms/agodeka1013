# AI橋本新 v12 relevance engine

## v12の目的

v11.2までは、

```text
検索する
↓
上位エピソードをそのままGroqへ渡す
```

だった。

v12では間に関連度判定を入れる。

```text
検索する
↓
候補エピソードを多めに取る
↓
relevance.py で採点
↓
関係薄い候補を捨てる
↓
強いエピソードだけGroqへ渡す
```

## 追加ファイル

```text
relevance.py
```

## relevance.py が見るもの

高評価:

```text
固有名詞一致
人物名一致
カタカナ語一致
強い名詞一致
橋本新系発言が近い
質問タイプと会話窓が合っている
```

低評価:

```text
述語だけでヒット
短い語だけでヒット
一般語だけでヒット
質問に答えられなさそう
橋本新系発言がない
```

## 質問タイプ

```text
usage      = 何に使うの？ / 用途
person     = 誰？
place      = どこ？
reason     = なんで？
preference = 好き？嫌い？
action     = 作ってる？行く？やる？
```

## ログ

v12ではこう出る。

```text
dynamic_search terms=[...] predicates=[...]
candidate_hits=...
candidate_episodes=...
selected_episodes=...
relevance_scores=[...]
relevance_labels=[...]
qtypes=[...]
called=...
question=...
```

### 良い例

```text
candidate_episodes=6
selected_episodes=2
relevance_scores=[96, 82]
relevance_labels=['high', 'mid']
generation path: groq_v12_relevant_episode
```

### 悪い候補を全部落とした例

```text
candidate_episodes=5
selected_episodes=0
relevance_scores=[]
relevance_labels=[]
generation path: no_relevant_episode_ignore
```

## 挙動

```text
関連エピソードあり
→ 関連度で選んだエピソード + 人間関係 + 口調サンプルから返答

候補はあるが関連度が低い
→ 無視

エピソードなし + 呼びかけあり
→ ｷｬﾋﾟｨ

エピソードなし + 呼びかけなし
→ 無視

Groqエラー/429
→ ｷｬﾋﾟｨ
```

## 推奨環境変数

```text
MAX_SEARCH_HITS=10
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=2
EPISODE_WINDOW_AFTER=3
MAX_TOKENS=90
```

## v12の狙い

生成能力の改善ではなく、Groqに渡す素材選びの改善。

これで、

```text
関係ない過去ログに飛ぶ
述語だけで変な文脈に飛ぶ
質問に答えられないエピソードを渡す
```

を減らす。
