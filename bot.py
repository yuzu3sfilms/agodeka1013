import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from store import HashimotoStore
from utils import clean_reply


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "240"))
        self.temperature = float(os.environ.get("TEMPERATURE", "1.05"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "5"))
        self.cooldown_seconds = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
        self.groq_disabled_until = 0.0

        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )

        self.store = HashimotoStore()
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))

        with open("profile.txt", "r", encoding="utf-8") as f:
            self.profile = f.read()

    def remember(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def prompt(self, user_text: str, context: str, hits: dict) -> tuple[str, str]:
        pairs = "\n".join(
            f"相手:{p.get('context_text','')}\n橋本新:{p.get('reply','')}"
            for p in hits["pairs"][:6]
        ) or "なし"

        messages = "\n".join(
            f"{m.get('text','')}"
            for m in hits["messages"][:5]
        ) or "なし"

        recent = "\n".join(context.splitlines()[-self.history_len:])

        system = self.profile + """

実行ルール:
- 似た返答ペアを最優先で真似る。
- 完全コピーではなく、今回の会話に自然に合わせる。
- 感情トーンを補正しない。低温化しない。
- テンションが高い文脈では高くしてよい。
- 強い表現も、過去ログ上・文脈上自然なら使ってよい。
- 返答の文字数を無理に短くしない。過去例に合わせる。
- ただしChatGPT風に説明しない。
- ユーザー文をそのまま繰り返さない。
"""

        user = f"""
直近会話:
{recent}

今回:
{user_text}

似た過去の文脈→橋本新返答:
{pairs}

関連する本人発言:
{messages}

橋本新として、文脈・テンション・長さを丸めずに返す。
"""
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str:
        context = self.context(chat_id, user_text)

        # 全返信保証：最初にローカル返答を確保
        local = clean_reply(user_text, self.store.local_reply(context))
        hits = self.store.search(context)

        if not self.groq_available():
            self.remember(chat_id, user_text)
            return local

        try:
            system, user = self.prompt(user_text, context, hits)
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

        except Exception as e:
            print("Groq error:", repr(e))
            if "429" in str(e) or "rate_limit" in str(e) or "TPD" in str(e):
                self.disable_groq()
            answer = local

        self.remember(chat_id, user_text)
        return answer or local or "難しいです。"
