
# v14.37 — non-destructive surface guard.
# Persona should come from prompting + PersonaJudge, not from blind suffix rewriting.
_SURFACE_BAD_REWRITES = (
    ("と思いるわ", "と思います"),
    ("と思いる", "と思います"),
    ("ているわ", "ています"),
    ("てるわ", "てる"),
    ("不明だわ", "不明です"),
)

def _repair_surface_corruption(text: str) -> str:
    """Repair only clearly broken post-generation rewrites.

    This intentionally does NOT try to 'make text Hashimoto-like'.
    It only undoes mechanically corrupted forms produced downstream.
    """
    t = (text or "").strip()
    for bad, good in _SURFACE_BAD_REWRITES:
        t = t.replace(bad, good)

    # Mechanical polite->casual rewrites can create impossible hybrids.
    t = re.sub(r"思い(?:ます|ました)るわ", "思います", t)
    t = re.sub(r"でき(?:ます|ません)るわ", "できません", t)
    t = re.sub(r"あり(?:ます|ません)るわ", "ありません", t)

    # Never append a style tail after terminal polite forms.
    t = re.sub(r"(です|ます|ません|でした|ました)だわ$", r"\1", t)

    return t.strip()

import os
import random
import re
import time
import threading
from collections import defaultdict, deque

from openai import OpenAI
from dynamic_search import DynamicSearch
from relationship import RelationshipProfile
from relationship_evidence import RelationshipEvidenceIndex
from relevance import RelevanceRanker
from style_guard import guard_reply
from canon_answer import CanonAnswer
from persona_judge import PersonaJudge
from actual_reply_engine import ActualReplyEngine
from current_state_engine import CurrentStateEngine
from dialogue_manager import DialogueManager
from reply_policy import ReplyPolicy
from training_advisor import TrainingAdvisor
from ai_training_advisor import AITrainingAdvisor
from training_intent import contains_training_intent
from speaker_resolver import SpeakerResolver, SpeakerProfile
from shutdown_state import ShutdownStateStore
from utils import clean_reply, normalize, de_ai_tone
from project_identity import PROJECT_VERSION, runtime_label

ERROR_FALLBACK = "ｷｬﾋﾟｨ"
CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA"]
ATTENTION_ONLY_TERMS = {"ねえ", "ねぇ", "ちょっと", "おい", "あの", "なあ", "なぁ", "うん", "はい", "なるほど", "ふむ"}

WAKE_TERMS = [
    "顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA",
    "起きて", "おきて", "復活", "戻って", "相談", "筋トレ", "トレーニング",
]
WAKE_ONLY_TERMS = {
    "顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA",
    "起きて", "おきて", "復活", "戻って",
}


class AgoHashimotoBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "160"))
        self.groq_completion_tokens = int(os.environ.get("GROQ_MAX_COMPLETION_TOKENS", "512"))
        self.groq_reasoning_effort = os.environ.get("GROQ_REASONING_EFFORT", "low")
        self.temperature = float(os.environ.get("TEMPERATURE", "1.0"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "4"))
        self.cooldown_seconds = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
        self.groq_disabled_until = 0.0

        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
        self.searcher = DynamicSearch()
        self.relationships = RelationshipProfile()
        self.relationship_evidence = RelationshipEvidenceIndex()
        self.ranker = RelevanceRanker()
        self.canon_answer = CanonAnswer()
        self.persona_judge = PersonaJudge()
        self.replay_engine = ActualReplyEngine()
        self.current_state = CurrentStateEngine()
        self.reply_policy = ReplyPolicy()
        self.training_advisor = TrainingAdvisor()
        self.ai_training_advisor = AITrainingAdvisor(
            client=self.client,
            model=self.model,
            memory=self.training_advisor.memory,
        )
        self.speaker_resolver = SpeakerResolver()

        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.dialogue = DialogueManager(max_turns=max(8, self.history_len * 2 + 2))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))
        self.last_reply_at = defaultdict(float)
        self.last_topic_terms = defaultdict(list)
        self.behavior_modes = defaultdict(lambda: "ordinary_direct")
        # v14.44: narrowly scoped conversation mode for chained person-opinion questions.
        # This is deliberately separate from the general topic stack so that
        # 「村田は？」「せっきー」 can inherit "どう思ってる？" without making
        # unrelated ellipsis inherit arbitrary old predicates.
        self.person_opinion_chain = defaultdict(bool)
        self.seen_chats = set()
        self.shutdown_store = ShutdownStateStore()
        # v14.45: one in-flight turn per chat. LINE can deliver rapid messages on
        # separate request threads; shared history/ellipsis state must never interleave.
        self.chat_locks = defaultdict(threading.RLock)
        # v14.46: conversation ownership. In a group, a follow-up belongs to AGO
        # only when AGO was actually talking to the same sender, or AGO is called
        # explicitly. This prevents unrelated group chatter from entering the
        # continuity route just because it is short/elliptical.
        self.last_ago_partner = defaultdict(str)
        self.pending_turn_partner = defaultdict(str)

        self.continuity_seconds = int(os.environ.get("CONTINUITY_SECONDS", "420"))
        self.continuity_min_history = int(os.environ.get("CONTINUITY_MIN_HISTORY", "1"))
        self.continuity_probability = float(os.environ.get("CONTINUITY_REPLY_PROBABILITY", "0.75"))

        # v14.27 spontaneous participation.
        # This affects only undirected group/room conversation. Direct calls,
        # questions, follow-ups and training consultations keep their normal route.
        self.spontaneous_enabled = os.environ.get(
            "SPONTANEOUS_PARTICIPATION_ENABLED", "1"
        ).lower() not in {"0", "false", "off", "no"}
        self.spontaneous_base_probability = float(
            os.environ.get("SPONTANEOUS_BASE_PROBABILITY", "0.08")
        )
        self.spontaneous_max_probability = float(
            os.environ.get("SPONTANEOUS_MAX_PROBABILITY", "0.58")
        )
        self.spontaneous_min_replay_score = int(
            os.environ.get("SPONTANEOUS_MIN_REPLAY_SCORE", "145")
        )
        self.spontaneous_cooldown_seconds = int(
            os.environ.get("SPONTANEOUS_COOLDOWN_SECONDS", "240")
        )
        self.spontaneous_min_history = int(
            os.environ.get("SPONTANEOUS_MIN_HISTORY", "2")
        )

        print(
            "bot_init:",
            f"version={PROJECT_VERSION}",
            f"persona_judge={hasattr(self, 'persona_judge')}",
            f"persona_profile_loaded={bool(getattr(self.persona_judge, 'profile', None))}",
            f"topic_canon_loaded={bool(getattr(self.persona_judge, 'topic_canon', None))}",
            f"replay_scenes={len(getattr(self.replay_engine, 'scenes', []))}",
            "policy=True",
            "training=True",
            f"spontaneous={self.spontaneous_enabled}",
            f"groq_reasoning={self.groq_reasoning_effort}",
            f"groq_max_completion_tokens={self.groq_completion_tokens}",
            flush=True,
        )

    def set_shutdown(self, chat_id: str, value: bool = True):
        self.shutdown_store.set(chat_id, bool(value))
        print("shutdown_state_set:", chat_id, bool(value), "store=sqlite", flush=True)

    def is_shutdown(self, chat_id: str) -> bool:
        value = self.shutdown_store.get(chat_id)
        print("shutdown_state_get:", chat_id, value, "store=sqlite", flush=True)
        return value

    def is_wake_only(self, text: str) -> bool:
        stripped = (text or "").strip()
        normalized = normalize(stripped)
        if not stripped:
            return False
        if stripped in WAKE_ONLY_TERMS or normalized in {normalize(x) for x in WAKE_ONLY_TERMS}:
            return True
        if len(stripped) <= 8 and any(term in stripped for term in CALL_TERMS):
            return True
        return False

    def should_wake_from_shutdown(self, text: str):
        """Wake on the first substantive message and process that same message."""
        t = (text or "").strip()
        if not t:
            return False, "empty_message"
        if self.current_state.stopped(t):
            return False, "explicit_stop"
        return True, "first_substantive_message"

    def _explicit_person_opinion_question(self, text: str) -> bool:
        t = (text or "").strip()
        return bool(re.search(r"(?:のこと|について|って)?\s*(?:どう思(?:ってる|う)|どう感じる|好き(?:なの)?|嫌い(?:なの)?)", t))

    def _short_person_subject(self, text: str):
        """Return a raw person token only for genuinely short person-only follow-ups."""
        t = (text or "").strip()
        if not t or len(t) > 24:
            return None
        # Remove only discourse/relationship-question particles, never arbitrary words.
        t = re.sub(r"^(?:じゃあ|じゃ|なら|で、|で)?\s*", "", t)
        t = re.sub(r"[？?。！!]+$", "", t).strip()
        t = re.sub(r"(?:のこと)?(?:は|って)$", "", t).strip()
        if not t or re.search(r"(?:何|なに|どう|なんで|なぜ|いつ|どこ|誰|だれ|これ|それ|あれ)$", t):
            return None
        resolved = self.relationship_evidence.resolve_alias(t)
        return t if resolved else None

    def _semantic_user_text(
        self, chat_id: str, user_text: str, partner_key: str = ""
    ):
        """Expand person-opinion ellipsis only within the same speaker's chain."""
        t = (user_text or "").strip()
        chain_key = (chat_id, partner_key or "__unknown__")
        explicit = self._explicit_person_opinion_question(t)
        if explicit:
            self.person_opinion_chain[chain_key] = True
            return t, {"expanded": False, "reason": "explicit_person_opinion"}

        subject = self._short_person_subject(t)
        if self.person_opinion_chain[chain_key] and subject:
            expanded = f"{subject}のことどう思ってる？"
            return expanded, {
                "expanded": True,
                "reason": "person_opinion_chain",
                "original": t,
                "expanded_text": expanded,
            }

        # A normal substantive turn ends this narrow inheritance mode.
        if t and not re.fullmatch(r"(?:うん|はい|へえ|ほう|なるほど|草|笑|ｗ+|w+)", t, re.I):
            self.person_opinion_chain[chain_key] = False
        return t, {"expanded": False, "reason": "no_person_opinion_inheritance"}

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)
        self.dialogue.add(chat_id, "user", text)

    def remember_bot(self, chat_id: str, text: str):
        if text:
            self.last_bot_replies[chat_id].append(text)
            self.dialogue.add(chat_id, "assistant", text)
            self.last_reply_at[chat_id] = time.time()

    def context(self, chat_id: str, user_text: str) -> str:
        return self.dialogue.context(chat_id, current_user_text=user_text, limit=8)

    def finish(self, chat_id: str, user_text: str, answer: str | None) -> str | None:
        """All routes update history; only real AGO replies establish ownership."""
        self.remember_user(chat_id, user_text)
        if answer:
            self.remember_bot(chat_id, answer)
            partner = self.pending_turn_partner.get(chat_id, "")
            if partner:
                self.last_ago_partner[chat_id] = partner
        return answer

    @staticmethod
    def _partner_key(sender_id: str | None, sender_display_name: str | None) -> str:
        return (sender_id or "").strip() or (sender_display_name or "").strip()

    def _turn_directed_to_ago(
        self,
        chat_id: str,
        user_text: str,
        sender_id: str | None,
        sender_display_name: str | None,
        relation: dict | None = None,
    ) -> tuple[bool, str]:
        """Resolve conversational ownership before continuity/generation.

        DM turns are directed by definition. In groups/rooms, ordinary chatter is
        not directed to AGO merely because it is a question or an ellipsis.
        Ownership requires an explicit call or an active same-speaker exchange
        after a real AGO reply.
        """
        if not self._is_group_or_room(chat_id):
            return True, "direct_message"
        if self.called_directly(user_text):
            return True, "explicit_call"

        partner = self._partner_key(sender_id, sender_display_name)
        if (
            partner
            and partner == self.last_ago_partner.get(chat_id, "")
            and self.is_conversation_continuing(chat_id)
        ):
            rel = (relation or {}).get("relation", "")
            if rel in {"followup", "continuation_request", "repair_request"}:
                return True, "same_partner_followup"
            if self.is_question(user_text):
                return True, "same_partner_question"

        return False, "undirected_group_turn"

    def _continuity_owned(
        self,
        chat_id: str,
        relation: dict,
        directed_to_ago: bool,
    ) -> bool:
        if relation.get("relation") not in {
            "repair_request", "followup", "continuation_request"
        }:
            return False
        if not self._is_group_or_room(chat_id):
            return True
        return bool(directed_to_ago)

    def continuity_prompt(self, user_text: str, chat_id: str, relation: dict, speaker: SpeakerProfile):
        history = self.dialogue.context(chat_id, current_user_text=user_text, limit=8)
        behavior = self.persona_judge.infer_behavior_state(
            user_text=user_text,
            context=history,
            search_result={},
            relation=relation,
            previous_mode=self.behavior_modes[chat_id],
        )
        self.behavior_modes[chat_id] = behavior["mode"]
        persona_guidance = self.persona_judge.generation_guidance(
            user_text,
            speaker.canonical_name,
            behavior,
        )
        relationship_evidence = self.relationship_evidence.evidence(
            user_text=user_text,
            behavior=behavior,
            current_speaker=speaker.canonical_name,
            relationship_policy=(getattr(self.persona_judge.persona_policy, "profile", {}) or {}).get("relationship_policy", {}),
            person_context=relation.get("person_context") or {},
        )
        relationship_evidence_block = self.relationship_evidence.format(relationship_evidence)
        system = (
            "橋本新本人風のAIアカウントとして、直前の会話につながる返答をする。"
            "現在の発言を単独の検索語として扱わず、直前のassistant発言とuser発言を最優先する。"
            "『え？』『何それ？』『どういうこと？』は直前回答への訂正・説明要求として処理する。"
            "自分の直前回答に誤字、造語、矛盾、存在しない用語があれば、ごまかさず訂正する。"
            "知らない言葉をもっともらしく定義しない。"
            "話題を勝手に古いトピックへ戻さない。"
            "最優先は現在の橋本行動状態。短文・長文・丁寧語・聞き返しを固定しない。"
            "一人称も固定しない。必要がないなら省略し、必要なら文脈に自然なものだけ使う。"
            "候補を4つ出す。"
        )
        user = f"""会話関係:{relation.get('relation')}
判定理由:{relation.get('reason')}
会話:
{history}

相手情報:
{speaker.prompt_block()}

過去ログ統計:
{persona_guidance}

人物関係資料:
{relationship_evidence_block}

人物関係資料がある対象では、その人物IDと実ログを優先する。別名の意味を聞き返さず、資料があるのに「分からない」「微妙」「別に」だけで逃げない。

直前の流れに自然につながる返答候補を4つ。
候補1: ...
候補2: ...
候補3: ...
候補4: ..."""
        return system, user

    def should_inherit_topic(self, chat_id: str, user_text: str, raw_result: dict) -> bool:
        stripped = (user_text or "").strip()
        if stripped in ATTENTION_ONLY_TERMS:
            return False
        if raw_result.get("topic_terms"):
            return False
        if not self.last_topic_terms[chat_id]:
            return False
        if self.is_question(user_text):
            return True
        return False

    def remember_topics(self, chat_id: str, result: dict):
        topics = result.get("topic_terms", []) or []
        if topics:
            self.last_topic_terms[chat_id] = topics[:4]

    def called_directly(self, user_text: str) -> bool:
        nt = normalize(user_text)
        return any(normalize(t) in nt for t in CALL_TERMS)

    def is_question(self, user_text: str) -> bool:
        return bool(re.search(
            r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|使う|作って|なの|の？|の\?",
            user_text,
        ))

    def is_conversation_continuing(self, chat_id: str) -> bool:
        if len(self.histories[chat_id]) < self.continuity_min_history:
            return False
        last = self.last_reply_at[chat_id]
        if not last:
            return False
        return (time.time() - last) <= self.continuity_seconds

    def should_continue_reply(self, chat_id: str, user_text: str, called: bool, question: bool) -> bool:
        if called:
            return True
        if question and self.is_conversation_continuing(chat_id):
            return True
        if not self.is_conversation_continuing(chat_id):
            return False
        seed = hash((chat_id, user_text, int(time.time() // 60)))
        rng = random.Random(seed)
        return rng.random() < self.continuity_probability

    def _is_group_or_room(self, chat_id: str) -> bool:
        # LINE group IDs start with C, multi-person room IDs with R,
        # one-to-one user IDs with U.
        return bool(chat_id) and chat_id[:1] in {"C", "R"}

    def _spontaneous_gate(
        self,
        chat_id: str,
        user_text: str,
        state: dict,
        result: dict,
        context: str,
        speaker: SpeakerProfile,
        dialogue_relation: dict,
        is_first_message: bool,
        directed_to_ago: bool = False,
    ) -> dict:
        """
        Decide whether AGO joins an undirected group conversation.

        The decision uses general evidence, not topic-specific hardcoding:
        - actual historical Replay strength
        - retrieval relevance
        - conversation activity
        - partner/scene continuity already included in Replay score
        - cooldown since AGO last spoke
        - stochastic participation probability

        If this method says gate=True, normal automatic reply routing is replaced
        by this decision for that undirected group turn.
        """
        base = {
            "gate": False,
            "participate": False,
            "reason": "",
            "probability": 0.0,
            "roll": None,
            "participation_score": 0.0,
            "replay": None,
            "replay_info": None,
        }

        if not self._is_group_or_room(chat_id):
            return {**base, "reason": "not_group"}
        if directed_to_ago:
            return {**base, "reason": "directed_to_ago"}

        # Every undirected group/room turn is owned by this gate even when
        # spontaneous participation is disabled. Otherwise disabling spontaneous
        # mode accidentally falls through to normal automatic reply routing.
        base["gate"] = True
        if not self.spontaneous_enabled:
            return {**base, "reason": "disabled_undirected_group"}

        # Questions, ellipses and first observed messages are not direct merely
        # because they look reply-worthy.
        if is_first_message:
            return {**base, "reason": "undirected_first_message"}
        if dialogue_relation.get("relation") in {
            "followup", "continuation_request", "repair_request"
        }:
            return {**base, "reason": "unowned_followup"}
        if len(self.histories[chat_id]) < self.spontaneous_min_history:
            return {**base, "reason": "not_enough_group_history"}

        since_last = time.time() - self.last_reply_at[chat_id] if self.last_reply_at[chat_id] else 10**9
        if since_last < self.spontaneous_cooldown_seconds:
            return {
                **base,
                "reason": "cooldown",
                "cooldown_remaining": round(self.spontaneous_cooldown_seconds - since_last, 1),
            }

        replay, replay_info = self.replay_engine.choose(
            user_text=user_text,
            context=context,
            topic_terms=result.get("topic_terms", []),
            context_topic_terms=[],
            intent=state.get("intent", ""),
            current_speaker=speaker.canonical_name,
        )
        replay, replay_info = self.persona_judge.select_replay(
            replay=replay,
            replay_info=replay_info,
            user_text=user_text,
            behavior=state.get("hashimoto_behavior")
                or result.get("hashimoto_behavior")
                or {"mode": state.get("hashimoto_mode", "ordinary_direct")},
        )
        base["replay"] = replay
        base["replay_info"] = replay_info

        if not replay or not replay_info.get("chosen"):
            return {**base, "reason": "no_grounded_replay"}

        replay_score = float(replay_info["chosen"].get("score", 0))
        if replay_score < self.spontaneous_min_replay_score:
            return {
                **base,
                "reason": "replay_too_weak",
                "replay_score": replay_score,
            }

        relevance_scores = [
            float(x) for x in (result.get("relevance_scores", []) or [])
            if isinstance(x, (int, float))
        ]
        relevance = max(relevance_scores, default=0.0)

        # Normalize multiple independent signals. Replay score already contains
        # same-partner and scene-continuity bonuses from ActualReplyEngine.
        replay_strength = min(1.0, max(
            0.0,
            (replay_score - self.spontaneous_min_replay_score) / 140.0,
        ))
        relevance_strength = min(1.0, relevance / 150.0)
        activity_strength = min(
            1.0,
            len(self.histories[chat_id]) / max(4.0, float(self.history_len)),
        )

        participation_score = (
            replay_strength * 0.55
            + relevance_strength * 0.25
            + activity_strength * 0.20
        )

        probability = self.spontaneous_base_probability + participation_score * 0.50
        probability = min(self.spontaneous_max_probability, max(0.0, probability))

        roll = random.SystemRandom().random()
        participate = roll < probability

        return {
            **base,
            "participate": participate,
            "reason": "roll_pass" if participate else "roll_silence",
            "probability": round(probability, 4),
            "roll": round(roll, 4),
            "participation_score": round(participation_score, 4),
            "replay_score": replay_score,
            "relevance": relevance,
        }

    def fallback_prompt(self, user_text: str, context: str, chat_id: str, question: bool, speaker: SpeakerProfile, person_context: dict | None = None):
        relation_style = "\n".join(self.relationships.style_samples(n=4))
        behavior = self.persona_judge.infer_behavior_state(
            user_text=user_text,
            context=context,
            search_result={},
            relation={"person_context": person_context or {}},
            previous_mode=self.behavior_modes[chat_id],
        )
        persona_guidance = self.persona_judge.generation_guidance(
            user_text,
            speaker.canonical_name,
            behavior,
        )
        relationship_evidence = self.relationship_evidence.evidence(
            user_text=user_text,
            behavior=behavior,
            current_speaker=speaker.canonical_name,
            relationship_policy=(getattr(self.persona_judge.persona_policy, "profile", {}) or {}).get("relationship_policy", {}),
            person_context=person_context or {},
        )
        relationship_evidence_block = self.relationship_evidence.format(relationship_evidence)
        system = (
            "橋本新本人風のAIアカウントとしてLINEで返す。"
            "グループ内では「あらくん」「橋本」「顎」「AGODEKA」と呼ばれる同一人物。"
            "説明AI・自己説明はしない。"
            "過去ログに根拠がない具体的な記憶や設定は作らない。"
            "短さや語尾を人格の代用品にしない。"
            "現在の橋本行動状態に従い、確認が必要なら聞き、説明状態なら長くなってよく、"
            "普通の会話では普通に答える。丁寧語も必要なら自然に使う。"
            "人物への意見質問では人物関係資料を優先し、実際の会話量・距離感・反応様式を使う。"
            "人物関係資料があっても、記録にない好き嫌い・内面評価は作らない。"
            "関係資料が十分ある相手に、根拠なく『分からない』『別に』『微妙』だけで逃げない。"
            "Opinion Evidenceがnoneでも人物関係資料がある場合は、低コミットメント逃避より実ログの具体情報を優先する。"
        )
        user = f"""mode:{'Q' if question else 'continue'}
発言:{user_text}
直近:{context}
相手情報:
{speaker.prompt_block()}

過去ログ統計:
{persona_guidance}

人物関係資料:
{relationship_evidence_block}

口調サンプル:
{relation_style}

過去ログに強い関連がない時の、会話継続用の短い返答候補を4つ。
候補1: ...
候補2: ...
候補3: ...
候補4: ..."""
        return system, user

    def remove_unverified_vocative(self, text: str, speaker: SpeakerProfile) -> str:
        out = (text or "").strip()
        labels = [
            speaker.address,
            speaker.canonical_name,
            speaker.display_name,
            *speaker.aliases,
        ]
        for label in sorted(
            {x.strip() for x in labels if x and x.strip()},
            key=len,
            reverse=True,
        ):
            out = re.sub(
                rf"^(?:{re.escape(label)})(?:さん|くん|君)?[、,\s]+",
                "",
                out,
            ).strip()
        return out

    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def completion_text(self, response, label: str = "groq") -> str:
        """Log Groq token use and return only complete candidate text."""
        choice = response.choices[0]
        message = choice.message
        raw = message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)

        usage = getattr(response, "usage", None)
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        reasoning_tokens = getattr(details, "reasoning_tokens", None) if details else None
        reasoning = getattr(message, "reasoning", None)
        print(
            f"{label}_usage:",
            {
                "model": self.model,
                "finish_reason": finish_reason,
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
                "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else None,
                "content_chars": len(raw),
                "reasoning_effort": self.groq_reasoning_effort,
                "max_completion_tokens": self.groq_completion_tokens,
            },
            flush=True,
        )

        if finish_reason == "length":
            lines = raw.splitlines()
            nonempty = [line for line in lines if line.strip()]
            if len(nonempty) >= 2:
                dropped = nonempty[-1]
                raw = "\n".join(nonempty[:-1])
                print(
                    f"{label}_truncation_guard:",
                    {
                        "finish_reason": "length",
                        "dropped_last_line": dropped,
                        "kept_lines": len(nonempty) - 1,
                    },
                    flush=True,
                )
            else:
                print(
                    f"{label}_truncation_guard:",
                    {
                        "finish_reason": "length",
                        "dropped_all": True,
                    },
                    flush=True,
                )
                raw = ""
        return raw

    def build_prompt(self, user_text: str, context: str, search_result: dict, chat_id: str, speaker: SpeakerProfile):
        episode_block = self.searcher.format_episodes(search_result)
        style_from_episode = self.searcher.format_style(search_result)
        relation_block = self.relationships.format()
        relation_style = "\n".join(
            f"- {x}" for x in self.relationships.style_samples(6)
        )
        terms = ", ".join(search_result.get("terms", [])[:8])
        topic_terms = ", ".join(search_result.get("topic_terms", [])[:8])
        predicates = ", ".join(search_result.get("predicates", [])[:8])
        rel = ", ".join(str(x) for x in search_result.get("relevance_scores", []))
        reasons = str(search_result.get("relevance_reasons", []))[:300]
        recent = "\n".join(context.splitlines()[-2:])
        question = self.is_question(user_text)
        behavior = search_result.get("hashimoto_behavior") or self.persona_judge.infer_behavior_state(
            user_text=user_text,
            context=context,
            search_result=search_result,
            relation={},
            previous_mode=self.behavior_modes[chat_id],
        )
        persona_guidance = self.persona_judge.generation_guidance(
            user_text,
            speaker.canonical_name,
            behavior,
        )
        relationship_evidence = search_result.get("relationship_evidence") or self.relationship_evidence.evidence(
            user_text=user_text,
            behavior=behavior,
            current_speaker=speaker.canonical_name,
            relationship_policy=(getattr(self.persona_judge.persona_policy, "profile", {}) or {}).get("relationship_policy", {}),
            person_context=search_result.get("person_context") or {},
        )
        relationship_evidence_block = self.relationship_evidence.format(relationship_evidence)
        system = (
            "あなたは橋本新本人風のAIアカウント。ただしこれは最後の保険生成。過去ログ実返答が使えない時だけ使われる。"
            "グループ内では「あらくん」「橋本」「顎」「AGODEKA」と呼ばれる同一人物として返す。"
            "呼ばれたら自分のこととして反応する。"
            "説明AI・自己説明は禁止。"
            "一人称は固定しない。必要な時だけ自然に使い、不要なら省略する。"
            "質問にはまず内容として答える。ただし知識説明状態では必要なだけ詳しくてよい。"
            "過去ログの役割を厳密に分ける。実際の過去発言をそのまま使う仕事はReplayエンジンが担当する。"
            "この生成ルートでは、過去ログは口調・反応の速さ・温度感・関係性の参考にだけ使う。"
            "検索エピソードに出た人物名、固有名詞、出来事、噂、発言内容を、新しい質問への事実根拠として持ち込まない。"
            "現在の発言に書かれていない過去ログ固有情報を、知っている事実のように言わない。"
            "質問には現在の質問そのものへ短く答える。人格は口調と反応様式で出す。"
            "4候補すべて、まず質問内容への有効な答えにする。"
            "Question Semanticsを最初に満たす。質問に答えていない候補は橋本らしくても作らない。"
            "Reality/Canonを次に優先する。人格を演じるためにAGO自身の自我・感情・意識・記憶などの事実を捏造しない。"
            "質問対象がAGO自身なら、ユーザー側へ質問を反転しない。Realityを守ったうえで自分についてまず答える。"
            "現在のStanceがpersonal_hunchなら、証拠や一般論の解説より先に本人としての傾きを出す。"
            "現在のStanceがpersonal_evaluationなら、抽象論ではなく本人の評価・感想として答える。"
            "Opinion Evidenceがnoneなら、対象への強い好き嫌い・怖さ・面白さを橋本の新しい価値観として捏造しない。"
            "ただし人物関係資料がある対象では『別に・分からない・微妙』を優先せず、本人の実発言と実会話から具体的に言える範囲を答える。"
            "Opinion Evidenceがdirectなら、その方向と過去発言の範囲を守る。"
            "人物への評価質問では人物関係資料を使う。対象人物との実際の隣接会話・行動傾向から距離感と反応様式を再現する。"
            "人物関係資料は好き嫌いを自動推定する許可ではない。記録にない内面評価は捏造しない。"
            "価値判断は多様性・創造力・人間性などのLLM的な総論へ逃げず、具体的に返す。"
            "次に現在の橋本行動状態に合わせ、最後に口調統計を表現調整として使う。"
            "生成後に敬語や語尾を機械的に橋本風へ置換しない。文法的に自然な原文を優先する。"
            "質問への返答は単独で意味が通る文にする。前提のない『そうだ』『そんな感じ』で逃げない。"
            "意見を聞かれた場合、過去ログに直接の意見がなくても、架空の経験を作らない範囲で本人として普通に評価を返す。"
            "短さ・丁寧語・語録そのものを人格だと誤認しない。"
            "明確な根拠がない個人的記憶や他人の発言を捏造しない。"
            "語尾でキャラを作らない。"
            "文数や長さは現在の行動状態に従う。丁寧語を禁止しない。"
            "過度な罵倒や、本人ログに根拠のない攻撃性は足さない。"
        )
        user = f"""mode:{'Q' if question else 'react'}
発言:{user_text}

相手情報:
{speaker.prompt_block()}

語:{terms}
本題語:{topic_terms}
述語:{predicates}
関連度:{rel}
採用理由:{reasons}
直近:{recent}

過去ログ統計:
{persona_guidance}

Reality / Canon:
{behavior.get("reality", {})}

現在の橋本行動状態:
{behavior.get("mode", "ordinary_direct")}

現在の橋本Stance:
{behavior.get("stance", {})}

橋本の価値判断の型:
{behavior.get("value_orientation", {})}

Question Semantics:
{behavior.get("question_semantics", {})}

Opinion Evidence:
{behavior.get("opinion_evidence", {})}

人物関係資料:
{relationship_evidence_block}

過去ログ:
{episode_block}

関係:
{relation_block}

口調:
{style_from_episode}
{relation_style}

厳守:
- ReplayとGenerationを混同しない。
- 過去ログ本文を新しい回答の事実ソースとして引用・再構成しない。
- 現在の発言にない人物名・固有名詞・出来事を、検索エピソードから持ち込まない。
- 「誰かが言ってた」「前にこういう話があった」「みんなで話してる」等を、現在の会話に根拠がないのに作らない。
- 過去ログから借りるのは会話行動・距離感・言葉の自然さ。
- 人物関係資料に観測シグナルがある人物評価では、「微妙」「別に」「まあかな」だけの汎用評価に逃げず、観測されたやり取りの特徴を少なくとも1つ内容に反映する。
- 観測シグナルは行動の事実として使い、そこから「好き」「嫌い」など未記録の内面を捏造しない。
- 現在の質問そのものにまず答える。
- 現在の橋本行動状態を最優先し、長さは固定しない。
- 根拠が薄い事実は作らない。
- 綺麗に整えすぎたAI文体にしない。

出力形式:
候補1: ...
候補2: ...
候補3: ...
候補4: ...

橋本新として、現在の行動状態に合う候補を4つ出す。"""
        return system, user

    def reply(
        self,
        chat_id: str,
        user_text: str,
        sender_id: str | None = None,
        sender_display_name: str | None = None,
    ) -> str | None:
        """Serialize the complete stateful turn per chat."""
        with self.chat_locks[chat_id]:
            return self._reply_unlocked(
                chat_id, user_text, sender_id=sender_id,
                sender_display_name=sender_display_name,
            )

    def _reply_unlocked(
        self,
        chat_id: str,
        user_text: str,
        sender_id: str | None = None,
        sender_display_name: str | None = None,
    ) -> str | None:
        is_first_message = chat_id not in self.seen_chats
        self.seen_chats.add(chat_id)
        self.pending_turn_partner[chat_id] = self._partner_key(
            sender_id, sender_display_name
        )

        context = self.context(chat_id, user_text)
        print(
            "conversation_entry:",
            {
                "is_first_message": is_first_message,
                "history_size": len(self.histories[chat_id]),
            },
            flush=True,
        )

        speaker = self.speaker_resolver.resolve(
            sender_id=sender_id,
            display_name=sender_display_name,
        )
        print(
            "speaker_resolution:",
            {
                "canonical": speaker.canonical_name,
                "display": speaker.display_name,
                "address": speaker.address,
                "confidence": speaker.confidence,
                "source": speaker.source,
            },
            flush=True,
        )

        semantic_user_text, semantic_resolution = self._semantic_user_text(
            chat_id, user_text, self.pending_turn_partner.get(chat_id, "")
        )
        print("semantic_resolution:", semantic_resolution, flush=True)

        # v14.45 canonical person context is resolved BEFORE dialogue/search.
        # Every downstream layer receives this same person_id instead of re-guessing aliases.
        person_context = self.relationship_evidence.resolve_context(
            semantic_user_text, current_speaker=speaker.canonical_name
        )
        search_user_text = self.relationship_evidence.search_text(
            semantic_user_text, person_context
        )
        print("person_context:", person_context, flush=True)
        print("person_search_text:", search_user_text, flush=True)

        dialogue_relation = self.dialogue.classify(chat_id, semantic_user_text)
        dialogue_relation["person_context"] = person_context
        if person_context.get("used") and person_context.get("kind") != "user_self":
            dialogue_relation["resolved_subject"] = person_context.get("canonical", "")
            dialogue_relation["subject_inherited"] = False
        print("dialogue_relation:", dialogue_relation, flush=True)
        directed_to_ago, directed_reason = self._turn_directed_to_ago(
            chat_id,
            semantic_user_text,
            sender_id,
            sender_display_name,
            dialogue_relation,
        )
        dialogue_relation["directed_to_ago"] = directed_to_ago
        dialogue_relation["directed_reason"] = directed_reason
        print(
            "conversation_ownership:",
            {
                "directed_to_ago": directed_to_ago,
                "reason": directed_reason,
                "partner": self.pending_turn_partner.get(chat_id, ""),
                "last_ago_partner": self.last_ago_partner.get(chat_id, ""),
            },
            flush=True,
        )

        if self.is_shutdown(chat_id):
            if self._is_group_or_room(chat_id) and not directed_to_ago:
                print("generation path: shutdown_undirected_group_silence", flush=True)
                return self.finish(chat_id, user_text, None)
            wake, reason = self.should_wake_from_shutdown(user_text)
            print(
                "shutdown_state:",
                True,
                "wake_check:",
                wake,
                f"reason={reason}",
                flush=True,
            )
            if not wake:
                print("generation path: shutdown_silence", flush=True)
                return self.finish(chat_id, user_text, None)

            self.set_shutdown(chat_id, False)
            print(
                "shutdown_state:",
                False,
                "wake_consumed_first_message:",
                False,
                flush=True,
            )
            if self.is_wake_only(user_text):
                answer = "あはい"
                print("generation path: wake_v14_11_short_ack", flush=True)
                return self.finish(chat_id, user_text, answer)

        training_context = self.training_advisor._context(chat_id)
        training_context = dict(training_context or {})
        training_context["speaker_instruction"] = speaker.prompt_block()
        training_context["dialogue_relation"] = dialogue_relation
        training_context["recent_dialogue"] = self.dialogue.context(
            chat_id,
            limit=6,
        )
        training = self.ai_training_advisor.answer(
            chat_id,
            user_text,
            context=training_context,
        )
        print(
            "ai_training_advisor:",
            {k: v for k, v in training.items() if k != "answer"},
            flush=True,
        )
        if training.get("used") and (
            not self._is_group_or_room(chat_id) or directed_to_ago
        ):
            answer = training["answer"]
            intent = training.get("intent") or {}
            if intent.get("intent") == "log_workout":
                self.training_advisor.memory.add(chat_id, user_text)
            self.training_advisor._remember_context(
                chat_id,
                intent,
                answer,
            )
            print(
                f"generation path: training_v14_11_{training.get('kind', 'advisor')}",
                flush=True,
            )
            return self.finish(chat_id, user_text, answer)
        elif training.get("used"):
            print(
                "training_advisor_skip: undirected_group_turn",
                flush=True,
            )

        if self._continuity_owned(
            chat_id, dialogue_relation, directed_to_ago
        ):
            if self.groq_available():
                try:
                    system, user = self.continuity_prompt(
                        semantic_user_text,
                        chat_id,
                        dialogue_relation,
                        speaker,
                    )
                    res = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=min(self.temperature, 0.65),
                        max_completion_tokens=max(self.groq_completion_tokens, 384),
                        extra_body={"reasoning_effort": self.groq_reasoning_effort},
                    )
                    raw = self.completion_text(res, "continuity_groq")
                    raw = _repair_surface_corruption(raw)
                    print("continuity_groq_raw:", raw, flush=True)
                    candidates = self.persona_judge.split_candidates(raw)
                    cleaned = []
                    for cand in candidates:
                        cand = self.remove_unverified_vocative(
                            clean_reply(semantic_user_text, cand),
                            speaker,
                        )
                        cand = _repair_surface_corruption(cand)
                        if cand:
                            cleaned.append(cand)
                    chosen, judge_info = self.persona_judge.choose(
                        cleaned,
                        semantic_user_text,
                        {
                            "episodes": [],
                            "topic_terms": [],
                            "generation_grounding_text": self.dialogue.context(
                                chat_id,
                                current_user_text=user_text,
                                limit=8,
                            ),
                            "generation_mode": True,
                            "current_speaker": speaker.canonical_name,
                            "hashimoto_behavior": self.persona_judge.infer_behavior_state(
                                user_text=semantic_user_text,
                                context=self.dialogue.context(
                                    chat_id,
                                    current_user_text=semantic_user_text,
                                    limit=8,
                                ),
                                search_result={},
                                relation=dialogue_relation,
                                previous_mode=self.behavior_modes[chat_id],
                            ),
                        },
                    )
                    print(
                        "continuity_persona_judge:",
                        judge_info,
                        flush=True,
                    )
                    if chosen:
                        print(
                            "generation path: dialogue_v14_20_contextual_continuity",
                            flush=True,
                        )
                        return self.finish(chat_id, user_text, chosen)
                except Exception as e:
                    print(
                        "continuity_groq_error:",
                        repr(e),
                        flush=True,
                    )

            if dialogue_relation.get("relation") == "repair_request":
                answer = "今の返し変でした。言い直します"
            else:
                answer = "その話の続きでいいです"
            print(
                "generation path: dialogue_v14_20_safe_fallback",
                flush=True,
            )
            return self.finish(chat_id, user_text, answer)

        raw_result = self.searcher.search(search_user_text)
        result = self.ranker.rerank(
            search_user_text,
            raw_result,
            max_selected=2,
        )
        result["inherited_topic"] = False
        result["person_context"] = person_context
        result["search_user_text"] = search_user_text

        state = self.current_state.classify(
            user_text=semantic_user_text,
            history=list(self.histories[chat_id]),
            last_topic_terms=self.last_topic_terms[chat_id],
            search_result=result,
            is_first_message=is_first_message,
        )
        behavior_state = self.persona_judge.infer_behavior_state(
            user_text=semantic_user_text,
            context=self.dialogue.context(chat_id, current_user_text=semantic_user_text, limit=8),
            search_result=result,
            relation=dialogue_relation,
            previous_mode=self.behavior_modes[chat_id],
        )
        self.behavior_modes[chat_id] = behavior_state["mode"]
        state["hashimoto_mode"] = behavior_state["mode"]
        state["hashimoto_behavior"] = behavior_state
        state["hashimoto_subject_role"] = behavior_state.get("subject_role", "")
        state["hashimoto_stance"] = behavior_state.get("stance", {})
        state["hashimoto_reality"] = behavior_state.get("reality", {})
        state["hashimoto_value_orientation"] = behavior_state.get("value_orientation", {})
        state["hashimoto_question_semantics"] = behavior_state.get("question_semantics", {})
        state["hashimoto_opinion_evidence"] = behavior_state.get("opinion_evidence", {})
        result["hashimoto_behavior"] = behavior_state
        result["hashimoto_stance"] = behavior_state.get("stance", {})
        result["hashimoto_reality"] = behavior_state.get("reality", {})
        result["hashimoto_value_orientation"] = behavior_state.get("value_orientation", {})
        result["hashimoto_question_semantics"] = behavior_state.get("question_semantics", {})
        result["hashimoto_opinion_evidence"] = behavior_state.get("opinion_evidence", {})
        relationship_evidence = self.relationship_evidence.evidence(
            user_text=semantic_user_text,
            behavior=behavior_state,
            current_speaker=speaker.canonical_name,
            relationship_policy=(getattr(self.persona_judge.persona_policy, "profile", {}) or {}).get("relationship_policy", {}),
            person_context=person_context,
        )
        result["relationship_evidence"] = relationship_evidence
        state["relationship_evidence"] = relationship_evidence
        result["semantic_user_text"] = semantic_user_text
        state["semantic_user_text"] = semantic_user_text
        state["semantic_resolution"] = semantic_resolution
        state["person_context"] = person_context

        called = state.get("called", False)
        question = state.get("question", False)

        print("current_state:", state, flush=True)
        print("hashimoto_behavior_state:", behavior_state, flush=True)
        print("hashimoto_stance:", behavior_state.get("stance", {}), flush=True)
        print("hashimoto_reality:", behavior_state.get("reality", {}), flush=True)
        print(
            "hashimoto_value_orientation:",
            behavior_state.get("value_orientation", {}),
            flush=True,
        )
        print(
            "hashimoto_question_semantics:",
            behavior_state.get("question_semantics", {}),
            flush=True,
        )
        print(
            "hashimoto_opinion_evidence:",
            behavior_state.get("opinion_evidence", {}),
            flush=True,
        )
        print("relationship_evidence:", relationship_evidence, flush=True)
        print(
            "dynamic_search",
            f"terms={result.get('terms', [])[:12]}",
            f"topic_terms={result.get('topic_terms', [])[:12]}",
            f"generic_terms={result.get('generic_terms', [])[:12]}",
            f"predicates={result.get('predicates', [])[:12]}",
            f"search_mode={result.get('search_mode', '')}",
            f"inherited_topic={result.get('inherited_topic', False)}",
            f"candidate_hits={len(result.get('hits', []))}",
            f"candidate_episodes={len(result.get('candidate_episodes', []))}",
            f"selected_episodes={len(result.get('episodes', []))}",
            f"relevance_scores={result.get('relevance_scores', [])}",
            f"relevance_labels={result.get('relevance_labels', [])}",
            f"relevance_reasons={result.get('relevance_reasons', [])}",
            f"force_kept={result.get('force_kept', False)}",
            f"top_rejected={result.get('top_rejected_scores', [])}",
            f"qtypes={result.get('question_types', [])}",
            f"called={called}",
            f"question={question}",
            flush=True,
        )

        self.remember_topics(chat_id, result)

        # v14.27: undirected group messages are no longer automatic replies.
        # They pass through an evidence-based stochastic participation gate.
        spontaneous = self._spontaneous_gate(
            chat_id=chat_id,
            user_text=user_text,
            state=state,
            result=result,
            context=context,
            speaker=speaker,
            dialogue_relation=dialogue_relation,
            is_first_message=is_first_message,
            directed_to_ago=directed_to_ago,
        )
        print(
            "spontaneous_participation:",
            {
                k: v
                for k, v in spontaneous.items()
                if k not in {"replay", "replay_info"}
            },
            flush=True,
        )

        if spontaneous.get("gate"):
            if spontaneous.get("participate") and spontaneous.get("replay"):
                replay = spontaneous["replay"]
                replay_info = spontaneous.get("replay_info") or {}
                print(
                    "spontaneous_replay_engine:",
                    replay_info,
                    flush=True,
                )
                guarded, guard_info = guard_reply(
                    replay,
                    user_text,
                    preserve_long=True,
                )
                if guarded != replay:
                    print(
                        "style_guard:",
                        guard_info,
                        flush=True,
                    )
                print(
                    "generation path: spontaneous_v14_27_scene_participation",
                    flush=True,
                )
                return self.finish(chat_id, user_text, guarded)

            print(
                "generation path: spontaneous_v14_27_silence",
                flush=True,
            )
            return self.finish(chat_id, user_text, None)

        no_relevant_episode = not result.get("episodes")
        policy = self.reply_policy.plan(
            state,
            has_relevant_episode=not no_relevant_episode,
        )
        print("reply_policy:", policy, flush=True)

        if not policy.get("reply"):
            print("generation path: policy_silence", flush=True)
            return self.finish(chat_id, user_text, None)

        if (
            no_relevant_episode
            and not self.should_continue_reply(
                chat_id,
                user_text,
                called,
                question,
            )
        ):
            if "fallback" not in policy.get("routes", []):
                print(
                    "generation path: no_relevant_episode_ignore",
                    flush=True,
                )
                return self.finish(chat_id, user_text, None)

        if not no_relevant_episode and "canon" in policy.get("routes", []):
            canon, canon_info = self.canon_answer.answer(
                user_text,
                result,
            )
            if canon:
                guarded, guard_info = guard_reply(
                    canon,
                    user_text,
                )
                print("canon_answer:", canon_info, flush=True)
                if guarded != canon:
                    print(
                        "style_guard:",
                        guard_info,
                        flush=True,
                    )
                print(
                    "generation path: canon_v14_11_policy_answer",
                    flush=True,
                )
                return self.finish(chat_id, user_text, guarded)
            else:
                print(
                    "canon_answer_skip:",
                    canon_info,
                    flush=True,
                )
        elif "canon" not in policy.get("routes", []):
            print(
                "canon_answer_skip:",
                {
                    "used": False,
                    "reason": "policy_skipped_canon",
                },
                flush=True,
            )

        if "scene_replay" in policy.get("routes", []):
            if not no_relevant_episode:
                replay, replay_info = self.replay_engine.choose(
                    user_text=user_text,
                    context=context,
                    topic_terms=result.get("topic_terms", []),
                    context_topic_terms=(
                        state.get("topic_terms", [])
                        if state.get("inherited_topic")
                        else []
                    ),
                    intent=state.get("intent", ""),
                    current_speaker=speaker.canonical_name,
                )
                print("replay_engine_raw:", replay_info, flush=True)
                replay, replay_info = self.persona_judge.select_replay(
                    replay=replay,
                    replay_info=replay_info,
                    user_text=user_text,
                    behavior=behavior_state,
                )
                print("replay_engine_behavioral:", replay_info, flush=True)
                if replay:
                    # Historical Replay is allowed to keep its original length.
                    guarded, guard_info = guard_reply(
                        replay,
                        user_text,
                        preserve_long=True,
                    )
                    if guarded != replay:
                        print(
                            "style_guard:",
                            guard_info,
                            flush=True,
                        )
                    print(
                        "generation path: replay_v15_behavioral_scene_reply",
                        flush=True,
                    )
                    return self.finish(
                        chat_id,
                        user_text,
                        guarded,
                    )
            else:
                print(
                    "replay_engine_skip: no_relevant_episode",
                    flush=True,
                )
        else:
            print(
                "replay_engine_skip: policy_skipped_scene_replay",
                flush=True,
            )

        if "fallback" not in policy.get("routes", []):
            print(
                "generation path: policy_no_fallback_silence",
                flush=True,
            )
            return self.finish(chat_id, user_text, None)

        if not self.groq_available():
            print(
                "generation path: groq_cooldown_capyi",
                flush=True,
            )
            return self.finish(
                chat_id,
                user_text,
                ERROR_FALLBACK,
            )

        try:
            if no_relevant_episode:
                system, user = self.fallback_prompt(
                    semantic_user_text,
                    context,
                    chat_id,
                    question,
                    speaker,
                    person_context=result.get("person_context", {}),
                )
            else:
                system, user = self.build_prompt(
                    semantic_user_text,
                    context,
                    result,
                    chat_id,
                    speaker,
                )

            res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.temperature,
                max_completion_tokens=max(self.groq_completion_tokens, 384),
                extra_body={"reasoning_effort": self.groq_reasoning_effort},
            )
            raw = self.completion_text(res, "groq")
            print("groq_raw:", raw, flush=True)
            raw = _repair_surface_corruption(raw)
            candidates = self.persona_judge.split_candidates(raw)
            print("persona_candidates:", candidates, flush=True)

            cleaned_candidates = []
            for cand in candidates:
                cand_clean = clean_reply(semantic_user_text, cand)
                cand_clean = self.remove_unverified_vocative(
                    cand_clean,
                    speaker,
                )
                cand_clean = _repair_surface_corruption(cand_clean)
                if cand_clean:
                    cleaned_candidates.append(cand_clean)

            judge_result = dict(result)
            judge_result["generation_grounding_text"] = "\n".join([
                semantic_user_text or "",
                self.dialogue.context(chat_id, current_user_text=semantic_user_text, limit=8) or "",
            ]).strip()
            judge_result["generation_mode"] = True
            judge_result["current_speaker"] = speaker.canonical_name
            judge_result["hashimoto_behavior"] = result.get(
                "hashimoto_behavior",
                {"mode": self.behavior_modes[chat_id]},
            )
            judge_result["hashimoto_stance"] = result.get(
                "hashimoto_stance",
                judge_result["hashimoto_behavior"].get("stance", {}),
            )
            judge_result["hashimoto_reality"] = result.get(
                "hashimoto_reality",
                judge_result["hashimoto_behavior"].get("reality", {}),
            )
            judge_result["hashimoto_value_orientation"] = result.get(
                "hashimoto_value_orientation",
                judge_result["hashimoto_behavior"].get("value_orientation", {}),
            )
            judge_result["hashimoto_question_semantics"] = result.get(
                "hashimoto_question_semantics",
                judge_result["hashimoto_behavior"].get("question_semantics", {}),
            )
            judge_result["hashimoto_opinion_evidence"] = result.get(
                "hashimoto_opinion_evidence",
                judge_result["hashimoto_behavior"].get("opinion_evidence", {}),
            )
            judge_result["relationship_evidence"] = result.get("relationship_evidence", {})
            judge_result["person_context"] = result.get("person_context", {})

            chosen, judge_info = self.persona_judge.choose(
                cleaned_candidates,
                semantic_user_text,
                judge_result,
            )
            print("persona_judge:", judge_info, flush=True)

            retry_needed, retry_reasons = self.persona_judge.should_regenerate(
                chosen, judge_info, judge_result
            )
            if retry_needed:
                print("persona_regeneration:", {"retry": True, "reasons": retry_reasons}, flush=True)
                retry_system = system + (
                    " 前回候補はjudgeで不十分と判定された。今度は指摘を修正する。"
                    " 人物関係資料がある場合はその実際の関係を使い、一般論や無難な逃げにしない。"
                    " 対象人物IDは前処理済みなので、別名の意味を聞き返したり別人として再解釈しない。"
                    " 観測シグナルがあるなら、そのうち少なくとも1つを返答内容に具体的に反映する。"
                    " 『微妙』『別に』『まあかな』だけで終わらせない。"
                    " ただし資料にない好き嫌い・感情・出来事は発明しない。"
                )
                retry_user = user + "\n\n前回の失敗理由:" + ", ".join(retry_reasons) + (
                    "\n4候補をすべて作り直す。前回候補の言い換えだけにしない。"
                )
                retry_res = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": retry_system},
                        {"role": "user", "content": retry_user},
                    ],
                    temperature=min(self.temperature, 0.72),
                    max_completion_tokens=max(self.groq_completion_tokens, 384),
                    extra_body={"reasoning_effort": self.groq_reasoning_effort},
                )
                retry_raw = self.completion_text(retry_res, "groq_retry")
                retry_raw = _repair_surface_corruption(retry_raw)
                print("groq_retry_raw:", retry_raw, flush=True)
                retry_candidates = []
                for cand in self.persona_judge.split_candidates(retry_raw):
                    cand_clean = clean_reply(semantic_user_text, cand)
                    cand_clean = self.remove_unverified_vocative(cand_clean, speaker)
                    cand_clean = _repair_surface_corruption(cand_clean)
                    if cand_clean:
                        retry_candidates.append(cand_clean)
                print("persona_retry_candidates:", retry_candidates, flush=True)
                retry_chosen, retry_judge_info = self.persona_judge.choose(
                    retry_candidates, semantic_user_text, judge_result
                )
                print("persona_retry_judge:", retry_judge_info, flush=True)
                if retry_chosen:
                    chosen = retry_chosen
                    judge_info = retry_judge_info

            answer = chosen
            if (
                not answer
                or answer in set(self.last_bot_replies[chat_id])
            ):
                print(
                    "generation path: persona_judge_reject_capyi",
                    flush=True,
                )
                answer = ERROR_FALLBACK
            else:
                if no_relevant_episode:
                    print(
                        "generation path: groq_v14_11_policy_fallback_continuity",
                        flush=True,
                    )
                else:
                    print(
                        "generation path: groq_v14_11_policy_fallback_episode",
                        flush=True,
                    )
        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            if (
                "429" in str(e)
                or "rate_limit" in str(e)
                or "TPD" in str(e)
            ):
                self.disable_groq()
                print(
                    "generation path: groq_429_capyi",
                    flush=True,
                )
            else:
                print(
                    "generation path: groq_exception_capyi",
                    flush=True,
                )
            answer = ERROR_FALLBACK

        return self.finish(chat_id, user_text, answer)


HashimotoArataBot = AgoHashimotoBot
