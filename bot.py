import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from trigger_engine import TriggerEngine
from utils import clean_reply


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "260"))
        self.temperature = float(os.environ.get("TEMPERATURE", "1.02"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "6"))
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

    def emergency_reply(self, user_text: str, hits: list[dict]) -> str:
        # Trigger exists but Groq unavailable: use first clean example instead of random generic.
        for h in hits:
            for ex in h.get("examples", []):
                r = (ex.get("reply") or "").strip()
                if r and r not in {"んー", "うん", "はい"}:
                    return r
        return ""

    def build_prompt(self, user_text: str, context: str, hits: list[dict], chat_id: str):
        trigger_block = self.triggers.format_hits(hits)
        recent = "\n".join(context.splitlines()[-self.history_len:])
        recent_bot = "\n".join(self.last_bot_replies[chat_id]) or "なし"
        trigger_names = ", ".join(h["trigger"] for h in hits)

        system = self.persona + """

生成ルール:
- triggerが出た時だけ返答するBotである。
- 今回出たtriggerを必ず拾う。
- 関連エピソード/語録/過去の返し方を反応に混ぜる。
- 一般返答だけで流さない。
- 怒り・罵倒・攻撃的な感情は再現しない。怒った人格にしない。
- ただし語録やテンションは必要なら出してよい。
- 参考例をそのまま貼るのではなく、今回の文脈に合わせる。
- 直近の自分の返答と同じ返答を繰り返さない。
- 「んー」「はい」「うん」だけで逃げない。
- ChatGPT風に説明しない。
- ユーザー発言の丸写しをしない。
"""

        user = f"""
直近会話:
{recent}

今回の相手発言:
{user_text}

発火trigger:
{trigger_names}

直近の自分の返答（繰り返し禁止）:
{recent_bot}

triggerに紐づく過去エピソード/語録/返答例:
{trigger_block}

橋本新として自然に返答。triggerを必ず拾う。怒りは切り離す。
"""
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

        if not self.groq_available():
            print("generation path: emergency_trigger_cooldown", flush=True)
            answer = self.emergency_reply(user_text, hits)
            self.remember_user(chat_id, user_text)
            self.remember_bot(chat_id, answer)
            return answer or None

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
                print("generation path: groq_bad_using_emergency", flush=True)
                answer = self.emergency_reply(user_text, hits)
            else:
                print("generation path: groq_trigger", flush=True)

        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            if "429" in str(e) or "rate_limit" in str(e) or "TPD" in str(e):
                self.disable_groq()
            print("generation path: emergency_trigger_exception", flush=True)
            answer = self.emergency_reply(user_text, hits)

        self.remember_user(chat_id, user_text)
        self.remember_bot(chat_id, answer)
        return answer or None
