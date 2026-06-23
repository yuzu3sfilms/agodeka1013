# AI橋本新 v5.4 no tone limit

## 目的

v5系で入れていた以下を外した版。

- 感情トーン補正
- 低温化
- キレすぎ抑制
- 文字数制限
- 短文強制
- emotion/functionボーナスによる返答選択の丸め

## 残したもの

- 全返信保証
- Render safe lazy scan
- 冷スタート時のpush fallback
- おうむ返し防止
- ChatGPT風フレーズ除去
- 文脈一致検索
- 過去の文脈→橋本新返答ペア参照

## デフォルト

```text
MAX_TOKENS=240
TEMPERATURE=1.05
HISTORY_LEN=5
MAX_PAIR_SCAN=2200
MAX_MESSAGE_SCAN=2200
MAX_KEYWORDS=3500
```

## 狙い

短く低温なBotではなく、過去ログにあるテンション・長さ・強い表現も自然に出せるようにする。
