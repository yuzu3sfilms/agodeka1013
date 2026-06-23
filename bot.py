import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from store import HashimotoStore
from utils import clean_reply


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "80"))
        self.temperature = float(os.environ.get("TEMPERATURE", "0.92"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "4"))
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
            f"相手:{p.get('context_text','')}\n橋本新:{p.get('reply','')} "
            f"[emotion={p.get('emotion','neutral')}, function={p.get('response_function','plain_reply')}, tags={','.join(p.get('behavior_tags', []))}]"
            for p in hits["pairs"][:5]
        ) or "なし"

        messages = "\n".join(
            f"{m.get('text','')} [emotion={m.get('emotion','neutral')}, function={m.get('response_function','plain_reply')}]"
            for m in hits["messages"][:4]
        ) or "なし"

        style_len = self.store.style_profile.get("length", {})
        presence = self.store.presence_profile.get("interpretation", {})
        recent = "\n".join(context.splitlines()[-self.history_len:])

        system = self.profile + f"""

実行ルール:
- 似た返答ペアを最優先で真似る。
- ただし完全コピーではなく、今回の会話に自然に合わせる。
- 返答内容だけでなく、反応機能と感情トーンを合わせる。
- 今回の目標感情: {hits.get('target_emotion','neutral')}
- ユーザー側の感情推定: {hits.get('user_emotion','neutral')}
- 今回の目標反応機能: {hits.get('target_function','plain_reply')}
- 橋本新の発言長中央値は約{style_len.get('median',14)}文字、75%は約{style_len.get('p75',27)}文字以内。
- 存在感の核: {presence.get('core','短い丁寧/中立返答、困惑、弱り、お願い、質問返し。')}
- 質問に正解を返すより、橋本新がその場にいた時の温度で返す。
- キレすぎない。怒り・罵倒・攻撃性だけを過剰再現しない。
- ユーザー文をそのまま繰り返さない。
- ChatGPT風に説明しない。
- 1〜2文。できれば短く。
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

橋本新として、文脈・感情・反応機能を合わせて短く返す。
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
