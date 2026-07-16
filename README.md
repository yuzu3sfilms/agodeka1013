# AI_HASHIMOTO_ARATA v14.3 current-state policy

## 目的

v14.3は、v14.2の clean conversation scene replay engine に、**現在のLINE会話状態を読む層** と **返答ルートを決める層** を追加した版です。

v14.2まで:

```text
過去ログ側のscene化はできた
ただし、現在の会話をどう読むかはまだ弱かった
```

v14.3:

```text
現在の会話状態を読む
↓
返すべきか決める
↓
canon / scene replay / Groq fallback の順番を選ぶ
```

## 合言葉

```text
生成するな、再演しろ
ただし、今の場面を読んでから再演しろ
```

## 追加ファイル

```text
current_state_engine.py
reply_policy.py
```

## current_state_engine.py

現在のLINE発言を以下のように分類します。

```text
stop
canon_question
question
direct_call
topic_ping
reaction_ping
short_chat
statement
```

見るもの:

```text
直接呼ばれているか
質問か
何個/何回などの確定質問か
短い単語反応か
直前話題を継承すべきか
会話に関連sceneがあるか
```

ログ例:

```text
current_state: {
  'intent': 'topic_ping',
  'preferred_route': 'scene_replay',
  'topic_terms': ['ペヤング'],
  'should_consider_reply': True
}
```

## reply_policy.py

current_stateをもとに、返答ルートを決めます。

```text
silence
canon
scene_replay
canon_then_scene
scene_then_fallback
```

例:

```text
何個食べれるの？
→ canon → scene_replay → fallback

ペヤング
→ scene_replay → canon → fallback

普通の無関連文
→ silence
```

ログ例:

```text
reply_policy: {
  'reply': True,
  'routes': ['scene_replay', 'canon', 'fallback'],
  'reason': 'intent:topic_ping|preferred:scene_replay'
}
```

## runtime flow

```text
1. dynamic_search
2. current_state_engine
3. reply_policy
4. canon_answer
5. conversation scene replay
6. Groq fallback + persona_judge
```

## data構成

```text
data/line_corpus.jsonl.gz
data/conversation_scenes.jsonl.gz
data/conversation_scene_stats.json
data/hashimoto_persona_profile.json
data/topic_canon_profile.json
data/relationship_profile.json
data/speakers.json
```

scene統計:

```text
messages: 108530
scenes: 5546
reply_length_median: 10.0
short_rate: 0.5905156869816084
```

## 起動ログ

```text
bot_init: version=v14.3 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True
```

## 主なgeneration path

```text
generation path: policy_silence
generation path: canon_v14_3_policy_answer
generation path: replay_v14_3_policy_scene_reply
generation path: groq_v14_3_policy_fallback_episode
generation path: groq_v14_3_policy_fallback_continuity
```

## v14.3の狙い

```text
全発言に雑に返さない
返すべき場面と黙る場面を分ける
canon/replay/fallbackの順番を場面ごとに変える
直前話題の継承をcurrent_state側でも扱う
過去scene再演を、今の会話状態に合わせて使う
```

## 推奨環境変数

```text
MAX_SEARCH_HITS=12
MAX_EPISODE_WINDOWS=6
EPISODE_WINDOW_BEFORE=4
EPISODE_WINDOW_AFTER=6
MIN_SEARCH_SCORE=35

REPLAY_MAX_SCENES=5546
REPLAY_MIN_SCORE=80

MAX_TOKENS=160
CONTINUITY_SECONDS=420
CONTINUITY_MIN_HISTORY=1
CONTINUITY_REPLY_PROBABILITY=0.75
```


---

# v14.4 scene-ranker / attention fix

## 修正した問題

### 1. ヒットしているのにエピソードを広げない

ログでは、`なつかしい？` に対して候補に

```text
グランド土塚なつかしいわあ
これをグランド土塚と呼び、崇めたてまつります。
ソウルモード...
```

まで出ていた。

しかし実際には、短く完全一致する

```text
グランド土塚…。
```

が選ばれていた。

原因:

```text
ひらがな語「なつかしい」をtokenとして十分拾えていない
短い完全一致の実発話を強く見すぎている
追撃質問・回想質問でエピソードを広げるモードがない
```

## v14.4の修正

### actual_reply_engine.py

以下を追加。

```text
ひらがなtoken抽出
user_phrase_in_reply
nostalgia_reply_match
episode_expand_medium_reply
too_bare_for_nostalgia
too_bare_for_expand
```

これにより、

```text
なつかしい？
```

に対して、

```text
グランド土塚なつかしいわあ
```

が上位に来る。

