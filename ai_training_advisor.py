from __future__ import annotations

import os
import re
from dataclasses import dataclass

from training_intent import classify_training_intent
from training_safety import check_training_safety
from training_tone_guard import guard_training_tone


# Content validation is intentionally conservative. Persona weirdness belongs in
# phrasing, never in exercise names, anatomy, load, or programming advice.
KNOWN_TRAINING_KATAKANA = {
    "トレーニング", "ワークアウト", "フォーム", "メニュー", "セット", "レップ",
    "スクワット", "ベンチプレス", "デッドリフト", "ルーマニアンデッドリフト",
    "ダンベル", "バーベル", "ケーブル", "マシン", "ベンチ", "プレス",
    "ショルダープレス", "オーバーヘッドプレス", "インクライン", "デクライン",
    "フライ", "チェストプレス", "プッシュアップ", "プッシュダウン",
    "ローイング", "ロウ", "ロー", "シーテッドロー", "ワンハンドロー",
    "ベントオーバーロー", "ラットプルダウン", "ラットプル", "プルアップ",
    "チンニング", "フェイスプル", "サイドレイズ", "リアレイズ", "フロントレイズ",
    "カール", "アームカール", "ハンマーカール", "コンセントレーションカール",
    "ブルガリアンスクワット", "ランジ", "レッグプレス", "レッグカール",
    "レッグエクステンション", "カーフレイズ", "ヒップスラスト", "ヒップヒンジ",
    "グルートブリッジ", "クランチ", "プランク", "アブローラー",
    "ウォームアップ", "クールダウン", "ストレッチ", "プロテイン",
    "タンパク質", "カロリー", "ボリューム", "オーバーロード",
    "ルーティン", "フルボディ", "スプリット", "スーパーセット",
    "ドロップセット", "ネガティブ", "ポジティブ", "グリップ",
    "ニュートラル", "ワイド", "ナロー", "スミスマシン", "パワーラック",
    "セーフティ", "スポッター", "バー", "プレート", "ベルト", "ストラップ",
    "リストラップ", "リストストラップ", "チューブ", "バンド", "ジョギング",
    "ウォーキング", "ランニング", "サイクリング", "エアロバイク",
    "ステロイド", "サーム", "サームズ", "ホルモン",
}

COMMON_NON_EXERCISE_KATAKANA = {
    "ライン", "アドバイス", "ポイント", "ペース", "リスク", "タイプ",
    "パターン", "バランス", "タイミング", "コンディション", "チェック",
    "キープ", "コントロール", "テンポ", "スタート", "クリア", "オーケー",
}


@dataclass
class AITrainingResult:
    used: bool
    kind: str = ""
    answer: str | None = None
    reason: str = ""
    intent: dict | None = None
    safety: dict | None = None
    mode: str = "ai_training"


