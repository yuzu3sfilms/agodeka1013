from __future__ import annotations

import os
import re
import threading
from collections import defaultdict

from openai import OpenAI

from ago_runtime import CorpusIndex, DialogueState, MeaningResolver, ConversationDynamics

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

PROJECT_VERSION = "v14.52"
ERROR_FALLBACK = "ｷｬﾋﾟｨ"


class AgoHashimotoBot:
    """Project AGO v14.52 — structure-grounded persona response core.

    Architecture: resolve once -> retrieve grounded evidence -> one generation.
    No candidate tournament, no downstream semantic re-guessing, no replay override.
    """

    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        self.client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
        self.corpus = CorpusIndex(roots=["data", "."])
        self.resolver = MeaningResolver(self.corpus)
        self.dynamics = ConversationDynamics()
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
            who = (t.get("speaker") or "相手") if t.get("role") == "user" else "橋本新"
            out.append(f"{who}: {t.get('text','')}")
        return "\n".join(out) or "なし"

    def _prompt(self, meaning, state, speaker):
        behavior = self.corpus.response_pattern_for_prompt(
            meaning.raw, meaning.stimulus_class, speaker, 6, meaning.stimulus_shape
        )
        persona = self.corpus.persona_for_prompt(
            meaning.raw, meaning.intent, 3, state.interaction_mode, behavior.get("response_modes")
        )
        pm = self.corpus.person_model_for_prompt(meaning.target_id, meaning.raw, 8) if meaning.target_id else None

        target_block = "なし"
        if meaning.target_id:
            target_block = f"target_id={meaning.target_id}\n呼び方={meaning.target_label}\n"
            if pm:
                target_block += (
                    f"人物モデル証拠強度={pm['evidence_strength']}\n"
                    f"直接会話数={pm['interaction_count']} / 直接言及数={pm['mention_count']}\n"
                    f"aliases={', '.join(pm['aliases']) or 'なし'}\n"
                    f"反復話題ヒント={', '.join(pm['recurring_terms']) or 'なし'}\n"
                )
                if pm['relationship_examples']:
                    target_block += "実際の相手別会話例:\n" + "\n".join(
                        f"相手: {x['other']}\n橋本新: {x['hashimoto']}" for x in pm['relationship_examples']
                    )
                if pm['direct_mentions']:
                    target_block += "\n橋本新本人による直接言及:\n" + "\n".join(f"- {x}" for x in pm['direct_mentions'])

        special = ""
        if meaning.intent == "self_state":
            special = "自己言及・変な問いも会話上のノリとして直接返す。哲学説明やAIの能力説明に変換しない。過去反応ペアの返し方を優先する。"
        elif meaning.intent == "person_opinion":
            special = "人物評価。人物モデルの証拠強度・相手別会話・直接言及から読み取れる範囲だけで答える。証拠が弱ければ断定を弱める。『好き』『嫌い』『どうでもいい』『微妙』を資料なしで創作しない。"
        elif meaning.intent == "subject_opinion":
            special = f"対象『{meaning.target_label}』への意見。人物辞書にない対象なので人物関係を捏造せず、橋本新の実ログ文体を使って普通に答える。"
        elif meaning.intent == "ambiguous_followup":
            special = "『どれ？』等だが直前に選択肢が確認できない。勝手にA/Bを作らず、『何が？』程度の自然な短い確認にする。"
        elif meaning.intent == "choice_followup":
            special = "直近会話に実在する選択肢だけを参照して答える。新しい選択肢を捏造しない。"

        system = """あなたはLINE上の橋本新を、実際の過去ログに基づいて再現するProject AGO。
便利AI、ChatGPT、カウンセラーとして振る舞わない。
現在の意味解析結果は上流で確定済み。人物・主語・述語を再解釈しない。
資料にない過去経験、好き嫌い、関係性、感情、予定を発明しない。

最重要なのは「何を説明すべきか」ではなく「橋本新ならこの刺激へどう返すか」。
stimulus→response実例の上位ほど強い行動アンカーとして扱い、内容ではなく返し方・短さ・間・温度を移す。
ユーザー文を言い換えてから答えない。質問を復唱しない。前置き・但し書き・一般論を足さない。
変な問い、自己言及、雑談も、必要以上に意味を深掘りせずLINEの一発言として返す。
実例が短い反応なら短く返し、実例が普通の説明なら必要な範囲だけ説明する。
全体人格例は語尾コピー用ではなく距離感・テンポの補助資料。無関係な固有名詞や話題は移さない。
通常1文、必要なら2文。候補一覧・解説・メタ説明は出さず返答本文だけ出す。"""

        user = f"""【確定した現在ターン】
intent={meaning.intent}
target={meaning.target_id or 'なし'}
predicate={meaning.predicate or 'なし'}
inherited_predicate={meaning.inherited_predicate}
stimulus_class={meaning.stimulus_class or 'なし'}
stimulus_shape={meaning.stimulus_shape or 'なし'}
user={meaning.raw}
speaker={speaker or '不明'}

【直近会話】
{self._history_text(state)}

【対象人物についての実ログ証拠】
{target_block}

【最優先：実ログから学習した stimulus → response 行動証拠】
stimulus_class={behavior['stimulus_class']}
stimulus_shape={behavior.get('stimulus_shape','なし')}
同クラス実例数={behavior['count']}
橋本の応答mode分布={behavior['response_modes']}
橋本の応答長中央値={behavior['median_response_length']}
類似する実際の反応ペア:
""" + "\n".join(
    f"- 相手: {x['stimulus']}\n  橋本新: {x['response']}" for x in behavior['examples']
) + f"""

【行動モデルの使い方】
上から順に強いアンカー。特にstimulus_shapeが同じ実例は、返答の構造・短さ・温度の第一根拠にする。
実例の話題・固有名詞・事実は現在へコピーしない。
意味解析・人物モデルと衝突した場合だけ、意味解析・人物モデルを優先する。
「質問だから質問で返す」のような機械的模倣はしない。ユーザー側の文法と橋本側の返答modeは別物。

【現在の会話人格状態】
interaction_mode={state.interaction_mode}
mode_strength={state.mode_strength}
mode_age={state.mode_age}
この状態は内容・事実を決めない。返答のテンポ、距離感、丁寧さ、ふざけ方だけに使う。

【橋本新の全体人格モデル（実ログから自動集計）】
発言数={persona['line_count']}
発言長中央値={persona['median_length']} / p75={persona['p75_length']}
短文率={persona['terse_rate']} / 丁寧形率={persona['polite_rate']} / 疑問形率={persona['question_rate']} / 笑い率={persona['laughter_rate']}
今回の会話行為に近い実発言例:
""" + "\n".join(f"- [{x['mode']}] {x['text']}" for x in persona['examples']) + f"""

【人格合成ルール】
1. 内容・対象・事実 = 確定意味解析と人物別実ログ。
2. 返し方・短さ・反応の型 = stimulus→response上位実例。
3. 距離感・丁寧さ・ふざけ方 = 持続中のAGO会話状態と全体人格モデル。
ユーザーの疑問符だけでAGOを質問調にしない。
上位実例が短い反応なら、説明を追加して“賢く”しない。
下流の証拠から上流の意味を変更しない。人物モデルにない好き嫌い・経験を捏造しない。

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
            speaker_changed = bool(state.last_partner and state.last_partner != speaker)
            self.dynamics.observe(state, user_text, speaker_changed=speaker_changed)
            if self._is_group(chat_id):
                called = bool(re.search(r"(?:あらくん|橋本|橋本新|顎|アゴ|AGODEKA)", user_text or "", re.I))
                previous = state.turns[-1] if state.turns else {}
                same_partner_continuation = previous.get("role") == "assistant" and state.last_partner and state.last_partner == speaker
                if not called and not same_partner_continuation:
                    meaning.should_reply = False
                    meaning.directed = False
            print("meaning:", meaning.__dict__, flush=True)
            if not meaning.should_reply:
                # Silence is still part of the conversation. Keep it so the next
                # speaker's ellipsis/follow-up sees what was actually said.
                state.turns.append({"role":"user","text":user_text,"speaker":speaker})
                if len(state.turns) > self.max_history * 2:
                    del state.turns[:-self.max_history * 2]
                print("generation path: v14_52_silence_context_kept", flush=True)
                return None

            system, user = self._prompt(meaning, state, speaker)
            try:
                res = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role":"system","content":system},{"role":"user","content":user}],
                    temperature=float(os.environ.get("TEMPERATURE", "0.58")),
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
            self.dynamics.after_reply(state, answer)
            print("conversation_mode:", {"mode": state.interaction_mode, "strength": state.mode_strength, "age": state.mode_age}, flush=True)
            print("generation path: v14_52_structure_grounded_single_pass", flush=True)
            print("reply:", answer, flush=True)
            return answer


HashimotoArataBot = AgoHashimotoBot
