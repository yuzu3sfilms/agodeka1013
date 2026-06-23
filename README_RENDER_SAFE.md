# AI橋本新 v5.1 render safe

## 修正理由

v5 presence engine は起動時に pairs/messages 全件を読み込み、全件term indexを作ったため、
Render無料枠の512MiBを超えて Out of memory になった。

## v5.1の変更

- 起動時に巨大indexを作らない
- pairs/messagesを全件メモリ展開しない
- 必要時だけJSONLを軽くスキャン
- keywordsも先頭2500件だけ読む
- 再現度のための emotion / response_function / behavior_tags は維持
- 全返信保証も維持

## 調整用環境変数

メモリや速度が厳しければ下げる。

```text
MAX_PAIR_SCAN=1200
MAX_MESSAGE_SCAN=1200
MAX_KEYWORDS=1800
```

余裕があれば上げる。

```text
MAX_PAIR_SCAN=2500
MAX_MESSAGE_SCAN=2500
MAX_KEYWORDS=4000
```

まずはデフォルトでOK。

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```
