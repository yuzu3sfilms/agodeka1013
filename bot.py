from __future__ import annotations

import os
import re
import threading
from collections import defaultdict

from openai import OpenAI

from ago_runtime import (
    PersonaArchive,
    DialogueState,
    MeaningResolver,
    ContractBuilder,
    PersonaGate,
)

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

PROJECT_VERSION = "v14.54"
ERROR_FALLBACK = "ｷｬﾋﾟｨ"


class AgoHashimotoBot:
    """Project AGO v14.54 — archive-native persona core.

    The model is not asked to invent Hashimoto's personality from a prompt.
    Real historical episodes and self-expression data determine the response
    contract first; the model only minimally edits those sources to fit the
    current turn. A post-generation gate rejects answers that drift too far.
    """

    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
        self.archive = PersonaArchive()
        self.resolver = MeaningResolver(self.archive)
        self.contracts = ContractBuilder(self.archive)
        self.states = defaultdict(DialogueState)
        self.locks = defaultdict(threading.RLock)
        self.shutdown_store = ShutdownStateStore()
        self.speaker_resolver = SpeakerResolver() if SpeakerResolver else None
        self.max_history = int(os.environ.get("AGO_HISTORY", "14"))
        meta = self.archive.source_meta
        print("bot_init:", {
            "version": PROJECT_VERSION,
            "raw_line_messages": (meta.get("line_raw") or {}).get("message_count"),
            "raw_episodes": len(self.archive.raw_episodes),
            "derived_context_episodes": len(self.archive.derived_episodes),
            "ai_dataset_statements": len(self.archive.self_statements),
            "hashimoto_utterances": len(self.archive.hashimoto_utterances),
        }, flush=True)

    def set_shutdown(self, chat_id: str, value: bool = True):
        self.shutdown_store.set(chat_id, bool(value))

    def is_shutdown(self, chat_id: str) -> bool:
        try:
            return bool(self.shutdown_store.get(chat_id))
        except Exception:
            return False

    @staticmethod
    def _is_group(chat_id: str) -> bool:
        return str(chat_id or "").startswith(("C", "R"))

    def _speaker(self, sender_id, display):
        if self.speaker_resolver:
            try:
                p = self.speaker_resolver.resolve(
                    sender_id=sender_id, display_name=display
                )
                return p.canonical_name or p.display_name or display or sender_id or ""
            except Exception:
                pass
        return display or sender_id or ""

    @staticmethod
    def _history_text(state: DialogueState) -> str:
        rows = []
        for t in state.turns[-8:]:
            who = (t.get("speaker") or "相手") if t.get("role") == "user" else "橋本新"
            rows.append(f"{who}: {t.get('text','')}")
        return "\n".join(rows) or "なし"

    @staticmethod
    def _episode_text(e: dict | None, label: str) -> str:
        if not e:
            return f"{label}: なし"
        ctx = []
        for t in e.get("context", [])[-5:]:
            who = "橋本新" if t.get("is_hashimoto") else t.get("sender", "相手")
            ctx.append(f"{who}: {t.get('text','')}")
        return (
            f"{label} [source={e.get('source')} id={e.get('id')}]\n"
            + "\n".join(ctx)
            + f"\n橋本新の実返答: {e.get('reply','')}"
        )

    def _build_prompt(self, contract, state: DialogueState, speaker: str):
        m = contract.meaning
        primary = self._episode_text(contract.primary, "PRIMARY")
        backups = "\n\n".join(
            self._episode_text(e, f"BACKUP{i+1}") for i, e in enumerate(contract.backups)
        ) or "なし"
        content = "\n".join(f"- {x}" for x in contract.content_sources[:6]) or "なし"

        # This prompt intentionally defines the model as an editor rather than a
        # persona actor. The persona already lives in the archive sources.
        system = """あなたはProject AGOの「最小編集器」です。人格を創作する役ではありません。
橋本新の人格・語彙・間・温度は、下に与える本人の実LINE返答と本人データセットだけが根拠です。

仕事は1つだけです。
PRIMARYの橋本新の実返答を、現在の会話に必要な最小限だけ編集して返してください。
PRIMARYが内容的に使えない場合だけBACKUPを使います。
人物・価値観については「本人発言の内容根拠」を優先します。

絶対禁止:
- ChatGPTらしく答え直す
- 丁寧で自然な日本語へ改善する
- ユーザーの質問を復唱してから答える
- 一般論、説明、但し書き、カウンセリングを足す
- 実資料にない好き嫌い・関係性・予定・経験・理由を作る
- 「それで何か〜するの？」「もう少し教えて」など会話を広げるためだけの質問を作る

橋本本人の変な語順、短さ、雑さ、妙な丁寧さ、記号、絵文字、言い回しは直さない。
原則としてPRIMARYの文型・長さ・テンポを保つ。
出力はLINEの返答本文だけ。解説、引用符、ラベルは出さない。"""

        intent_rule = ""
        if m.intent == "person_opinion":
            intent_rule = (
                "人物評価。本人発言の内容根拠から言える範囲だけ返す。"
                "感情ラベルを推測で追加しない。内容根拠が直接的でなくても、"
                "『わからない』というAI的逃げ方より、本人の実際の呼び方・距離感・反応を使う。"
            )
        elif m.intent == "self_state":
            intent_rule = (
                "自己言及の変な問い。哲学やAIの意識の説明をしない。"
                "PRIMARYが短い反応なら、その短い反応のまま返す。"
            )
        elif m.intent == "subject_opinion":
            intent_rule = (
                "抽象的な意見。本人データセットに該当する本人発言があれば、"
                "その考え方と言葉を優先し、一般論を作らない。"
            )
        elif m.intent == "ambiguous_followup":
            intent_rule = "直前に選択肢がなければ勝手に選択肢を作らない。短く聞き返す。"
        elif m.intent == "scheduling":
            intent_rule = "予定の会話。現在会話にある時刻だけを使う。新しい時刻や予定を作らない。"
        else:
            intent_rule = "現在の発言へ直接返す。会話を広げるためだけの質問を足さない。"

        user = f"""【現在の確定意味】
intent={m.intent}
target={m.target_id or 'なし'}
predicate={m.predicate or 'なし'}
act={m.act}
speaker={speaker or '不明'}
user={m.raw}

【直近の実会話】
{self._history_text(state)}

【PRIMARY: 最優先の実会話エピソード】
{primary}

【BACKUP: PRIMARYが内容的に不適切な時だけ】
{backups}

【本人発言の内容根拠】
{content}

【今回の編集制約】
{intent_rule}
目標文字数は約{contract.target_chars}文字。tone={contract.tone}。

PRIMARYの橋本新の返答を「別人が自然に書き直す」のではなく、橋本本人の文章を現在へ移植するつもりで最小編集してください。
返答本文だけ。"""
        return system, user

    @staticmethod
    def _clean(text: str) -> str:
        t = (text or "").strip()
        t = re.sub(r"^(?:REPLY|返答|回答)\s*[:：]\s*", "", t, flags=re.I)
        t = t.strip('"「」')
        return t[:300].strip()

    def _generate(self, contract, state, speaker):
        if contract.can_replay and contract.primary:
            answer = (contract.primary.get("reply") or "").strip()
            return answer, "archive_replay", "not_needed"

        system, user = self._build_prompt(contract, state, speaker)
        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=float(os.environ.get("TEMPERATURE", "0.18")),
                max_completion_tokens=int(os.environ.get("GROQ_MAX_COMPLETION_TOKENS", "120")),
                extra_body={"reasoning_effort": os.environ.get("GROQ_REASONING_EFFORT", "low")},
            )
            candidate = self._clean(res.choices[0].message.content or "")
        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            return contract.fallback or ERROR_FALLBACK, "archive_fallback", "groq_error"

        ok, reason = PersonaGate.validate(candidate, contract, contract.meaning.raw)
        if ok:
            return candidate, "minimal_edit", reason
        return contract.fallback or ERROR_FALLBACK, "archive_fallback", reason

    def reply(
        self,
        chat_id: str,
        user_text: str,
        sender_id: str | None = None,
        sender_display_name: str | None = None,
    ) -> str | None:
        with self.locks[chat_id]:
            if self.is_shutdown(chat_id):
                return None

            state = self.states[chat_id]
            speaker = self._speaker(sender_id, sender_display_name)
            meaning = self.resolver.resolve(
                user_text, state, speaker, self._is_group(chat_id)
            )
            print("meaning:", meaning.__dict__, flush=True)

            if not meaning.should_reply:
                state.turns.append({"role": "user", "text": user_text, "speaker": speaker})
                if len(state.turns) > self.max_history * 2:
                    del state.turns[:-self.max_history * 2]
                print("generation path: v14_54_archive_silence", flush=True)
                return None

            contract = self.contracts.build(meaning, state, speaker)
            dbg = contract.debug
            print("persona_contract:", {
                "confidence": contract.source_confidence,
                "tone": contract.tone,
                "target_chars": contract.target_chars,
                "can_replay": contract.can_replay,
                "top_hits": dbg.get("top_hits", [])[:3],
                "content_sources": dbg.get("content_sources", [])[:3],
            }, flush=True)

            answer, path, gate = self._generate(contract, state, speaker)
            answer = self._clean(answer) or ERROR_FALLBACK

            state.turns.append({"role": "user", "text": user_text, "speaker": speaker})
            state.turns.append({"role": "assistant", "text": answer})
            if len(state.turns) > self.max_history * 2:
                del state.turns[:-self.max_history * 2]
            self.resolver.commit(state, meaning, speaker)

            print("generation path:", f"v14_54_{path}", flush=True)
            print("persona_gate:", gate, flush=True)
            print("reply:", answer, flush=True)
            return answer


HashimotoArataBot = AgoHashimotoBot
