# Project AGO v14.66 — Groq TPM対策

## 導入
既存 v14.65 の修正パッチ。ZIPのファイルをすべて既存GitHubリポジトリのルートに配置する。app.py / requirements.txt / Procfile / webhook_event_store.py / shutdown_state.py / speaker_resolver.py / data/ は維持する。削除必須ファイルなし。人格・参加データのスキーマは変更せず、v14_65というファイル名を維持する。必要な実行データも同梱。追加パッケージ、APIキー変更不要。非公開リポジトリに限る。

## 障害の原因
v14.65では9仮説と49件の原文根拠を毎回送信し、Groq上の8000 TPMを単一要求で超過（実ログ9448〜9539）。

## 修正
- 9仮説・49証拠はローカル保持。短い仮説要約と、現在の会話末尾4発言の文字bigram重複による候補選択を使う。最大3件の根拠を送信、支持・限定の区別を保持し、反例も予算の範囲で候補に入れる。語彙一致は意味理解や人格の正しさを保証しない。短い仮説要約は既存研究からの手動圧縮。
- 直近の発言優先、余裕があれば過去の発言も追加。最大60発言/24時間を記憶し、送信量は別途制限。最新発言が極端に長い場合は中略明示で冒頭と末尾を保存。履歴全体の完全送信は保証しない。
- UTF-8バイト数 + メッセージ枠の余裕288 + max_completion_tokensをローカル推定値とする。正式なモデルtokenizerではない。通常は過大見積もりになるが、サービス側の厳密な計数や共有利用分を保証しない。
- プロセス内の全チャット共通で60秒の送信予算を管理。送信前に予約、成功時にusageがあればprompt_tokens + completion上限と余裕256を基に更新。usageなし、失敗時は予約維持。共有アカウント、複数worker、再起動、Groq独自のレート計算までは追跡できない。
- 足りなければ送信予算を縮小し、最低限の入力も収まらない場合は無送信でログにlocal_budget_exhaustedを記録。Webhook内で長時間待たない。413/429時は再試行せず10秒/60秒のローカルbackoff。定型返答は復活させない。
- モデルの申告する証拠IDは今回実際に提示したものに限定。

## 設定 (既存環境変数を変える必要なし)
- AGO_TPM_LIMIT: 既定8000、上限8000。400を差し引いてローカル予算にする。
- AGO_REQUEST_TOKENS: 既定4200、1800〜7400に制限。出力枠込みの保守的推定値。
- AGO_COMPLETION_TOKENS: 既定768、256〜1024に制限。gpt-ossの推論も含む。
既存設定にAGO_COMPLETION_TOKENSがあればその値を範囲内で使用する。

## 確認
`python -m unittest test_v14_66 -v` (旧版テストは旧契約のため対象外)。すべてのAPI応答は模擬。Groq実API、Render上での起動、人格再現品質は未検証。
ログ: generation budget (estimate_upper_proxy, request_cap, available_before, completion, history_count, hypotheses, evidence_count)、generation usage (実APIが返した値)、generation path: v14_66_integrated / v14_66_local_budget_exhausted / v14_66_api_error 等。
