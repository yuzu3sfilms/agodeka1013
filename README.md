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


---

# v12.3 episode recall fix

## 原因

Renderログでこうなっていた。

```text
candidate_hits=10
candidate_episodes=6
selected_episodes=0
generation path: no_relevant_episode_ignore
```

これは検索失敗ではない。

```text
検索はヒットしている
↓
候補エピソードも作れている
↓
relevance.py が全部落としている
```

つまり、v12の関連度判定が厳しすぎて、欲しいエピソードまで殺していた。

## v12.3の修正

### 1. 固有トピック強制保持

`ペヤング` のようなカタカナ語・商品名・固有語がユーザー発言にあり、その語がエピソード窓に出ている場合、低スコアでも落とさない。

```text
exact_topic
force_keep_topic
```

ログ例:

```text
relevance_labels=['topic']
force_kept=True
relevance_reasons=[['exact_topic:ペヤング', 'force_keep_topic']]
```

### 2. 関連度しきい値を緩和

```text
min_keep_score: 55 → 45
strong_score: 85 → 80
```

### 3. エピソード窓を広げた

```text
EPISODE_WINDOW_BEFORE: 2 → 4
EPISODE_WINDOW_AFTER: 3 → 6
formatted window: 480 chars → 900 chars
persona lines: 4 → 8
```

これで、キーワード発言とあらくんの反応が少し離れていても同じエピソードとして入る。

### 4. ログ強化

```text
relevance_reasons=...
force_kept=...
top_rejected=...
```

これで「候補はあるのに何で落ちたか」が見える。

### 5. エピソード再生を強化

プロンプトに追加。

```text
ヒットしたエピソードの名詞・出来事・関係性・言い回しを返答に反映する。
エピソードにある話題を無視して、一般的な返答に逃げない。
過去ログのエピソードを再生するように、短く反応。
```

## 推奨環境変数

```text
MAX_SEARCH_HITS=10
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MAX_TOKENS=90

CONTINUITY_SECONDS=420
CONTINUITY_MIN_HISTORY=1
CONTINUITY_REPLY_PROBABILITY=0.75
```

## v12.3の狙い

```text
検索で拾えたエピソードをrelevanceで殺さない
ペヤング/牛角/二郎/ニッパーのような固有話題を必ず再生候補に残す
過去ログを設定として反応に使う
```


---

# v12.4 topic search fix

## 問題

Renderログでこうなっていた。

```text
received: 今日はペヤング何個食べるの？
terms=['今日はペヤング何個食べるの', 'ペヤング', '何個食', '今日']
candidate_hits=10
top_rejected=[{'matched': ['今日']} ...]
selected_episodes=0
```

これは最悪で、検索が「ペヤング」ではなく「今日」で埋まっていた。

つまり、

```text
ペヤング = 本題
今日 = ノイズ
```

なのに、ノイズで検索していた。

## v12.4の修正

### 1. topic-first search

検索語を分ける。

```text
topic_terms  = 本題語
generic_terms = ノイズ寄り語
predicates = 述語
```

例:

```text
今日はペヤング何個食べるの？
```

はこうなる。

```text
topic_terms=['ペヤング']
generic_terms=['今日はペヤング何個食べるの', '何個食', '今日']
predicates=['何個食べる', '何個食べ', ...]
```

### 2. topic termがある時はtopicだけで先に検索

```text
topic_termsがある
↓
topic_termsだけで検索
↓
1件でも出たらgeneric_termsは使わない
```

これで「今日」や「何個」でヒット欄が埋まらない。

### 3. topicが0件の時だけfallback

```text
topic_termsで0件
↓
topic_miss_fallback_general
↓
generic/predicateも使う
```

### 4. ログ強化

v12.4からこう出る。

```text
topic_terms=['ペヤング']
generic_terms=['今日はペヤング何個食べるの', '何個食', '今日']
search_mode=topic_first
```

これで検索の主役が何か分かる。

## ローカル検証

```text
query: 今日はペヤング何個食べるの？
topic_terms=['ペヤング']
search_mode=topic_first
candidate_hits=5
candidate_episodes=5
selected_episodes=2
relevance_scores=[144, 122]
```

拾えたエピソード例:

```text
ペヤング25個食べてる途中なんでしょ
ペヤング50個食べれそう
```

## 推奨環境変数

```text
MAX_SEARCH_HITS=12
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MIN_SEARCH_SCORE=35
MAX_TOKENS=90

CONTINUITY_SECONDS=420
CONTINUITY_MIN_HISTORY=1
CONTINUITY_REPLY_PROBABILITY=0.75
```

## 方針

