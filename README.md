# AI橋本新 v10.1 selective fallback

## 方針

エピソードがヒットしない時の挙動を整理した版。

```text
エピソードあり
→ 過去ログエピソードを元に返答

エピソードなし + 明示的に呼ばれている
→ ｷｬﾋﾟｨ

エピソードなし + 呼ばれていない
→ 無視

Groqエラー/429
→ ｷｬﾋﾟｨ
```

## 呼びかけ判定

以下が発言に含まれると「呼ばれている」とみなす。

```text
顎
アゴ
橋本
橋本新
あらくん
あらた
AGODEKA
LIAR
ARAKUN
```

## ログ

### エピソードあり

```text
dynamic_search terms=[...] hits=... episodes=4 called=False
generation path: groq_dynamic_episode
```

### エピソードなし + 呼びかけあり

```text
dynamic_search terms=[...] hits=0 episodes=0 called=True
generation path: no_episode_called_capyi
reply: ｷｬﾋﾟｨ
```

### エピソードなし + 呼びかけなし

```text
dynamic_search terms=[...] hits=0 episodes=0 called=False
generation path: no_episode_ignore
ignored: no episode
```

## 設計理由

過去ログに根拠がないのに喋ると、橋本新ではなくただのAI即興になる。
ただし、明示的に呼ばれた時だけは最低限の存在感として `ｷｬﾋﾟｨ` を返す。
