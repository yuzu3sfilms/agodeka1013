# AI橋本新 v7 trigger episode engine

## 根本修正

v6.1でも会話が成り立たなかった主因は、キーワード/語録/固有名が出ても、
それに紐づくエピソードを強制発火させる仕組みがなかったこと。

つまり、

```text
牛角
二郎
野猿
ぼくぅ
きゃぴ
フリーポーズ
無理ゲー
玩具
トーマス
アナザーアラクン
```

などが出ても、通常検索の一部に埋もれていた。

## v7で追加したもの

### data/trigger_index.json

900個のtriggerを作成。

各triggerには、

- docfreq
- freq
- 関連する文脈
- 直前発言
- 橋本新の返答例

を入れている。

### data/trigger_keywords.txt

trigger一覧。

### trigger_search

ユーザー発言にtriggerが含まれたら、通常検索スコアに関係なく `trigger_hits` として取得。

### prompt強制

triggerが出た場合、

```text
関連エピソード/語録/過去の返し方を必ず反応に混ぜる
triggerが出ているのに一般返答だけで流さない
```

と明示している。

## ログ

triggerが効いていればRender logsにこう出る。

```text
retrieval triggers=['牛角'] pairs=... messages=... scores=...
generation path: groq
```

複数なら:

```text
retrieval triggers=['二郎', '野猿'] pairs=... messages=...
```

ここが空なら、trigger抽出または一致の問題。

## 重要な変更

### 廃止

- キーワードが通常検索に埋もれる構造
- ローカル引用ガチャ
- 弱い検索結果からのランダム返答
- 「んー」連発

### 維持

- Groq生成
- 全返信保証
- 冷スタートpush fallback
- Render safe
- おうむ返し防止
- ChatGPT臭除去

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_TOKENS=260
TEMPERATURE=1.03
HISTORY_LEN=6
MAX_PAIR_SCAN=3200
MAX_MESSAGE_SCAN=2400
MAX_KEYWORDS=4500
MAX_TRIGGER_HITS=5
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/` フォルダも必須。
