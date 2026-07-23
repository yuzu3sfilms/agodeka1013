# v14.12.1 shared shutdown state fix

## 原因
`shutdown_state` が各Pythonプロセス内の辞書だけに保存されていた。
Gunicorn/Renderで別ワーカーが次のLINEイベントを処理すると、停止状態を引き継げず、最初のwakeメッセージが通常ルートで無視される可能性があった。

## 変更
- shutdown状態をSQLiteへ保存し、ワーカー間で共有
- `set_shutdown()` / `is_shutdown()` は必ず共有ストアを参照
- wake成功時は共有ストアを即時解除し、同じメッセージを通常処理へ継続
- 起動語だけなら同じイベントへの返信として「あはい」
- Procfileを1 worker + 4 threadsへ固定し、LINE会話状態の分散をさらに防止

## 期待ログ
停止時:
```
shutdown_state_set: <chat_id> True store=sqlite
```
最初の起動メッセージ時:
```
shutdown_state_get: <chat_id> True store=sqlite
shutdown_state: True wake_check: True reason=wake_term
shutdown_state_set: <chat_id> False store=sqlite
shutdown_state: False wake_consumed_first_message: False
generation path: wake_v14_11_short_ack
```

複合メッセージ時（例: あらくん、胸トレ教えて）は `wake_v14_11_short_ack` でreturnせず、その同じ文がtraining routeへ進む。