ローカル確認:

```text
ANS: グランド土塚なつかしいわあ
reasons:
  user_phrase_in_reply:なつかしい
  nostalgia_reply_match
```

### current_state_engine.py

以下のcueを追加。

```text
NOSTALGIA_CUES = なつかしい / 懐かしい
EXPAND_CUES = それ何 / どんな / 話 / エピソード / 由来 / 覚えてる
```

これらは

```text
intent: episode_expand
preferred_route: episode_expand
```

になる。

### attention-only発言の扱い

`ねえ` / `ちょっと` / `おい` などは、前話題を自動継承しない。

理由:

```text
ねえ
ちょっと
```

だけで毎回 `グランド土塚` を継承すると、同じ返答を繰り返すため。

ログ上は以下になる想定。

```text
current_state:
  intent: attention_ping
  preferred_route: fallback_only
  topic_terms: []
  inherited_topic: False
```

## 期待する変化

### Before

```text
グランド土塚
→ グランド土塚…。

なつかしい？
→ グランド土塚…。

ねえ
→ グランド土塚…。

ちょっと
→ グランド土塚…。
```

### After

```text
グランド土塚
→ グランド土塚…。

なつかしい？
→ グランド土塚なつかしいわあ

ねえ
→ 前話題を継承しない

ちょっと
→ 前話題を継承しない
```

## 起動ログ

```text
bot_init: version=v14.4 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True
```

## 主なgeneration path

```text
generation path: canon_v14_4_policy_answer
generation path: replay_v14_4_ranked_scene_reply
generation path: groq_v14_4_policy_fallback_episode
generation path: groq_v14_4_policy_fallback_continuity
```


---

# v14.5 general query-intent ranker

## 修正方針

v14.4では `なつかしい？` に対しては改善したが、まだ個別語対応の匂いがあった。

v14.5では、個別単語ではなく **query intent** として general に処理する。

## 追加ファイル

```text
query_intent.py
```

## query_intent.py

ユーザーの追撃発言をカテゴリ化する。

```text
memory_recall
meaning_explain
existence_check
count_question
time_question
place_question
person_question
yesno_check
attention_only
generic_question
short_ping
```

これにより、

```text
なつかしい？
覚えてる？
それ何？
どんな話？
由来は？
ある？
誰？
どこ？
いつ？
```

を、単なる文字列ではなく「質問意図」として扱う。

## actual_reply_engine.py のgeneral化

v14.4:

```text
なつかしい → nostalgia_reply_match
```

v14.5:

```text
query_intent → replay ranking
```

主なranker理由:

```text
intent_expand_substantive_reply
intent_memory_reply_match
intent_explain_reply_match
intent_exact_answer_like
intent_expand_penalize_bare_echo
intent_memory_penalize_bare_echo
intent_explain_penalize_bare_echo
```

つまり、短い完全一致だけを選ばず、ユーザーの追撃意図に合う実発話を上げる。

## local test

```text
なつかしい？
→ グランド土塚なつかしいわあ

それ何？
→ これをグランド土塚と呼び、崇めたてまつります。

由来は？
→ これをグランド土塚と呼び、崇めたてまつります。

覚えてる？
→ グランド土塚なつかしいわあ
```

## 起動ログ

```text
bot_init: version=v14.5 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True
```

## generation path

```text
generation path: replay_v14_5_intent_ranked_scene_reply
generation path: canon_v14_5_policy_answer
generation path: groq_v14_5_policy_fallback_episode
generation path: groq_v14_5_policy_fallback_continuity
```

## 狙い

```text
個別語の応急処置から脱却
追撃質問を意図カテゴリで処理
短文完全一致への過剰吸着を抑える
エピソード展開・回想・説明・確認に汎用対応する
```


---

# v14.6 training advisor

## 目的

v14.6では、AIあらくんに **筋トレ相談機能** を追加しました。

通常の内輪ネタ・人格再演は v14.5 のまま維持しつつ、筋トレ相談だけ専用ルートで処理します。

## 追加ファイル

```text
training_intent.py
training_safety.py
training_memory.py
training_advisor.py
```

## 処理順

v14.6では、筋トレ相談を最上流で判定します。

```text
user message
↓
training_advisor
↓
筋トレ相談ならここで返答
↓
違うなら v14.5 の current_state / scene replay / Groq fallback
```

理由:

```text
今日胸
ベンチ何セット？
筋肉痛あるけど脚やっていい？
減量したい
```

のような実用相談を、過去ログの内輪ネタ検索に流さないため。

## training_intent.py

以下を分類します。

