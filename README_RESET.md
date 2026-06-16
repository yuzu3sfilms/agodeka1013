# AI橋本新 v2 fresh rebuild

## 理念
このLINEグループにかつていた橋本 新（はしもと あらた）を、過去ログとExcelデータから可能な限り忠実に模倣するAIアカウント。

## GitHubを更地にする
古いファイルは全削除してCommit。

## 入れるファイル
- app.py
- config.py
- bot_core.py
- data_store.py
- anti_echo.py
- memory.py
- text_utils.py
- HASHIMOTO_ARATA_IDENTITY_PROMPT.txt
- requirements.txt
- Procfile
- data/ ディレクトリ一式

## data/ の中身
- hashimoto_arata_messages.jsonl
- hashimoto_arata_reply_pairs.jsonl
- hashimoto_arata_style_examples.txt
- hashimoto_arata_keywords.txt
- dataset_report.json

## Render環境変数
- LINE_CHANNEL_SECRET
- LINE_CHANNEL_ACCESS_TOKEN
- GROQ_API_KEY

## データ抽出結果
LINEログ108,537発言から、橋本新として扱う名義の発言5,083件、直前文脈→本人返答ペア5,083件、Excel由来の発言412件を抽出。
