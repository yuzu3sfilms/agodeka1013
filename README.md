# AI橋本新 v11.2 token slim

## 修正理由

Groqで以下のエラーが出た。

```text
TPD Limit 100000
Used 98018
Requested 2685
rate_limit_exceeded
```

v11.1は、毎回以下を全部Groqに渡していたため重すぎた。

```text
エピソード窓
人物関係プロファイル
口調サンプル
述語展開
直近会話
```

## v11.2の修正

### 1. Groqに渡す情報を圧縮

```text
エピソード窓: 4個 → 2個
会話窓: 前後10行程度 → 前後5行程度
各行: 150字 → 90字
人物関係: 詳細例たくさん → 主要人物・呼称・代表例1つ
口調サンプル: 最大18個 → 6個
直近会話: 4行 → 2行
max_tokens: 140 → 90
```

### 2. 検索能力は維持

以下は維持。

```text
全文検索
述語展開
人間関係プロファイル
質問応答モード
口調サンプル
```

削ったのは「Groqへ渡す文章量」。

### 3. 期待される効果

`Requested 2685` からかなり下がる想定。
Groq無料枠のTPD消費を減らす。

## 推奨環境変数

Render側に入れるなら:

```text
MAX_SEARCH_HITS=4
MAX_EPISODE_WINDOWS=2
EPISODE_WINDOW_BEFORE=2
EPISODE_WINDOW_AFTER=3
MAX_TOKENS=90
MAX_EPISODES_PER_TRIGGER=2
```

## 注意

TPDをすでに使い切っている日は、軽量化してもリセットまでは429が出る。
ただし翌日以降の消費速度は落ちる。