```text
本題語を外さない
ノイズ語で候補を埋めない
エピソード検索はまずtopic-first
topicが拾えたらgenericは使わない
```


---

# v12.5 canon answer fix

## 問題

v12.4で検索は直った。

```text
topic_terms=['ペヤング']
search_mode=topic_first
selected_episodes=2
```

しかしGroqが勝手に文を作っていた。

```text
ペヤング25個食べる予定だ
ペヤング25個食べるつもりだ
ペヤング25個食べたことあるから、25個以上は無理
25個食べました
```

これは、過去ログに答えがあるのにLLMに考えさせているのが原因。

## v12.5の修正

`canon_answer.py` を追加。

```text
過去ログから確定答えが取れる
↓
Groqを呼ばない
↓
過去ログ由来の短い答えを直接返す
```

## 対象

まずは数値質問。

```text
何個？
何人？
何枚？
何回？
何本？
何杯？
いくつ？
```

## ペヤング例

入力:

```text
今日はペヤング何個食べるの？
```

検索されたエピソード:

```text
坂口: ペヤング25個食べてる途中なんでしょ
```

v12.5の返答:

```text
25個の途中
```

## ログ

成功時:

```text
canon_answer: {'used': True, 'type': 'count', ...}
generation path: canon_v12_5_answer
```

この時はGroqを呼ばない。

スキップ時:

```text
canon_answer_skip: {'used': False, 'reason': 'not_count_question'}
```

その場合は従来通りGroqへ。

## 狙い

```text
予定/つもり/食べました みたいな勝手な時制改変を止める
過去ログに答えがある質問は、設定から直接答える
LLMに考えさせる部分を減らす
```

## 推奨環境変数

v12.4と同じ。

```text
MAX_SEARCH_HITS=12
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MIN_SEARCH_SCORE=35
MAX_TOKENS=90
```


---

# v13 global persona judge

## 目的

v12.xは小手先修正が増えていた。

```text
検索がズレる → topic-first
語尾がズレる → style_guard
確定答えを捏造する → canon_answer
途中で黙る → continuity fallback
```

これは必要だったが、根本的にはまだ

```text
LLMに1個返答させる
↓
後処理で直す
```

という構造だった。

v13では構造を変える。

```text
全発言から人格プロファイルを作る
↓
候補返答を複数作る
↓
persona_judge.py が全候補を採点
↓
橋本全発言から見て乖離が少ないものだけ返す
```

## 追加ファイル

```text
persona_judge.py
data/hashimoto_persona_profile.json
data/topic_canon_profile.json
```

## hashimoto_persona_profile.json

橋本発言 5546件から作成。

主な統計:

```text
中央値: 10文字
8文字以下: 約40%
4文字以下: 約17%
一人称「私」: 7回
一人称「俺」: 5回
一人称「僕/ぼく」: 197回
```

これにより、長く綺麗に説明する返答を減点する。

## topic_canon_profile.json

話題ごとの設定・エピソード・本人発言を抽出。

例:

```text
ペヤング:
  - ペヤング25個食べてる途中なんでしょ
  - ペヤング50個食べれそう
```

## persona_judge.py

候補返答を採点する。

見るもの:

```text
全体人格との一致
文の長さ
禁止語尾
一人称
説明臭さ
過去ログエピソードとの矛盾
topic canonとの一致
数値設定との一致
勝手な時制改変
```

## 生成フロー

確定答えが取れる場合:

```text
search
↓
canon_answer
↓
Groqを呼ばず直接返答
```

それ以外:

```text
search
↓
Groqが候補1〜4を生成
↓
style_guard
↓
persona_judge
↓
最良候補だけ返す
```

## ログ

候補生成時:

```text
persona_candidates: [...]
persona_judge: {'chosen': ..., 'scored': [...]}
generation path: groq_v13_judged_episode
```

全候補が悪い時:

```text
generation path: persona_judge_reject_capyi
```

## ペヤング検証

候補:

```text
ペヤング25個食べる予定だ
25個の途中
坂口が言った通り、25個かな
25個食べました
```

persona_judgeは `予定` / `食べました` を時制改変として減点し、`25個の途中` を選ぶ。

## 推奨環境変数

```text
MAX_SEARCH_HITS=12
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MIN_SEARCH_SCORE=35
MAX_TOKENS=160

CONTINUITY_SECONDS=420
CONTINUITY_MIN_HISTORY=1
CONTINUITY_REPLY_PROBABILITY=0.75
```

## v13の狙い

```text
小手先修正から脱却する
LLMの一発回答を信用しない
橋本全発言から見て乖離が少ない返答だけ採用する
過去ログを設定として扱う
```
