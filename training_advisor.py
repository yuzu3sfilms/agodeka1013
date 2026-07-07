import random
import time
from collections import defaultdict

from training_intent import classify_training_intent
from training_safety import check_training_safety
from training_memory import TrainingMemory


PART_LABELS = {
    "chest": "胸",
    "back": "背中",
    "legs": "脚",
    "shoulders": "肩",
    "arms": "腕",
    "core": "腹",
}


MENU = {
    "chest": [
        "ベンチプレス 3〜4セット",
        "インクラインダンベルプレス 2〜3セット",
        "ケーブル or ダンベルフライ 2〜3セット",
        "余力があれば腕立て 1〜2セット",
    ],
    "back": [
        "懸垂 or ラットプル 3〜4セット",
        "ローイング系 3セット",
        "デッドリフトはやるなら軽〜中重量で2〜3セット",
        "最後に背中を寄せる種目を軽く2セット",
    ],
    "legs": [
        "スクワット 3〜4セット",
        "レッグプレス 2〜3セット",
        "ルーマニアンデッド or レッグカール 2〜3セット",
        "カーフ 2セット",
    ],
    "shoulders": [
        "ショルダープレス 3セット",
        "サイドレイズ 3〜4セット",
        "リアレイズ 2〜3セット",
        "軽めにフェイスプル 2セット",
    ],
    "arms": [
        "アームカール 3セット",
        "インクラインカール 2セット",
        "プッシュダウン 3セット",
        "オーバーヘッドエクステンション 2セット",
    ],
    "core": [
        "プランク 2〜3セット",
        "レッグレイズ 2〜3セット",
        "ケーブルクランチ or クランチ 2〜3セット",
    ],
}


