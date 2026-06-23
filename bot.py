import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from trigger_engine import TriggerEngine
from utils import clean_reply


ERROR_FALLBACK = "ｷｬﾋﾟｨ"


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "120"))
        self.temperature = float(os.environ.get("TEMPERATURE", "0.95"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "4"))
        self.cooldown_seconds = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
        self.groq_disabled_until = 0.0

        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )

        self.triggers = TriggerEngine()
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))

        with open("persona.md", "r", encoding="utf-8") as f:
            self.persona = f.read()

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def remember_bot(self, chat_id: str, text: str):
        if text:
            self.last_bot_replies[chat_id].append(text)

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def emergency_reply(self) -> str:
        return ERROR_FALLBACK

    def build_prompt(self, user_text: str, context: str, hits: list[dict], chat_id: str):
        trigger_block = self.triggers.format_hits(hits)
        recent = "\n".join(context.splitlines()[-self.history_len:])
        recent_bot = "\n".join(self.last_bot_replies[chat_id]) or "なし"
        trigger_names = ", ".join(h["trigger"] for h in hits)

        system = """
あなたはLINEグループにいた「橋本新」を模倣するAI。
キーワード/triggerが出た時だけ反応する。
怒り・罵倒・攻撃的な感情は切り離す。
triggerの関連エピソード/語録を必ず拾う。
ChatGPT風に説明しない。
ユーザー発言を丸写ししない。
直近の自分の返答と同じ返答をしない。
短く逃げず、文脈に合わせて自然に返す。
""".strip()

        user = f"""
今回の発言:
{user_text}

発火trigger:
{trigger_names}

直近会話:
{recent}

直近の自分の返答:
{recent_bot}

trigger関連の過去例:
{trigger_block}

橋本新として自然に返答。triggerを必ず拾う。怒りは出さない。
""".strip()
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str | None:
        context = self.context(chat_id, user_text)
        hits = self.triggers.match(user_text, context)

        print(
            "trigger_check",
            f"hits={[h['trigger'] for h in hits]}",
            flush=True,
        )

        # Keyword-only mode: no trigger, no reply.
        if not hits:
            self.remember_user(chat_id, user_text)
            print("generation path: no_trigger_ignore", flush=True)
            return None

        # If Groq is cooling down, send requested fixed fallback.
        if not self.groq_available():
            print("generation path: groq_cooldown_capyi", flush=True)
            answer = self.emergency_reply()
            self.remember_user(chat_id, user_text)
            self.remember_bot(chat_id, answer)
            return answer

        try:
            system, user = self.build_prompt(user_text, context, hits, chat_id)
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
            answer = clean_reply(user_text, raw)

            if not answer or answer in set(self.last_bot_replies[chat_id]):
                print("generation path: groq_bad_capyi", flush=True)
                answer = self.emergency_reply()
            else:
                print("generation path: groq_trigger", flush=True)

        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            if "429" in str(e) or "rate_limit" in str(e) or "TPD" in str(e):
                self.disable_groq()
                print("generation path: groq_429_capyi", flush=True)
            else:
                print("generation path: groq_exception_capyi", flush=True)
            answer = self.emergency_reply()

        self.remember_user(chat_id, user_text)
        self.remember_bot(chat_id, answer)
        return answer