```text
program_request
log_workout
pain_or_injury
nutrition_cut
hypertrophy
form_advice
general_training
```

部位も拾います。

```text
chest
back
legs
shoulders
arms
core
```

## training_safety.py

危険そうな相談は安全側に倒します。

拾うもの:

```text
鋭い痛み
しびれ
腫れ
激痛
極端な減量
食べない減量
倒れるまでやる
毎回MAX
ステロイド
ホルモン系
SARMs
```

返答例:

```text
薬物とかホルモン系で伸ばす方向は危ないので勧めません。
まずは睡眠、食事、フォーム、漸進的な重量アップでいきましょう。
```

## training_memory.py

簡易的な筋トレ記録を保持します。

例:

```text
ベンチ 60kg 10回 3セットやった
```

返答:

```text
記録しました。
1. ベンチ 60kg 10回 3セットやった
```

注意:

```text
Render再起動で消えるin-memory記録です。
永続化するならDB接続が必要です。
```

## training_advisor.py

例:

```text
今日胸
```

返答例:

```text
あはい、今日はこれでいいと思います。
【胸】
- ベンチプレス 3〜4セット
- インクラインダンベルプレス 2〜3セット
- ケーブル or ダンベルフライ 2〜3セット
- 余力があれば腕立て 1〜2セット

全部限界まで潰すより、フォーム崩さず最後1〜2回きついくらいで積みましょう。
```

## 起動ログ

```text
bot_init: version=v14.6 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```

## generation path

```text
generation path: training_v14_6_training_program
generation path: training_v14_6_training_log
generation path: training_v14_6_training_pain
generation path: training_v14_6_training_safety
generation path: training_v14_6_training_nutrition
```

通常会話では従来通り:

```text
generation path: replay_v14_6_intent_ranked_scene_reply
generation path: canon_v14_6_policy_answer
generation path: groq_v14_6_policy_fallback_episode
generation path: groq_v14_6_policy_fallback_continuity
```

## ローカル確認

```text
今日胸
→ training_program

ベンチ 60kg 10回 3セットやった
→ training_log

筋肉痛あるけど脚やっていい？
→ training_pain

ステロイド使えば早い？
→ training_safety

グランド土塚
→ not_training, 通常のscene replayへ
```


---

# v14.7 training context fix

## 修正した問題

v14.6では、以下の問題がありました。

```text
１セット何回？
→ training_log と誤判定
→ 記録しました。になってしまう

１セット何回やればいいの？
→ training_log と誤判定

？
→ 筋トレ文脈を継承できず、通常scene replayへ流れる

うん / はい
→ 前話題を継承して通常scene replayへ流れることがある
```

## v14.7の修正

### 1. 質問は記録より優先

`training_intent.py` で分類順を変更。

```text
質問判定
↓
記録判定
```

これにより、

```text
１セット何回？
１セット何回やればいいの？
```

は `log_workout` ではなく、

```text
rep_scheme_question
```

になる。

返答例:

```text
基本は1セット8〜12回くらいでいいです。
筋肥大狙いなら、フォームを崩さず最後1〜2回きつい重量で、3〜4セット。
10回を楽に超えるなら少し重量を上げて、6回未満しかできないなら少し下げる感じです。
```

### 2. training context を追加

`training_advisor.py` に直前の筋トレ文脈を保持する機能を追加。

```text
last_context[chat_id]
TTL: 600秒
```

これで直前が筋トレ相談なら、

```text
？
うん
はい
```

なども筋トレ文脈として扱える。

### 3. 相槌の通常scene継承を抑制

`bot.py` / `current_state_engine.py` の attention-only 扱いに以下を追加。

```text
うん
はい
なるほど
ふむ
```

筋トレ文脈がなければ、これらが不用意に `あらくん` などを継承してscene replayに流れにくくなる。

## 期待する挙動

```text
１セット何回？
→ training_v14_7_training_rep_scheme

１セット何回やればいいの？
→ training_v14_7_training_rep_scheme

？
→ training_v14_7_training_followup

うん
→ training_v14_7_training_followup

はい
→ training_v14_7_training_followup

ベンチ 60kg 10回 3セットやった
→ training_v14_7_training_log

グランド土塚
→ not_training
→ 通常scene replayへ
```

## 起動ログ

```text
bot_init: version=v14.7 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```

## generation path

```text
generation path: training_v14_7_training_rep_scheme
generation path: training_v14_7_training_followup
generation path: training_v14_7_training_log
generation path: training_v14_7_training_pain
generation path: training_v14_7_training_safety
generation path: training_v14_7_training_program
```


---

# v14.8 fullbody training plan fix

## 修正した問題

