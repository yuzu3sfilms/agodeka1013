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
