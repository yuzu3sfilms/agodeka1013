import os
import re
import time
from collections import defaultdict, deque

from openai import OpenAI

from dynamic_search import DynamicSearch
from relationship import RelationshipProfile
from relevance import RelevanceRanker
from style_guard import guard_reply
from canon_answer import CanonAnswer
from persona_judge import PersonaJudge
from actual_reply_engine import ActualReplyEngine
from current_state_engine import CurrentStateEngine
from reply_policy import ReplyPolicy
from training_advisor import TrainingAdvisor
from utils import clean_reply, normalize, de_ai_tone


ERROR_FALLBACK = "ｷｬﾋﾟｨ"
CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA"]
ATTENTION_ONLY_TERMS = {"ねえ", "ねぇ", "ちょっと", "おい", "あの", "なあ", "なぁ", "うん", "はい", "なるほど", "ふむ"}


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "160"))
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
        self.ranker = RelevanceRanker()
        self.canon_answer = CanonAnswer()
        self.persona_judge = PersonaJudge()
        self.replay_engine = ActualReplyEngine()
        self.current_state = CurrentStateEngine()
        self.reply_policy = ReplyPolicy()
        self.training_advisor = TrainingAdvisor()
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))
        self.last_reply_at = defaultdict(float)
        self.last_topic_terms = defaultdict(list)
        self.continuity_seconds = int(os.environ.get("CONTINUITY_SECONDS", "420"))
        self.continuity_min_history = int(os.environ.get("CONTINUITY_MIN_HISTORY", "1"))
        self.continuity_probability = float(os.environ.get("CONTINUITY_REPLY_PROBABILITY", "0.75"))

        print(
            "bot_init:",
            "version=v14.7",
            f"persona_judge={hasattr(self, 'persona_judge')}",
            f"persona_profile_loaded={bool(getattr(self.persona_judge, 'profile', None))}",
            f"topic_canon_loaded={bool(getattr(self.persona_judge, 'topic_canon', None))}",
            f"replay_scenes={len(getattr(self.replay_engine, 'scenes', []))}", f"policy=True", f"training=True",
            flush=True,
        )

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def remember_bot(self, chat_id: str, text: str):
        if text:
            self.last_bot_replies[chat_id].append(text)
            self.last_reply_at[chat_id] = time.time()

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

    def should_inherit_topic(self, chat_id: str, user_text: str, raw_result: dict) -> bool:
        stripped = (user_text or "").strip()
        # v14.4:
        # Do not inherit previous topic for attention-only fillers.
        # "ねえ" / "ちょっと" should not repeatedly trigger the last topic scene.
        if stripped in ATTENTION_ONLY_TERMS:
            return False
        if raw_result.get("topic_terms"):
            return False
        if not self.last_topic_terms[chat_id]:
            return False
        # Inherit for short follow-up questions or vague replies.
        if self.is_question(user_text):
            return True
        if len(stripped) <= 12 and raw_result.get("candidate_hits", 0) == 0:
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
        return bool(re.search(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|使う|作って|なの|の？|の\?", user_text))

    def is_conversation_continuing(self, chat_id: str) -> bool:
        """
        v12.2:
        If the bot has replied recently and the chat has some context,
        do not suddenly go silent just because relevance dropped to zero.
        """
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
        # Stable pseudo-randomness per text/chat; avoids replying to literally everything.
        import random
        seed = hash((chat_id, user_text, int(time.time() // 60)))
        rng = random.Random(seed)
        return rng.random() < self.continuity_probability

    def fallback_prompt(self, user_text: str, context: str, chat_id: str, question: bool):
        relation_style = "\n".join(self.relationships.style_samples(n=4))
        system = (
            "橋本新本人風のAIアカウントとしてLINEで短く返す。"
            "グループ内では「あらくん」「橋本」「顎」「AGODEKA」と呼ばれる同一人物。"
            "説明AI禁止。自己説明禁止。"
            "一人称は基本出さない。私/わたし/俺/おれは禁止。"
            "過去ログに強い根拠がない時は、新設定を作らず短い反応だけにする。"
            "1文。短く雑に。"
            "「ぜ」「ないよ」「だよ」「よな」「だよな」「だよね」「なんだよね」「です」「ます」禁止。"
        )
        user = f"""mode:{'Q' if question else 'continue'}
発言:{user_text}
直近:{context}

口調サンプル:
{relation_style}

過去ログに強い関連がない時の、会話継続用の短い返答候補を4つ。
候補1: ...
候補2: ...
候補3: ...
候補4: ..."""
        return system, user


    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def build_prompt(self, user_text: str, context: str, search_result: dict, chat_id: str):
        episode_block = self.searcher.format_episodes(search_result)
        style_from_episode = self.searcher.format_style(search_result)
        relation_block = self.relationships.format()
        relation_style = "\n".join(f"- {x}" for x in self.relationships.style_samples(6))
        terms = ", ".join(search_result.get("terms", [])[:8])
        topic_terms = ", ".join(search_result.get("topic_terms", [])[:8])
        predicates = ", ".join(search_result.get("predicates", [])[:8])
        rel = ", ".join(str(x) for x in search_result.get("relevance_scores", []))
        reasons = str(search_result.get("relevance_reasons", []))[:300]
        recent = "\n".join(context.splitlines()[-2:])
        question = self.is_question(user_text)

        system = (
            "あなたは橋本新本人風のAIアカウント。ただしこれは最後の保険生成。過去ログ実返答が使えない時だけ使われる。"
            "グループ内では「あらくん」「橋本」「顎」「AGODEKA」と呼ばれる同一人物として返す。"
            "呼ばれたら自分のこととして反応する。"
            "説明AI禁止。自己説明禁止。"
            "一人称は基本出さない。私/わたし/俺/おれは禁止。必要なら僕。"
            "質問ならまず短く答える。説明しすぎない。"
            "過去ログエピソードは単なる参考材料ではなく、この人物の設定・記憶・関係性の根拠。"
            "返答は過去ログエピソードに矛盾してはいけない。"
            "エピソードに根拠がある時は、その事実・関係・ノリを優先する。一般論で埋めない。"
            "ヒットしたエピソードの名詞・出来事・関係性・言い回しを返答に反映する。"
            "エピソードにある話題を無視して、一般的な返答に逃げない。"
            "エピソードにないことを勝手に断定しない。"
            "怒り・罵倒なし。1文。長くても2文。"
            "語尾でキャラを作らない。"
            "「ぜ」「ないよ」「だよ」「よな」「だよな」「だよね」「なんだよね」「です」「ます」禁止。"
        )

        user = f"""mode:{'Q' if question else 'react'}
発言:{user_text}
語:{terms}
本題語:{topic_terms}
述語:{predicates}
関連度:{rel}
採用理由:{reasons}
直近:{recent}

過去ログ:
{episode_block}

関係:
{relation_block}

口調:
{style_from_episode}
{relation_style}

厳守:
- 過去ログは設定。矛盾禁止。
- 検索エピソードに出ている人物関係・出来事・好みを優先。
- ヒット語とエピソード内の固有名詞を無視しない。
- 過去ログのエピソードを再生するように、短く反応。
- 根拠が薄い時は断定せず短く反応。
- 綺麗に説明しない。

出力形式:
候補1: ...
候補2: ...
候補3: ...
候補4: ...

橋本新として、短い候補を4つ出す。"""
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str | None:
        context = self.context(chat_id, user_text)

        # v14.6: practical training-advisor route first.
        # This prevents workout questions from being treated as inside-joke search queries.
        training = self.training_advisor.answer(chat_id, user_text)
        print("training_advisor:", {k: v for k, v in training.items() if k != "answer"}, flush=True)
        if training.get("used"):
            answer = training["answer"]
            print(f"generation path: training_v14_7_{training.get('kind', 'advisor')}", flush=True)
            self.remember_user(chat_id, user_text)
            self.remember_bot(chat_id, answer)
            return answer

        raw_result = self.searcher.search(user_text)
        inherited_topic = False
        if self.should_inherit_topic(chat_id, user_text, raw_result):
            inherited_topic = True
            inherited_text = user_text + " " + " ".join(self.last_topic_terms[chat_id])
            print("topic_inherit:", self.last_topic_terms[chat_id], "augmented_text=", inherited_text, flush=True)
            raw_result = self.searcher.search(inherited_text)

        result = self.ranker.rerank(user_text, raw_result, max_selected=2)
        result["inherited_topic"] = inherited_topic

        state = self.current_state.classify(
            user_text=user_text,
            history=list(self.histories[chat_id]),
            last_topic_terms=self.last_topic_terms[chat_id],
            search_result=result,
        )
        if state.get("inherited_topic") and not inherited_topic:
            inherited_topic = True
            inherited_text = user_text + " " + " ".join(state.get("topic_terms", []))
            print("state_topic_inherit:", state.get("topic_terms", []), "augmented_text=", inherited_text, flush=True)
            raw_result = self.searcher.search(inherited_text)
            result = self.ranker.rerank(user_text, raw_result, max_selected=2)
            result["inherited_topic"] = True
            state = self.current_state.classify(
                user_text=user_text,
                history=list(self.histories[chat_id]),
                last_topic_terms=self.last_topic_terms[chat_id],
                search_result=result,
            )

        called = state.get("called", False)
        question = state.get("question", False)
        print("current_state:", state, flush=True)

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

        no_relevant_episode = not result.get("episodes")
        policy = self.reply_policy.plan(state, has_relevant_episode=not no_relevant_episode)
        print("reply_policy:", policy, flush=True)

        if not policy.get("reply"):
            self.remember_user(chat_id, user_text)
            print("generation path: policy_silence", flush=True)
            return None

        if no_relevant_episode and not self.should_continue_reply(chat_id, user_text, called, question):
            if "fallback" not in policy.get("routes", []):
                self.remember_user(chat_id, user_text)
                print("generation path: no_relevant_episode_ignore", flush=True)
                return None

        if not no_relevant_episode and "canon" in policy.get("routes", []):
            canon, canon_info = self.canon_answer.answer(user_text, result)
            if canon:
                guarded, guard_info = guard_reply(canon, user_text)
                print("canon_answer:", canon_info, flush=True)
                if guarded != canon:
                    print("style_guard:", guard_info, flush=True)
                answer = guarded
                print("generation path: canon_v14_7_policy_answer", flush=True)
                self.remember_user(chat_id, user_text)
                self.remember_bot(chat_id, answer)
                return answer
            else:
                print("canon_answer_skip:", canon_info, flush=True)
        elif "canon" not in policy.get("routes", []):
            print("canon_answer_skip:", {"used": False, "reason": "policy_skipped_canon"}, flush=True)

        # v14.3: actual-reply-first replay engine controlled by reply_policy.
        # If a similar past situation exists, replay an actual Hashimoto reply
        # before asking Groq to invent anything.
        if "scene_replay" in policy.get("routes", []):
            if not no_relevant_episode:
                replay, replay_info = self.replay_engine.choose(
                    user_text=user_text,
                    context=context,
                    topic_terms=state.get("topic_terms") or result.get("topic_terms", []),
                )
                print("replay_engine:", replay_info, flush=True)
                if replay:
                    guarded, guard_info = guard_reply(replay, user_text)
                    if guarded != replay:
                        print("style_guard:", guard_info, flush=True)
                    answer = guarded
                    print("generation path: replay_v14_7_intent_ranked_scene_reply", flush=True)
                    self.remember_user(chat_id, user_text)
                    self.remember_bot(chat_id, answer)
                    return answer
            else:
                print("replay_engine_skip: no_relevant_episode", flush=True)
        else:
            print("replay_engine_skip: policy_skipped_scene_replay", flush=True)

        if "fallback" not in policy.get("routes", []):
            self.remember_user(chat_id, user_text)
            print("generation path: policy_no_fallback_silence", flush=True)
            return None

        if not self.groq_available():
            print("generation path: groq_cooldown_capyi", flush=True)
            answer = ERROR_FALLBACK
            self.remember_user(chat_id, user_text)
            self.remember_bot(chat_id, answer)
            return answer

        try:
            if no_relevant_episode:
                system, user = self.fallback_prompt(user_text, context, chat_id, question)
            else:
                system, user = self.build_prompt(user_text, context, result, chat_id)
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            raw = res.choices[0].message.content or ""
            print("groq_raw:", raw, flush=True)

            raw = de_ai_tone(raw)
            candidates = self.persona_judge.split_candidates(raw)
            print("persona_candidates:", candidates, flush=True)

            cleaned_candidates = []
            for cand in candidates:
                cand_clean = clean_reply(user_text, cand)
                guarded, guard_info = guard_reply(cand_clean, user_text)
                if guarded != cand_clean:
                    print("style_guard_candidate:", guard_info, "orig=", cand_clean, "guarded=", guarded, flush=True)
                if guarded:
                    cleaned_candidates.append(guarded)

            chosen, judge_info = self.persona_judge.choose(cleaned_candidates, user_text, result)
            print("persona_judge:", judge_info, flush=True)

            answer = chosen

            if not answer or answer in set(self.last_bot_replies[chat_id]):
                print("generation path: persona_judge_reject_capyi", flush=True)
                answer = ERROR_FALLBACK
            else:
                if no_relevant_episode:
                    print("generation path: groq_v14_7_policy_fallback_continuity", flush=True)
                else:
                    print("generation path: groq_v14_7_policy_fallback_episode", flush=True)

        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            if "429" in str(e) or "rate_limit" in str(e) or "TPD" in str(e):
                self.disable_groq()
                print("generation path: groq_429_capyi", flush=True)
            else:
                print("generation path: groq_exception_capyi", flush=True)
            answer = ERROR_FALLBACK

        self.remember_user(chat_id, user_text)
        self.remember_bot(chat_id, answer)
        return answer
