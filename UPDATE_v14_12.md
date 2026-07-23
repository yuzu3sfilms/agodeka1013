# AI_HASHIMOTO_ARATA v14.12 更新内容

## 変更理由
従来はWebhookからchat_idだけをbotへ渡しており、発言者のLINE userIdを捨てていた。そのため、相手ごとの呼称を選べなかった。

## 変更点
- `app.py`
  - LINEの`userId`を取得。
  - グループ・ルーム・1対1に応じたプロフィールAPIから表示名を取得。
  - 表示名をメモリキャッシュ。
  - `bot.reply()`へsender情報を渡す。
- `speaker_resolver.py`（新規）
  - userId固定マップを最優先。
  - 次にLINE表示名と過去ログ人物名・aliasを照合。
  - 一意に特定できない場合はunresolvedとして返す。
- `data/speaker_profiles.json`（新規）
  - 初期人物プロファイルと呼称候補。
  - `line_user_map`へ実際のuserIdを登録可能。
- `bot.py`
  - 返信ごとに話者を解決。
  - 通常Groq生成・continuity fallback・筋トレAdvisorへ相手情報を渡す。
  - 「あなた」「君」を避け、名前は自然に必要な場合だけ使うよう指示。

## 期待ログ
```text
sender: Uxxxxxxxx Reiji Shioda
speaker_resolution: {'canonical': 'Reiji Shioda', 'display': 'Reiji Shioda', 'address': '塩田', 'confidence': 0.96, 'source': 'display_name_exact'}
```

未知の相手:
```text
speaker_resolution: {'canonical': '', 'display': 'unknown name', 'address': '', 'confidence': 0.0, 'source': 'unresolved'}
```

## 副作用・制限
- LINE表示名が過去ログ名と大きく異なる場合は自動認識しない。
- 誤認防止のため、曖昧な部分一致は一意に決まる場合だけ採用。
- 最も確実なのは`data/speaker_profiles.json`の`line_user_map`へuserIdを登録する方法。
- Replayそのものは過去の実発言を優先するため、呼称を機械的に書き換えない。