class TrainingAdvisor:
    def __init__(self):
        self.memory = TrainingMemory()
        self.last_context = defaultdict(dict)
        self.context_ttl_seconds = 600

    def _context(self, chat_id: str):
        ctx = self.last_context.get(chat_id, {})
        if not ctx:
            return {}
        if time.time() - ctx.get("ts", 0) > self.context_ttl_seconds:
            self.last_context[chat_id] = {}
            return {}
        return ctx

    def _remember_context(self, chat_id: str, info: dict, answer: str = ""):
        if info.get("is_training"):
            self.last_context[chat_id] = {
                "ts": time.time(),
                "intent": info.get("intent"),
                "parts": info.get("parts", []),
                "last_answer": answer,
            }

    def detect(self, text: str, chat_id: str | None = None):
        ctx = self._context(chat_id) if chat_id else {}
        return classify_training_intent(text, last_training_context=ctx)

    def _tone(self, text: str):
        # Keep the persona light. Avoid too much roleplay.
        starters = [
            "それなら、",
            "いいですね。",
            "あはい、",
            "まずは安全にいきましょう。",
        ]
        if len(text) <= 12:
            return random.choice(["あはい、", "それなら、"])
        return random.choice(starters)

    def _format_menu(self, parts):
        if not parts:
            parts = ["chest"]
        lines = []
        for part in parts[:2]:
            label = PART_LABELS.get(part, part)
            lines.append(f"【{label}】")
            for item in MENU.get(part, [])[:4]:
                lines.append(f"- {item}")
        return "\n".join(lines)

    def _used(self, chat_id: str, kind: str, answer: str, info: dict, **extra):
        self._remember_context(chat_id, info, answer)
        out = {"used": True, "kind": kind, "answer": answer, "intent": info}
        out.update(extra)
        return out

    def answer(self, chat_id: str, user_text: str):
        ctx = self._context(chat_id)
        info = classify_training_intent(user_text, last_training_context=ctx)
        safety = check_training_safety(user_text)

        # Safety-related muscle/drug/diet questions should be caught even if
        # they do not contain normal workout words.
        if not info.get("is_training") and safety.get("safe"):
            return {"used": False, "reason": "not_training"}

        if not info.get("is_training") and not safety.get("safe"):
            info = {"is_training": True, "intent": "safety_question", "parts": [], "is_log": False}

        if not safety.get("safe"):
            return self._used(chat_id, "training_safety", safety["message"], info, safety=safety)

        intent = info.get("intent")
        parts = info.get("parts", [])

        if intent == "log_workout":
            item = self.memory.add(chat_id, user_text)
            ans = "記録しました。\n" + self.memory.format_recent(chat_id, limit=3)
            return self._used(chat_id, "training_log", ans, info)

        if "最近の記録" in user_text or "前回" in user_text:
            ans = self.memory.format_recent(chat_id, limit=5)
            return self._used(chat_id, "training_recent_log", ans, info)

        if intent in ["rep_scheme_question", "set_scheme_question"]:
            ans = (
                "基本は1セット8〜12回くらいでいいです。\n"
                "筋肥大狙いなら、フォームを崩さず最後1〜2回きつい重量で、3〜4セット。\n"
                "10回を楽に超えるなら少し重量を上げて、6回未満しかできないなら少し下げる感じです。"
            )
            return self._used(chat_id, "training_rep_scheme", ans, info)

        if intent == "training_ack_or_followup":
            ans = (
                "続きで言うと、まずは3セットで十分です。\n"
                "各セット8〜12回、最後だけきついくらい。\n"
                "慣れてきたら4セット目を足す、くらいでいいと思います。"
            )
            return self._used(chat_id, "training_followup", ans, info)

        if intent == "training_followup_question":
            prev_intent = ctx.get("intent")
            if prev_intent in ["rep_scheme_question", "set_scheme_question", "training_ack_or_followup"]:
                ans = (
                    "さっきの続きなら、1セット8〜12回を目安にすればいいです。\n"
                    "3セットから始めて、余裕があれば4セット。\n"
                    "全部潰れるまでじゃなくて、最後1〜2回きついくらいで十分です。"
                )
            else:
                ans = (
                    "続きで言うと、まずは3セットで十分です。\n"
                    "各セット8〜12回、最後だけきついくらい。\n"
                    "慣れてきたら4セット目を足す、くらいでいいと思います。"
                )
            return self._used(chat_id, "training_followup", ans, info)

        if intent == "pain_or_injury":
            ans = (
                "筋肉痛なら軽めに流すのはありです。\n"
                "でも関節の痛み、鋭い痛み、しびれ、腫れがあるなら今日はやめましょう。\n"
                "ぼくぅでもそこは攻めません。別部位か休みに逃げていいです。"
            )
            return self._used(chat_id, "training_pain", ans, info)

        if intent in ["program_request", "hypertrophy", "general_training"]:
            if not parts:
                # Infer common shorthand.
                t = user_text
                if "胸" in t:
                    parts = ["chest"]
                elif "背中" in t:
                    parts = ["back"]
                elif "脚" in t or "足" in t:
                    parts = ["legs"]
                elif "肩" in t:
                    parts = ["shoulders"]
                elif "腕" in t:
                    parts = ["arms"]
                elif "腹" in t:
                    parts = ["core"]
            menu = self._format_menu(parts)
            ans = (
                f"{self._tone(user_text)}今日はこれでいいと思います。\n"
                f"{menu}\n\n"
                "全部限界まで潰すより、フォーム崩さず最後1〜2回きついくらいで積みましょう。"
            )
            return self._used(chat_id, "training_program", ans, info)

        if intent == "form_advice":
            ans = (
                "フォームはまず重量より優先です。\n"
                "反動を減らして、狙う筋肉に乗ってる感じがある重量まで落としましょう。\n"
                "動画を撮れるなら横から撮るとかなり分かります。"
            )
            return self._used(chat_id, "training_form", ans, info)

        if intent == "nutrition_cut":
            ans = (
                "減量は急に削りすぎない方がいいです。\n"
                "まずはタンパク質を毎食入れて、間食と脂質を少し整えて、体重の週平均を見るのが安全です。\n"
                "食べない方向に行くと筋肉もメンタルも削れます。"
            )
            return self._used(chat_id, "training_nutrition", ans, info)

        ans = (
            "筋トレ相談ですね。\n"
            "目的が筋肥大なら、狙う部位を決めて3〜4種目、各2〜4セットくらいからで十分です。\n"
            "痛みがある日は無理しないでください。"
        )
        return self._used(chat_id, "training_general", ans, info)
