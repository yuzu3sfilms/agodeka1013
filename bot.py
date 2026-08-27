from __future__ import annotations

import os
import re
import threading
from collections import defaultdict

from openai import OpenAI

from ago_runtime import CorpusIndex, DialogueState, MeaningResolver

try:
    from shutdown_state import ShutdownStateStore
except Exception:
    class ShutdownStateStore:
        def __init__(self): self._d = {}
        def set(self, k, v): self._d[k] = bool(v)
        def get(self, k): return bool(self._d.get(k, False))

try:
    from speaker_resolver import SpeakerResolver
except Exception:
    SpeakerResolver = None

PROJECT_VERSION = "v14.47"
ERROR_FALLBACK = "ｷｬﾋﾟｨ"


class AgoHashimotoBot:
    """Project AGO v14.47 — clean conversation core.

    Architecture: resolve once -> retrieve grounded evidence -> one generation.
    No candidate tournament, no downstream semantic re-guessing, no replay override.
    """

    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        self.client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
        self.corpus = CorpusIndex(roots=["data", "."])
        self.resolver = MeaningResolver(self.corpus)
        self.states = defaultdict(DialogueState)
        self.locks = defaultdict(threading.RLock)
        self.shutdown_store = ShutdownStateStore()
        self.speaker_resolver = SpeakerResolver() if SpeakerResolver else None
        self.max_history = int(os.environ.get("AGO_HISTORY", "12"))
        print("bot_init:", {"version": PROJECT_VERSION, "messages": len(self.corpus.messages), "hashimoto_lines": len(self.corpus.hashimoto_lines), "people": len(self.corpus.name_to_aliases)}, flush=True)

    def set_shutdown(self, chat_id: str, value: bool = True):
        self.shutdown_store.set(chat_id, bool(value))

    def is_shutdown(self, chat_id: str) -> bool:
        try: return bool(self.shutdown_store.get(chat_id))
        except Exception: return False

    @staticmethod
    def _is_group(chat_id: str) -> bool:
        return str(chat_id or "").startswith(("C", "R"))

    def _speaker(self, sender_id, display):
        if self.speaker_resolver:
            try:
                p = self.speaker_resolver.resolve(sender_id=sender_id, display_name=display)
                return p.canonical_name or p.display_name or display or sender_id or ""
            except Exception:
                pass
        return display or sender_id or ""

    def _history_text(self, state: DialogueState):
        out = []
        for t in state.turns[-8:]:
            who = "相手" if t.get("role") == "user" else "橋本新"
            out.append(f"{who}: {t.get('text','')}")
        return "\n".join(out) or "なし"

    def _prompt(self, meaning, state, speaker):
        style = self.corpus.style_examples(meaning.raw, 8)
        rel = self.corpus.relationship_examples(meaning.target_id, 8) if meaning.target_id else []
        mentions = self.corpus.mentions(meaning.target_id, 8) if meaning.target_id else []

        target_block = "なし"
        if meaning.target_id:
            target_block = f"target_id={meaning.target_id}\n呼び方={meaning.target_label}\n"
            if rel:
                target_block += "実際の相手別会話例:\n" + "\n".join(f"相手: {x['other']}\n橋本新: {x['hashimoto']}" for x in rel)
            if mentions:
                target_block += "\n橋本新本人による直接言及:\n" + "\n".join(f"- {x}" for x in mentions)

        special = ""
        if meaning.intent == "self_state":
            special = "自我・意識が実在すると断定しない。ただし説明AI口調にもせず、橋本新らしい短い返しにする。"
        elif meaning.intent == "person_opinion":
            special = "人物評価。相手別会話例と直接言及から読み取れる範囲だけで答える。根拠が薄ければ薄い評価にする。『好き』『嫌い』『どうでもいい』『微妙』を資料なしで創作しない。"
        elif meaning.intent == "subject_opinion":
            special = f"対象『{meaning.target_label}』への意見。人物辞書にない対象なので人物関係を捏造せず、橋本新の実ログ文体を使って普通に答える。"
        elif meaning.intent == "ambiguous_followup":
            special = "『どれ？』等だが直前に選択肢が確認できない。勝手にA/Bを作らず、『何が？』程度の自然な短い確認にする。"
        elif meaning.intent == "choice_followup":
            special = "直近会話に実在する選択肢だけを参照して答える。新しい選択肢を捏造しない。"

        system = """あなたはLINE上の橋本新を、実際の過去ログに基づいて再現するProject AGO。
便利AI、ChatGPT、カウンセラーとして振る舞わない。過剰に親切な『手伝える？』『詳しく教えて』を自動で言わない。
人格は奇妙な語尾ではなく、提示された実ログの反応・距離感・言い回しから再現する。
現在の意味解析結果は上流で確定済み。あなたは人物・主語・述語を再解釈しない。
資料にない過去経験、好き嫌い、関係性、感情、予定を発明しない。
LINEの一発言として自然に返す。通常1文、必要なら2文。候補一覧や説明は出さず返答本文だけ出す。"""

        user = f"""【確定した現在ターン】
intent={meaning.intent}
target={meaning.target_id or 'なし'}
predicate={meaning.predicate or 'なし'}
inherited_predicate={meaning.inherited_predicate}
user={meaning.raw}
speaker={speaker or '不明'}

【直近会話】
{self._history_text(state)}

【対象人物についての実ログ証拠】
{target_block}

【今回の話題に近い橋本新の実発言・文体例】
""" + "\n".join(f"- {x}" for x in style) + f"""

【今回だけの制約】
{special or '現在の発言へ普通に直接返す。'}

橋本新として返答本文だけ。"""
        return system, user

    @staticmethod
    def _clean(text):
        t = (text or "").strip()
        t = re.sub(r"^(?:候補\d+[:：]\s*)", "", t)
        t = t.strip('"「」')
        return t[:300].strip()

    def reply(self, chat_id: str, user_text: str, sender_id: str | None = None, sender_display_name: str | None = None) -> str | None:
        with self.locks[chat_id]:
            if self.is_shutdown(chat_id):
                return None
            state = self.states[chat_id]
            speaker = self._speaker(sender_id, sender_display_name)
            meaning = self.resolver.resolve(user_text, state, speaker, self._is_group(chat_id))
            print("meaning:", meaning.__dict__, flush=True)
            if not meaning.should_reply:
                print("generation path: v14_47_silence", flush=True)
                return None

            system, user = self._prompt(meaning, state, speaker)
            try:
                res = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role":"system","content":system},{"role":"user","content":user}],
                    temperature=float(os.environ.get("TEMPERATURE", "0.72")),
                    max_completion_tokens=int(os.environ.get("GROQ_MAX_COMPLETION_TOKENS", "256")),
                    extra_body={"reasoning_effort": os.environ.get("GROQ_REASONING_EFFORT", "low")},
                )
                answer = self._clean(res.choices[0].message.content or "")
                if not answer:
                    answer = ERROR_FALLBACK
            except Exception as e:
                print("Groq error:", repr(e), flush=True)
                answer = ERROR_FALLBACK

            state.turns.append({"role":"user","text":user_text,"speaker":speaker})
            state.turns.append({"role":"assistant","text":answer})
            if len(state.turns) > self.max_history * 2:
                del state.turns[:-self.max_history * 2]
            self.resolver.commit(state, meaning, speaker)
            print("generation path: v14_47_single_pass", flush=True)
            print("reply:", answer, flush=True)
            return answer


HashimotoArataBot = AgoHashimotoBot
