# AI橋本新 v11 relationship + QA engine

## 修正理由

v10系の弱点:

1. 検索エピソードは拾えるが、単純な質問に適切に答えない
2. グループ内の人間関係を別レイヤーとして学習していない
3. そのため「誰が誰か」「橋本新が誰にどう返していたか」が返答に反映されにくい

## v11の追加構造

```text
ユーザー発言
↓
検索語抽出
↓
過去LINEログ全文検索
↓
ヒット発言・周辺エピソード取得
↓
質問判定
↓
人物関係プロファイルを追加
↓
質問ならまず質問に答える
↓
橋本新の口調で返答
```

## 追加ファイル

```text
data/relationship_profile.json
relationship.py
```

## relationship_profile.json の中身

LINEログから自動抽出:

```text
主要発言者
橋本新系として扱う発言者
橋本新系アカウントがよく反応していた相手
人物・呼称の出現頻度
橋本新系発言の口調サンプル
```

例:

```text
Reiji Shioda
村田
坂口
Ryo Sekiguchi
中山 貴文
LIAR OF ARAKUN
Unknown
橋本新
Arata Hashimoto
```

## 質問応答モード

以下を含むと質問扱い:

```text
？
?
何
誰
どこ
いつ
なんで
どう
使う
作って
なの
```

ログ:

```text
dynamic_search terms=[...] hits=... episodes=... called=False question=True
generation path: groq_relationship_qa
```

## プロンプトの重要変更

質問時:

```text
ユーザーが質問している時は、まず質問に答える。
答えは過去ログエピソードと人物関係から推測する。
分からない時は説明せず、短く曖昧に逃がす。
```

通常時:

```text
エピソード内の出来事・人物関係・呼称を拾う。
説明AIではなく、橋本新としてLINEで返す。
```

## 挙動

```text
エピソードあり
→ エピソード + 人物関係 + 口調サンプルから返答

エピソードなし + 呼びかけあり
→ ｷｬﾋﾟｨ

エピソードなし + 呼びかけなし
→ 無視

Groqエラー/429
→ ｷｬﾋﾟｨ
```

## 必須環境変数

```text
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
GROQ_API_KEY
```
