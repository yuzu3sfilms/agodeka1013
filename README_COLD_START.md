# AI橋本新 v5.3 cold-start push fallback

## 目的

時間が空いた後の1通目だけ無視される問題への対策。

Render Freeは15分アイドルでスピンダウンし、次のリクエストで再起動する。
LINEのreplyTokenはWebhook受信後1分以内に使う必要がある。
そのため、冷スタート中にreplyTokenが失効し、1通目だけ返信できないことがある。

## 対策

通常:
- reply APIで返信

reply APIが失敗した場合:
- groupId / roomId / userId に push API で追撃送信

## ログ

正常:
- LINE reply status: 200

replyToken失効など:
- LINE reply error: 400 ...
- trying push fallback
- LINE push status: 200

## 注意

Push APIを使うため、LINE Developersでpush messageが使えるプラン/設定である必要がある。