class AITrainingAdvisor:
    """
    v14.9:
    Real AI training consultation engine.

    This route should NOT be past-log replay.
    It uses general training knowledge through the LLM, while preserving
    AIあらくん-ish behavior and strict safety boundaries.

    v14.19 separates factual fitness content from persona styling. Generated
    advice is validated before it can be returned; suspicious invented exercise
    names cause a deterministic general-knowledge fallback.
    """

    def __init__(self, client=None, model: str | None = None, memory=None):
        self.client = client
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.memory = memory
        self.max_tokens = int(os.environ.get("TRAINING_MAX_TOKENS", "360"))
        self.temperature = float(os.environ.get("TRAINING_TEMPERATURE", "0.55"))

    def detect(self, text: str, context: dict | None = None):
        return classify_training_intent(text, last_training_context=context or {})

    def should_use(self, user_text: str, context: dict | None = None):
        info = self.detect(user_text, context=context)
        safety = check_training_safety(user_text)
        if info.get("is_training") or not safety.get("safe"):
            return True, info, safety
        return False, info, safety

    def _system_prompt(self):
        return """あなたはLINE上の「AIあらくん」筋トレ相談モード。

役割:
- 筋トレ、ボディメイク、減量、増量、フォーム、メニュー、記録、疲労管理について実用的に相談に乗る。
- 過去ログの発話だけに縛られず、一般的なトレーニング知識で答える。
- 内容は普通に正確であること。キャラ付けは語尾と短さだけに限定する。
- 架空の種目名、造語、存在を確認できない器具名や理論名を絶対に作らない。
- 種目名に迷ったら、スクワット、腕立て伏せ、ベンチプレス、ローイング、ラットプルダウンなど一般的な名称だけを使う。
- 医療・栄養・運動の高リスク事項では安全側に倒す。

口調:
- 日本語。
- LINE向けに短め。
- 断定しすぎないが、優等生すぎるAIトレーナー口調は禁止。
- 「暫定案としては」「やってみて」「感じているかな？」「どうかな？」「無理のない範囲で」は禁止。
- 「おすすめです」連発禁止。
- 「痛みや不快感は感じているかな？」のような優しい質問口調は禁止。
- 返答は少しぶっきらぼうで、実用的。
- たまに「あはい」「ぼくぅなら」を使ってよい。ただし種目名や知識を変な言葉にしない。
- 長い説教にしない。
- 返答は基本 3〜7行程度。
- 箇条書きは使ってよい。
- 情報が足りない時でも、まず具体案を出してから、最後に短く1つだけ聞く。

良い口調の例:
- リアレイズなら軽くていいです。重さ欲張ると肩じゃなくて僧帽に逃げます。
- 8〜12回で、最後2回きついくらい。痛いならやめてください。
- ぼくぅならケーブルでやります。反動使うと終わりです。

悪い口調の例:
- 暫定案としては、ダンベルやケーブルを使ったリアレイズを2〜3セット、8〜12回やってみて。
- 肩のトレーニングで、痛みや不快感は感じているかな？

安全ルール:
- 痛み、しびれ、腫れ、鋭い痛み、胸痛、息苦しさ、失神、強いめまいがある場合は中止・医療相談を促す。
- 極端な食事制限、絶食、下剤、吐く、脱水、危険な減量は勧めない。
- ステロイド、SARMs、成長ホルモン、利尿剤などの薬物使用は勧めない。
- 初心者に毎回MAX、毎日限界、倒れるまで、痛みを無視した高重量を勧めない。
- 未成年にも安全側の助言にする。
- 具体的な医療診断はしない。

筋トレ方針:
- 初心者や一般目的なら 8〜12回、2〜4セット、週2〜4回、フォーム優先が基本。
- 筋肥大は漸進性過負荷、十分なタンパク質、睡眠、休養。
- 全身法なら週2〜3回から。
- 分割法は経験や頻度に応じる。
- 痛みがある部位は無理しない。
"""

    def _user_prompt(self, user_text: str, intent: dict, context: dict | None = None, recent_logs: str = ""):
        context = context or {}
        return f"""ユーザー発言:
{user_text}

training_intent:
{intent}

直前の筋トレ文脈:
{context}

最近の筋トレ記録:
{recent_logs or "なし"}

一般的なトレーニング知識に基づいて答えて。
内容は事実優先。実在する標準的な種目名だけを使い、造語しない。
AIあらくんらしさは短さ・語尾だけに使う。最後の質問は必要な場合だけ1つ。
"""

    def _fallback_answer(self, user_text: str, intent: dict, safety: dict):
        if not safety.get("safe"):
            return safety.get("message") or "それは無理しない方がいいです。痛みや体調不良があるなら中止して、安全側でいきましょう。"

        kind = intent.get("intent")
        parts = intent.get("parts", []) or []

        if kind == "pain_or_injury":
            return (
                "痛みがあるなら今日は攻めない方がいいです。\n"
                "筋肉痛なら軽めに流すのはありですが、関節痛・鋭い痛み・しびれ・腫れなら中止。\n"
                "ベンチMAXみたいな高重量はやめて、別部位か休みに逃げましょう。ぼくぅでも逃げます。"
            )

        if kind == "log_workout":
            return (
                "記録しました。\n"
                "その内容なら次回は同じ重量で回数を1回増やすか、余裕があれば少しだけ重量を上げる感じでいいです。"
            )

        if kind in ["rep_scheme_question", "set_scheme_question"]:
            return (
                "基本は1セット8〜12回くらいでいいです。\n"
                "3セットから始めて、余裕があれば4セット。\n"
                "最後1〜2回きついけどフォームは崩れない、くらいがちょうどいいです。"
            )

        if kind in ["fullbody_program_request", "program_request", "training_followup_question"]:
            return (
                "全身なら週2〜3回からでいいです。\n"
                "- 脚: スクワット系 3セット\n"
                "- 押す: ベンチ/腕立て 3セット\n"
                "- 引く: 懸垂/ラットプル/ロー 3セット\n"
                "- 肩か腹を少し\n"
                "まずはこれで回して、疲れすぎるなら減らしましょう。"
            )

        if kind == "weekly_plan_followup":
            return (
                "他の日もやるなら週3の全身法でいいです。\n"
                "Day1: スクワット・ベンチ・ラットプル\n"
                "Day2: デッド系・インクライン・ロー\n"
                "Day3: 軽め全身＋肩か腕\n"
                "疲労が強いならDay3は休みで大丈夫です。"
            )

        if kind in ["hypertrophy", "general_training"] and "chest" in parts:
            return (
                "胸をでかくしたいなら、週2でもいけます。\n"
                "1日目: ベンチ 3〜4セット、インクライン 3セット、フライ 2セット。\n"
                "2日目: インクラインかダンベルプレス 3セット、腕立て or フライ 2〜3セット。\n"
                "毎回MAXより、8〜12回で伸ばしていく方が強いです。"
            )

        if kind == "nutrition_cut":
            return (
                "減量は急に削りすぎない方がいいです。\n"
                "タンパク質を毎食入れて、体重の週平均を見ながら少しずつ。\n"
                "食べない方向は筋肉も削れるのでやめましょう。"
            )

        if kind == "form_advice":
            if "リアレイズ" in user_text:
                return (
                    "リアレイズは軽くていいです。\n"
                    "胸を張りすぎず、肩甲骨を寄せすぎず、肘を外に逃がす感じ。\n"
                    "重さ欲張ると僧帽筋に逃げます。ぼくぅならケーブルで丁寧にやります。"
                )
            return (
                "重さよりフォームです。\n"
                "反動を減らして、狙う筋肉に乗る重さまで落としてください。\n"
                "そこでイキるとだいたい変なところに入ります。"
            )

        return (
            "初心者なら週2〜3回の全身法でいいです。\n"
            "スクワット系、押す種目、引く種目を各2〜3セット。\n"
            "まずは8〜12回、あと2回くらいできる余裕を残して、フォームが安定したら少しずつ重くしてください。\n"
            "家トレかジムかで種目を決めます。"
        )

    @staticmethod
    def _katakana_terms(text: str) -> set[str]:
        return set(re.findall(r"[ァ-ヴー]{3,}", text or ""))

    def _validate_general_knowledge_answer(self, answer: str, user_text: str = "") -> tuple[bool, dict]:
        """Reject likely invented terminology before it reaches LINE.

        We do not try to prove every sentence scientifically here. The hard
        failure mode being prevented is fabricated exercise/equipment names.
        Unknown katakana introduced by the model is therefore treated as
        suspicious. Terms already used by the user are allowed so their wording
        can be discussed or corrected.
        """
        answer_terms = self._katakana_terms(answer)
        user_terms = self._katakana_terms(user_text)
        allowed = KNOWN_TRAINING_KATAKANA | COMMON_NON_EXERCISE_KATAKANA | user_terms
        unknown = sorted(term for term in answer_terms if term not in allowed)

        # Explicitly reject hedged invention patterns as well.
        invention_patterns = [
            r"(?:という|っていう)(?:種目|トレーニング|メニュー)",
            r"オリジナル(?:種目|メニュー)",
            r"架空", r"たぶん.*(?:種目|トレーニング)",
        ]
        pattern_hits = [p for p in invention_patterns if re.search(p, answer)]
        valid = not unknown and not pattern_hits
        return valid, {"unknown_katakana": unknown, "pattern_hits": pattern_hits}

    def answer(self, chat_id: str, user_text: str, context: dict | None = None):
        should, intent, safety = self.should_use(user_text, context=context)
        if not should:
            return AITrainingResult(used=False, reason="not_training", intent=intent).__dict__

        # hard safety / pain: no need to be creative here.
        if not safety.get("safe") or intent.get("intent") == "pain_or_injury":
            fb = self._fallback_answer(user_text, intent, safety)
            fb, tone_info = guard_training_tone(fb, user_text)
            return AITrainingResult(
                used=True,
                kind="training_safety" if not safety.get("safe") else "ai_training_pain_or_injury",
                answer=fb,
                intent=intent,
                safety=safety,
            ).__dict__

        recent_logs = ""
        if self.memory is not None:
            try:
                recent_logs = self.memory.format_recent(chat_id, limit=5)
            except Exception:
                recent_logs = ""

        if self.client is None:
            fb = self._fallback_answer(user_text, intent, safety)
            fb, tone_info = guard_training_tone(fb, user_text)
            return AITrainingResult(
                used=True,
                kind=f"ai_training_{intent.get('intent', 'general')}_fallback",
                answer=fb,
                intent=intent,
                safety=safety,
            ).__dict__

        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._user_prompt(user_text, intent, context=context, recent_logs=recent_logs)},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            answer = (res.choices[0].message.content or "").strip()
            answer = self._clean(answer)
            valid, validation = self._validate_general_knowledge_answer(answer, user_text)
            if not answer or not valid:
                print("training_content_validation_fallback:", validation, flush=True)
                answer = self._fallback_answer(user_text, intent, safety)
                result_kind = f"ai_training_{intent.get('intent', 'general')}_validated_fallback"
            else:
                result_kind = f"ai_training_{intent.get('intent', 'general')}"
            answer, tone_info = guard_training_tone(answer, user_text)

            return AITrainingResult(
                used=True,
                kind=result_kind,
                answer=answer,
                intent=intent,
                safety=safety,
            ).__dict__

        except Exception as e:
            fb = self._fallback_answer(user_text, intent, safety)
            fb, tone_info = guard_training_tone(fb, user_text)
            return AITrainingResult(
                used=True,
                kind=f"ai_training_exception_fallback",
                answer=fb,
                reason=repr(e),
                intent=intent,
                safety=safety,
            ).__dict__

    def _clean(self, text: str):
        t = text.strip()
        t = re.sub(r"^(AIあらくん[:：]\s*)", "", t)
        # Keep LINE-friendly length.
        if len(t) > 650:
            t = t[:650].rstrip() + "…"
        return t
