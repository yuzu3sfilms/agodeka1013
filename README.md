# AI橋本新 v9.1 reaction boost

## 修正理由

v9は「キーワード→エピソード→返答生成」の構造にはなったが、反応が鈍い/悪い可能性が残っていた。

主な原因:
- 短い部分語・汎用triggerが混ざる
- 長いキーワードより部分語が勝つ
- context由来triggerがユーザー発言の明示triggerを邪魔する
- エピソードなしkeywordで即ｷｬﾋﾟｨになりやすい

## v9.1の修正

### 1. 明示trigger優先

ユーザー発言に含まれるtriggerを最優先。
context由来triggerは、明示triggerがない時だけ使う。

### 2. 長いキーワード優先

`シンギュラリティ` のような長い語がある場合、短い部分語を抑える。

### 3. 内包短語を削除

長いhitに含まれる短いhitは基本的に削除。
ただし `顎` などのidentity triggerは明示されていれば残す。

### 4. episode補完

キーワード自体にエピソードがない場合でも、
内包/被内包するepisode付きkeywordを探して補完する。

### 5. エピソード使用を強制

プロンプトで、

```text
エピソード内の単語や出来事を最低1つは反応に混ぜる
```

を追加。

## ログ

成功時:

```text
episode_check hits=['ムタ'] episode_counts=[3]
generation path: groq_episode
```

キーワードあり・エピソード補完あり:

```text
episode_check hits=['ムタソ→ムタ'] episode_counts=[3]
```

キーワードなし:

```text
episode_check hits=[]
generation path: no_keyword_ignore
```

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
