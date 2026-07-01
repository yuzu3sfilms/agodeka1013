# AI橋本新 v12 relevance engine

## v12の目的

v11.2までは、

```text
検索する
↓
上位エピソードをそのままGroqへ渡す
```

だった。

v12では間に関連度判定を入れる。

```text
検索する
↓
候補エピソードを多めに取る
↓
relevance.py で採点
↓
関係薄い候補を捨てる
↓
強いエピソードだけGroqへ渡す
```

## 追加ファイル

```text
relevance.py
```

## relevance.py が見るもの

高評価:

```text
固有名詞一致
人物名一致
カタカナ語一致
強い名詞一致
橋本新系発言が近い
質問タイプと会話窓が合っている
```

低評価:

```text
述語だけでヒット
短い語だけでヒット
一般語だけでヒット
質問に答えられなさそう
橋本新系発言がない
```

## 質問タイプ

```text
usage      = 何に使うの？ / 用途
person     = 誰？
place      = どこ？
reason     = なんで？
preference = 好き？嫌い？
action     = 作ってる？行く？やる？
```

## ログ

v12ではこう出る。

```text
dynamic_search terms=[...] predicates=[...]
candidate_hits=...
candidate_episodes=...
selected_episodes=...
relevance_scores=[...]
relevance_labels=[...]
qtypes=[...]
called=...
question=...
```

### 良い例

```text
candidate_episodes=6
selected_episodes=2
relevance_scores=[96, 82]
relevance_labels=['high', 'mid']
generation path: groq_v12_relevant_episode
```

### 悪い候補を全部落とした例

```text
candidate_episodes=5
selected_episodes=0
relevance_scores=[]
relevance_labels=[]
generation path: no_relevant_episode_ignore
```

## 挙動

```text
関連エピソードあり
→ 関連度で選んだエピソード + 人間関係 + 口調サンプルから返答

候補はあるが関連度が低い
→ 無視

エピソードなし + 呼びかけあり
→ ｷｬﾋﾟｨ

エピソードなし + 呼びかけなし
→ 無視

Groqエラー/429
→ ｷｬﾋﾟｨ
```

## 推奨環境変数

```text
MAX_SEARCH_HITS=10
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=2
EPISODE_WINDOW_AFTER=3
MAX_TOKENS=90
```

## v12の狙い

生成能力の改善ではなく、Groqに渡す素材選びの改善。

これで、

```text
関係ない過去ログに飛ぶ
述語だけで変な文脈に飛ぶ
質問に答えられないエピソードを渡す
```

を減らす。


---

# v12.1 style guard

## 目的

v12で検索関連度は改善したが、生成後の口調がまだ崩れることがあった。

主な問題:

```text
「〜ぜ」
「〜ないよ」
「〜よな」
「私」
説明口調
AIっぽい丁寧な返答
自分をあらくんとして認識しない
```

v12.1では `style_guard.py` を追加し、Groqの返答をそのまま返さず、最終チェックしてからLINEへ返す。

## 追加ファイル

```text
style_guard.py
```

## 処理

```text
Groq生成
↓
de_ai_tone
↓
clean_reply
↓
style_guard
↓
LINE返信
```

## 禁止されるもの

```text
私 / わたし / 俺 / おれ
AIとして / 私はAI / 橋本新では / 本人では
〜ぜ / 〜だぜ
〜ないよ / 〜だよ / 〜よな / 〜だよな / 〜だよね / 〜なんだよね
です / ます / ですね / ください / と思います
```

## 方針

橋本っぽさを語尾で作らない。

```text
説明しすぎない
一人称を出さない
短く返す
雑に返す
主語を抜く
```

## ログ

style guardが発動するとこう出る。

```text
style_guard: {'changed': True, 'reason': ['first_person_removed', 'bad_ending_replaced']}
generation path: groq_v12_1_style_guard
```

AI自己説明などが出た場合は安全に落とす。

```text
style_guard: {'changed': True, 'reason': ['ai_disclaimer']}
reply: ｷｬﾋﾟｨ
```

## 推奨環境変数

v12と同じ。

```text
MAX_SEARCH_HITS=10
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=2
EPISODE_WINDOW_AFTER=3
MAX_TOKENS=90
```


---

# v12.2 continuity / canon fix

## 目的

v12.1で口調ガードを入れたが、次の問題が残った。

```text
会話の途中で突然反応しなくなる
過去ログのエピソードに準拠しない
過去ログと矛盾するような一般論を返す
```

v12.2ではこの2点を修正する。

```text
1. continuity fix
   会話中に selected_episodes=0 になっても、直前に会話していた場合は短文継続返答に回す。

2. canon lock
   過去ログエピソードを「参考材料」ではなく「設定・記憶・関係性の根拠」として扱う。
```

## 呼びかけ語の修正

`LIAR` と `AI` では反応しない。

呼びかけ扱い:

```text
顎
アゴ
橋本
橋本新
あらくん
あらた
AGODEKA
```

## continuity fix

v12.1ではこうだった。

```text
selected_episodes=0
↓
no_relevant_episode_ignore
↓
無視
```

v12.2では、直前に会話していた場合はこうなる。

```text
selected_episodes=0
↓
conversation continuing
↓
fallback_prompt
↓
短文で返す
```

ログ:

```text
generation path: groq_v12_2_continuity_fallback
```

## canon lock

system promptを変更。

```text
過去ログエピソードは単なる参考材料ではなく、この人物の設定・記憶・関係性の根拠。
返答は過去ログエピソードに矛盾してはいけない。
エピソードに根拠がある時は、その事実・関係・ノリを優先する。
一般論で埋めない。
エピソードにないことを勝手に断定しない。
```

## 関連エピソードがある時

```text
generation path: groq_v12_2_relevant_episode
```

この時は、過去ログを設定として使う。

## 関連エピソードがないが会話継続中

```text
generation path: groq_v12_2_continuity_fallback
```

この時は新設定を作らず、短い反応だけ。

## 推奨環境変数

```text
MAX_SEARCH_HITS=10
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=2
EPISODE_WINDOW_AFTER=3
MAX_TOKENS=90

CONTINUITY_SECONDS=420
CONTINUITY_MIN_HISTORY=1
CONTINUITY_REPLY_PROBABILITY=0.75
```

## 方針

```text
喋らなすぎない
でもAIやLIARでは反応しない
過去ログにあるエピソードは設定として扱う
設定にないことは勝手に作らない
```
