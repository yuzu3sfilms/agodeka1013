# AI_HASHIMOTO_ARATA v14.2 clean rebuild

## 目的

この版は、v12/v13系の「検索してLLMに作文させるBot」から切り替えた、**conversation-state replay engine** 版です。

合言葉:

```text
生成するな、再演しろ
```

## v14.2の方針

LINEグループの会話では、発言が必ずしも直前の発言への返答とは限りません。

そのため、v14.2では以下のように処理します。

```text
ユーザー発言
↓
会話状態・話題を更新
↓
過去ログの会話場面を検索
↓
その場面で橋本が実際に言った発話を候補にする
↓
使える場合はそのまま再演
↓
使えない場合だけGroq fallback
```

## 主な構成

```text
app.py
bot.py
actual_reply_engine.py
canon_answer.py
dynamic_search.py
relevance.py
persona_judge.py
relationship.py
style_guard.py
utils.py
data/
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

## 削除した旧ファイル

v14.2 clean rebuildでは、v14初期の旧reply-pair系ファイルを削除しました。

```text
data/reply_pairs.jsonl.gz
data/reply_pair_stats.json
```

理由:

```text
LINE会話を「直前発言 → 返答」と決め打ちしないため
conversation_scenes に一本化するため
```

## conversation_scenes

橋本の各発言について、以下を保存しています。

```text
前12発言
橋本の実発言
後6発言
```

統計:

```text
messages: 108530
scenes: 5546
reply_length_median: 10.0
short_rate: 0.5905156869816084
```

## 返答優先順位

```text
1. canon_answer
   数値・確定答えを過去ログから直接返す

2. actual_reply_engine
   過去ログの会話場面から橋本の実発話を再演する

3. Groq fallback + persona_judge
   scene replay が使えない場合だけ候補生成する
```

## style_guard

v14.2では語尾の強制変換をやめています。

旧版では、

```text
大丈夫ですか
↓
大丈夫だわか
```

のように日本語が壊れることがありました。

v14.2の `style_guard.py` は以下だけ行います。

```text
候補ラベル除去
AI自己説明の除去
壊れた断片の修正
長すぎる返答の軽いtrim
```

普通の日本語の語尾は無理に削りません。

## 起動ログ

Render起動時に以下が出れば正常です。

```text
bot_init: version=v14.2 persona_judge=True persona_profile_loaded=True topic_canon_loaded=True replay_scenes=5546
```

## replay成功ログ

```text
replay_engine: {'used': True, 'mode': 'scene_replay', 'chosen': ...}
generation path: replay_v14_2_scene_reply
```

## fallbackログ

scene replayが使えない場合だけGroqに行きます。

```text
replay_engine: {'used': False, 'reason': 'no_scene_replay_hit'}
generation path: groq_v14_fallback_judged_episode
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

## v14.2の狙い

```text
古い修正履歴を整理
旧reply_pair構造を削除
conversation scene replayに一本化
過去ログ実発話を主役にする
LLM生成は最後の保険にする
日本語を後処理で壊さない
```
