# AI橋本新 v8.2 exhaustive keywords + ｷｬﾋﾟｨ fallback

## 修正内容

### 1. キーワード網羅を大幅拡張

v8/v8.1の3000 triggerでは足りなかったため、元LINEログ・Excel・既存triggerから再抽出し直した。

対象:
- 元LINEログ 108,530発言
- Excelデータ
- 既存trigger
- 既存triggerの関連例
- speaker名/固有名詞

trigger数:

```text
10000
```

### 2. 固有名詞も広く投入

抽出対象:
- 人名/表示名
- カタカナ語
- 英数字語
- 漢字語
- 混合語
- 語録断片
- 話題語
- speaker名

### 3. 手動重要語は必ず含めた

例:

```text
橋本新
橋本
あらた
あらくん
顎
AGODEKA
LIAR
ARAKUN
Unknown
牛角
二郎
野猿
ボンジョヴィ
Bon Jovi
BON JOVI
きゃぴ
きゃぴい
ｷｬﾋﾟｨ
ぼくぅ
かわいいでしょ
フリーポーズ
無理ゲー
玩具
ｷﾞｬｵ
トーマス
アナザーアラクン
ムタ
ムタソ
どいくん
塩田
```

### 4. エラー時fallback

Groq 429 / Groq例外 / 生成失敗時は、固定でこれを返す。

```text
ｷｬﾋﾟｨ
```

ログ:

```text
generation path: groq_429_capyi
reply: ｷｬﾋﾟｨ
```

### 5. キーワードなしは無視

```text
trigger_check hits=[]
generation path: no_trigger_ignore
ignored: no trigger
```

### 6. ファイルサイズ

`data/triggers.json` は約12.8MB。
GitHubの25MB単体ファイル制限内。

ZIPは約数MB台。

## ファイル構成

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

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```

## 任意環境変数

```text
MAX_TRIGGER_HITS=6
MAX_TRIGGER_EXAMPLES=3
MAX_TOKENS=120
TEMPERATURE=0.95
HISTORY_LEN=4
RATE_LIMIT_COOLDOWN_SECONDS=900
DEBUG_LOG=1
```
