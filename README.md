# AI橋本新 v6.1 lite generator

## これは何

v6の根本修正版を、GitHubの25MB制限に収まるように作り直した軽量版。

## v6.0で失敗した理由

`data/hashimoto.db` が大きすぎた。

- 展開後: 約119MB
- zip後: 約40.5MB

GitHubの25MB制限を超えた。

## v6.1の方針

DB同梱をやめた。

代わりに、1MB台のJSONLデータを使って、

```text
LINE受信
↓
JSONLから近い過去文脈を検索
↓
Groqに参考例として渡す
↓
Groqが橋本新として生成
↓
LINE返信
```

にした。

## 根本修正ポイント

### 廃止

- ローカル引用ガチャ
- 弱い検索結果からのランダム返答
- `んー` 連発
- 巨大SQLite DB同梱

### 維持

- 過去ログ検索
- Groq生成
- 全返信保証
- 冷スタートpush fallback
- Render safe
- おうむ返し防止
- ChatGPT臭除去

## ログ

正常時:

```text
retrieval pairs=... messages=... scores=...
generation path: groq
reply: ...
LINE reply status: 200
```

Groq制限時:

```text
generation path: emergency_local_cooldown
```

Groqエラー時:

```text
generation path: emergency_local_exception
```

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_TOKENS=220
TEMPERATURE=1.0
HISTORY_LEN=6
MAX_PAIR_SCAN=3200
MAX_MESSAGE_SCAN=2400
MAX_KEYWORDS=4500
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```

## 導入

GitHubを更地にして、このZIPの中身を全部アップロード。
`data/` フォルダも必須。