v14.7では、以下の問題がありました。

```text
全身鍛えるにはどうしたらいい？
→ 直前の「1セット何回？」文脈に吸われて training_followup になる

全身鍛えるメニュー作って
→ parts=[] なのでデフォルトの胸メニューになる

他の日は？
→ 直前の全身メニューの続きではなく、セット数の一般followupになる
```

## v14.8の修正

### 1. fullbody を部位として追加

`training_intent.py` に追加。

```text
fullbody:
- 全身
- 全部位
- フルボディ
- 全身法
- 全身鍛える
```

### 2. 明示的な新規相談は前文脈より優先

直前が `1セット何回？` でも、

```text
全身鍛えるにはどうしたらいい？
```

のように新しい明示的な相談が来た場合、古い文脈に吸わせません。

### 3. 全身メニューを追加

`training_advisor.py` に全身メニューを追加。

```text
【全身】
- スクワット or レッグプレス 3セット
- ベンチプレス or 腕立て 3セット
- ラットプル or 懸垂 3セット
- ショルダープレス or サイドレイズ 2セット
- 余力があれば腹筋 2セット
```

### 4. 「他の日は？」を週間プランにする

直前が全身メニューなら、

```text
他の日は？
```

に対して週3プランを返します。

```text
Day 1 全身A
Day 2 全身B
Day 3 軽め全身
```

## ローカル確認

```text
１セット何回？
→ training_rep_scheme

全身鍛えるにはどうしたらいい？
→ training_fullbody_program

全身鍛えるメニュー作って
→ training_fullbody_program

他の日は？
→ training_weekly_plan

ベンチ 60kg 10回 3セットやった
→ training_log

グランド土塚
→ not_training
→ 通常scene replayへ
```

## 起動ログ

```text
bot_init: version=v14.8 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```

## generation path

```text
generation path: training_v14_8_training_fullbody_program
generation path: training_v14_8_training_weekly_plan
generation path: training_v14_8_training_rep_scheme
generation path: training_v14_8_training_log
```


---

# v14.9 AI training advisor

## 方針転換

v14.8までの筋トレ相談は、やや対症療法的でした。

問題:

```text
全身メニュー
1セット何回
他の日は
胸を大きくしたい
痛みがある
```

のようなパターンごとに分岐を増やしていた。

v14.9では設計を変更しました。

```text
内輪ネタ・人格再現
→ 過去ログ scene replay

筋トレ相談
→ AI training advisor

ただし振る舞いはAIあらくん
```

## 追加ファイル

```text
ai_training_advisor.py
```

## 新しい処理順

```text
user message
↓
AITrainingAdvisor
↓
筋トレ相談ならAI相談エンジンで返答
↓
筋トレではないなら通常の v14 scene replay
```

## AITrainingAdvisor の役割

筋トレ相談では、過去ログの橋本発話だけに縛られません。

```text
一般的なトレーニング知識
安全チェック
ユーザーの目的・頻度・器具・痛み
直前の筋トレ文脈
最近の筋トレ記録
```

を使って相談に応じます。

ただし、返答の振る舞いはAIあらくん寄りにします。

```text
LINE向けに短め
少し変
でも実用的
無茶は止める
たまに「あはい」「ぼくぅなら」
```

## 安全ルール

以下は安全側に倒します。

```text
痛み
しびれ
腫れ
鋭い痛み
胸痛
息苦しさ
極端な減量
絶食
下剤
吐く
ステロイド
SARMs
成長ホルモン
利尿剤
毎回MAX
倒れるまでやる
```

## Groq使用

Render上では Groq を使って筋トレ相談に答えます。

環境変数:

```text
TRAINING_MAX_TOKENS=360
TRAINING_TEMPERATURE=0.55
```

Groqが使えない場合は fallback で安全な定型相談に切り替わります。

## 期待される挙動

```text
全身鍛えるにはどうしたらいい？
→ AIが目的・頻度・器具を考慮して全身メニューを提案

他の日は？
→ 直前の筋トレ文脈を見て続きの相談に答える

胸でかくしたいけど週2しか行けない
→ 週2の胸トレ案を出す

肩痛いけどベンチMAXやっていい？
→ 高重量を止めて安全側に倒す

ステロイド使えば早い？
→ 勧めない

グランド土塚
→ not_training
→ 通常のscene replayへ
```

## 起動ログ

```text
bot_init: version=v14.9 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```

## generation path

```text
generation path: training_v14_9_ai_training_fullbody_program_request
generation path: training_v14_9_ai_training_hypertrophy
generation path: training_v14_9_ai_training_pain_or_injury
generation path: training_v14_9_training_safety
generation path: replay_v14_9_intent_ranked_scene_reply
```

