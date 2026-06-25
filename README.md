# AI橋本新 v10.2 clean_reply fix

## 修正理由

v10.1で以下のようなログが出た。

```text
received: コテンパン
dynamic_search terms=['コテンパン', ...] hits=6 episodes=4
groq_raw: 自分を変えたかったから、コテンパンにしたかったんじゃない？
generation path: groq_bad_capyi
reply: ｷｬﾋﾟｨ
```

```text
received: ポッさん
dynamic_search terms=['ポッさん', ...] hits=3 episodes=3
groq_raw: 細くてひ弱な自分を変えたかったのによ、ポッさんと名乗られるようになってしまったんだからなぁ
generation path: groq_bad_capyi
reply: ｷｬﾋﾟｨ
```

検索もエピソード取得もGroq生成も成功している。
しかし `clean_reply()` が、ユーザー発言の検索語が返答内に含まれているだけで「丸写し」と誤判定して弾いていた。

## v10.2の変更

### 1. 検索語を返答に含めることを許可

`コテンパン` や `ポッさん` が返答に入っていても弾かない。

### 2. ほぼ丸写しだけ弾く

以下だけ弾く。

```text
user: コテンパン
reply: コテンパン
```

または、長文同士でほぼ同一の場合。

### 3. 期待ログ

```text
received: コテンパン
dynamic_search terms=['コテンパン', ...] hits=6 episodes=4
groq_raw: 自分を変えたかったから、コテンパンにしたかったんじゃない？
generation path: groq_dynamic_episode
reply: 自分を変えたかったから、コテンパンにしたかったんじゃない？
```

## 挙動はv10.1と同じ

```text
エピソードあり
→ 過去ログエピソードを元に返答

エピソードなし + 呼びかけあり
→ ｷｬﾋﾟｨ

エピソードなし + 呼びかけなし
→ 無視

Groqエラー/429
→ ｷｬﾋﾟｨ
```
