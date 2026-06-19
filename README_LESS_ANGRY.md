# AI橋本新 v2.3 less angry

v2.2 guaranteed reply は「無言にならない」ことを優先したため、過去ログから強い口調・キレ気味の返答まで拾いやすくなっていた。

v2.3では、人格模倣は維持しつつ、怒り・罵倒・攻撃性だけが過剰再生されないようにした。

## 変更点

- anti_echo.py に anger filter を追加
- local reply の候補から強すぎる怒り文を除外
- Groq prompt に「怒りだけ過剰再現しない」を追加
- 429時のローカル返答でも、落ち着いた短文に逃げる

## 環境変数

通常は不要。

怒りフィルタを切る場合だけ:

ANGER_FILTER_ENABLED=0

ユーザーが怒っている時だけ怒り返答を許す場合:

ALLOW_ANGRY_REPLY_WHEN_USER_ANGRY=1

基本はどちらも設定しないのがおすすめ。