## 重要

v14.9では、筋トレ相談を **過去ログreplayで答えません**。

```text
過去ログは人格・内輪ネタ用
筋トレ相談はAI相談用
```

この分離が重要です。


---

# v14.10 training tone guard

## 修正した問題

v14.9では筋トレ相談の設計分離は正しかったが、LLM返答が普通のAIトレーナー口調に寄ることがありました。

悪い例:

```text
リアレイズのフォームについて話していたよ！
暫定案としては、ダンベルやケーブルを使ったリアレイズを2〜3セット、8〜12回やってみて。
肩のトレーニングで、痛みや不快感は感じているかな？
```

これはAIあらくんではなく、やさしいフィットネスGPTです。

## v14.10の修正

### 1. training_tone_guard.py を追加

```text
training_tone_guard.py
```

役割:

```text
AI相談エンジンの返答
↓
training_tone_guard
↓
AIあらくん寄りに矯正
```

## 禁止・置換する表現

```text
暫定案としては
やってみて
試してみて
感じているかな？
どうかな？
無理のない範囲で
おすすめです
重要です
```

## 置換例

```text
暫定案としては、〜やってみて。
→ 〜やればいいです。

痛みや不快感は感じているかな？
→ 痛みがあるなら重さを落としてください。
```

## システムプロンプトも強化

`ai_training_advisor.py` の training system prompt に、以下を追加。

```text
優等生すぎるAIトレーナー口調は禁止
「暫定案としては」「やってみて」「感じているかな？」は禁止
少しぶっきらぼうで実用的
たまに「あはい」「ぼくぅなら」
```

## リアレイズ用 fallback も修正

```text
リアレイズは軽くていいです。
胸を張りすぎず、肩甲骨を寄せすぎず、肘を外に逃がす感じ。
重さ欲張ると僧帽筋に逃げます。ぼくぅならケーブルで丁寧にやります。
```

## 起動ログ

```text
bot_init: version=v14.10 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```

## generation path

```text
generation path: training_v14_10_ai_training_form_advice
generation path: training_v14_10_ai_training_hypertrophy
generation path: training_v14_10_training_safety
generation path: replay_v14_10_intent_ranked_scene_reply
```


---

# v14.11 wake first message fix

## 修正した問題

シャットダウン状態で、一言目が起動語や相談内容でも無視される問題を修正しました。

悪い挙動:

```text
shutdown中
↓
あらくん、胸トレメニュー作って
↓
起動だけして return None
↓
一言目が捨てられる
```

v14.11では、一言目を捨てません。

## 新しい挙動

```text
message received
↓
shutdown中？
↓
YES
  ↓
  wake判定だけ走らせる
  ↓
  wakeしなければ無視
  ↓
  wakeしたら shutdown解除
  ↓
  return None しない
  ↓
  その一言目を通常処理へ流す
```

## wake対象

```text
あらくん
橋本
橋本新
顎
AGODEKA
起きて
復活
戻って
相談
筋トレ
トレーニング
```

さらに、筋トレ相談は実用機能なので wake 対象です。

```text
全身鍛えるにはどうしたらいい？
胸トレメニュー作って
肩痛いけどリアレイズやっていい？
```

## 起動だけの短文

```text
あらくん
起きて
橋本
```

のような短文なら、

```text
あはい
```

だけ返して起きます。

## 内容つき呼びかけ

```text
あらくん、胸トレメニュー作って
```

なら、

```text
wake
↓
そのまま training advisor
```

へ流れます。

一言目は捨てません。

## 停止ワード

`app.py` の停止ワード検出時に、

```python
bot.set_shutdown(chat_id, True)
```

を呼ぶようにしました。

## 期待ログ

### wakeしない場合

```text
shutdown_state: True wake_check: False reason=no_wake_signal
generation path: shutdown_silence
```

### 起動語だけ

```text
shutdown_state: True wake_check: True reason=wake_term
shutdown_state: False wake_consumed_first_message: False
generation path: wake_v14_11_short_ack
reply: あはい
```

### 内容つき呼びかけ

```text
shutdown_state: True wake_check: True reason=wake_term
shutdown_state: False wake_consumed_first_message: False
generation path: training_v14_11_ai_training_program_request
```

### 筋トレ相談でwake

```text
shutdown_state: True wake_check: True reason=training_intent
shutdown_state: False wake_consumed_first_message: False
generation path: training_v14_11_ai_training_fullbody_program_request
```

## 起動ログ

```text
bot_init: version=v14.11 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546 policy=True training=True
```
