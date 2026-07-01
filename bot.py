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
from utils import clean_reply, normalize, de_ai_tone


ERROR_FALLBACK = "ｷｬﾋﾟｨ"
CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA"]


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "90"))
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
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))
        self.last_reply_at = defaultdict(float)
        self.continuity_seconds = int(os.environ.get("CONTINUITY_SECONDS", "420"))
        self.continuity_min_history = int(os.environ.get("CONTINUITY_MIN_HISTORY", "1"))
        self.continuity_probability = float(os.environ.get("CONTINUITY_REPLY_PROBABILITY", "0.75"))

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def remember_bot(self, chat_id: str, text: str):
        if text:
            self.last_bot_replies[chat_id].append(text)
            self.last_reply_at[chat_id] = time.time()

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

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

過去ログに強い関連がない時の、会話継続用の短い返答。"""
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
            "あなたは橋本新本人風のAIアカウント。"
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

橋本新として返答。"""
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str | None:
        context = self.context(chat_id, user_text)
        raw_result = self.searcher.search(user_text)
        result = self.ranker.rerank(user_text, raw_result, max_selected=2)
        called = self.called_directly(user_text)
        question = self.is_question(user_text)

        print(
            "dynamic_search",
            f"terms={result.get('terms', [])[:12]}",
            f"topic_terms={result.get('topic_terms', [])[:12]}",
            f"generic_terms={result.get('generic_terms', [])[:12]}",
            f"predicates={result.get('predicates', [])[:12]}",
            f"search_mode={result.get('search_mode', '')}",
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

        no_relevant_episode = not result.get("episodes")

        if no_relevant_episode and not self.should_continue_reply(chat_id, user_text, called, question):
            self.remember_user(chat_id, user_text)
            print("generation path: no_relevant_episode_ignore", flush=True)
            return None

        if not no_relevant_episode:
            canon, canon_info = self.canon_answer.answer(user_text, result)
            if canon:
                guarded, guard_info = guard_reply(canon, user_text)
                print("canon_answer:", canon_info, flush=True)
                if guarded != canon:
                    print("style_guard:", guard_info, flush=True)
                answer = guarded
                print("generation path: canon_v12_5_answer", flush=True)
                self.remember_user(chat_id, user_text)
                self.remember_bot(chat_id, answer)
                return answer
            else:
                print("canon_answer_skip:", canon_info, flush=True)

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
            answer = clean_reply(user_text, raw)
            guarded, guard_info = guard_reply(answer, user_text)
            if guarded != answer:
                print("style_guard:", guard_info, flush=True)
            answer = guarded

            if not answer or answer in set(self.last_bot_replies[chat_id]):
                print("generation path: groq_bad_capyi", flush=True)
                answer = ERROR_FALLBACK
            else:
                if no_relevant_episode:
                    print("generation path: groq_v12_5_continuity_fallback", flush=True)
                else:
                    print("generation path: groq_v12_5_topic_episode", flush=True)

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
