# Project AGO v14.65 — 統合型人格生成エンジン（実験版）

## 導入
既存 GitHub リポジトリのルートへ ZIP 内のファイルを配置する。既存 app.py / requirements.txt / Procfile / webhook_event_store.py / shutdown_state.py / speaker_resolver.py および data/ はそのまま維持。新規アプリ一式ではなく既存 v14.56 向けの交換パッチ。旧 archive は新しい bot.py では使用しない（削除は必須ではない）。旧テスト test_v14_56_participation.py は旧内部契約を前提としているので、新しい bot のテストに使用しない。旧バージョンへのロールバックは Git のコミット単位で行う。

必須パッチファイル: bot.py, persona_engine.py, ago_persona_v14_65.json, participation.py, ago_participation_v14_65.json, ago_runtime.py, project_identity.py。すべて同梱。既存の OpenAI Python SDK と GROQ_API_KEY / GROQ_MODEL を使う。GROQ_MODEL の既定値は openai/gpt-oss-20b。JSON mode / reasoning_effort の本番互換性は未検証。API タイムアウト 12 秒、自動再試行なし。旧 GROQ_MAX_COMPLETION_TOKENS は引き継がず AGO_COMPLETION_TOKENS (既定1024) を使用。

## 設計
- 49の原文出典付き発言（一次分析対象の表示名のみ）と9仮説を利用。仮説には条件、支持事例、境界・反例がある。引用の文脈は観測データであり本人の現在の事実ではない。H07（グループ内ネタ）と模倣候補 L102008 を人格根拠から除外。未確定アカウントやExcelを本人の直接証拠として使わない。
- 最長60発言、24時間以内の会話をプロンプトへ。会話中に黙った発言も記録し、AGO生成文は区別する。インメモリのため再起動や複数workerをまたぐ永続性なし。
- 一回の LLM 呼び出しで応答対象ID、行動、参照証拠ID、本文をJSONで取得。旧RAG、固定返答、最小編集、旧MeaningResolver、固定文字数目標はbotの生成経路から外した。失敗時は返答せずログに理由を出す。明示的呼びかけの場合、応答するなら最新IDも必須。
- 検査はJSON構造、対象ID、根拠ID、空応答等に限定。意味や出典の使用が正しいこと、本人らしさは保証しない。IDはモデルの申告。
- 参加集計は一次分析対象に限定し、帰属未確定の発言を含む遷移を除外。学習34,865場面（次話者本人849）、後年7,815場面（173）。旧手動話題ゲートは外したが、宛先・短文・自然な終了・直近会話・クールダウン・確率上限は引き続き保守的なルール。既読・真の返信意思や実運用での頻度は未検証。自発参加を無効にするには AGO_SPONTANEOUS=0。
- 本人の実在の身元・現在の状態を偽らないAIシミュレーション。過去発言の引用を現在の本人の発言としてコピーしないよう指示する。

## 検証
`python test_v14_65.py` で12件のオフラインテスト。OpenAI SDK がない環境ではimportスタブを用い、APIはすべてFake。bot初期化、旧ログの発言文脈保持、他人宛・明示呼びかけ、遅い応答対象、履歴分離・期限・上限、API異常・不正出力、停止、話題ゲートなしの自発参加を検査。実際のLLM出力の品質、旧版との比較、本番app.pyとの完全な互換性、Render起動は未検証。

## データとプライバシー
ZIPには私的な過去会話の抜粋と分析注釈が入る。公開リポジトリへはアップロードしないこと。実行時は最新会話と人格根拠がGroqに送信される。原文全体・Excel原本・旧人格アーカイブは同梱していない。研究資料は `research/`、再構築用コマンドは同フォルダの README を参照。外部への実API送信は今回行っていない。
