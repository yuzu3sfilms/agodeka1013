import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from retriever import Retriever
from utils import clean_reply


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "260"))
        self.temperature = float(os.environ.get("TEMPERATURE", "1.03"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "6"))
        self.cooldown_seconds = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
        self.groq_disabled_until = 0.0

        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )

        self.retriever = Retriever()
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))

        with open("persona.md", "r", encoding="utf-8") as f:
            self.persona = f.read()

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def remember_bot(self, chat_id: str, text: str):
        self.last_bot_replies[chat_id].append(text)

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def emergency_reply(self, user_text: str, hits: dict | None = None) -> str:
        hits = hits or {}
        triggers = hits.get("trigger_hits", [])

        # If a trigger is present and Groq is unavailable, use a trigger example instead of a generic quote lottery.
        for h in triggers:
            for ex in h.get("examples", []):
                r = (ex.get("reply") or "").strip()
                if r and r not in {"んー", "うん", "はい"}:
                    return r

        t = user_text or ""
        if "嫌い" in t:
            return "嫌いではないです。"
        if any(x in t for x in ["おい", "壊れ", "こわれ"]):
            return "何ですか？"
        if "?" in t or "？" in t:
            return "どういうことですか？"
        if any(x in t for x in ["あらくん", "橋本", "あらた"]):
            return "呼びました？"
        return "難しいです。"

    def format_trigger_block(self, hits: dict) -> str:
        trigger_hits = hits.get("trigger_hits", [])
        if not trigger_hits:
            return "なし"

        blocks = []
        for h in trigger_hits:
            exs = []
            for ex in h.get("examples", [])[:4]:
                ctx = (ex.get("context") or "").strip()
                lo = (ex.get("last_other") or "").strip()
                rep = (ex.get("reply") or "").strip()
                parts = []
                if ctx:
                    parts.append(f"文脈:{ctx}")
                if lo:
                    parts.append(f"直前:{lo}")
                if rep:
                    parts.append(f"橋本新:{rep}")
                if parts:
                    exs.append("\n".join(parts))
            blocks.append(f"## trigger: {h['trigger']} (docfreq={h.get('docfreq',0)})\n" + "\n---\n".join(exs))
        return "\n\n".join(blocks)

    def build_prompt(self, user_text: str, context: str, hits: dict, chat_id: str):
        pairs = "\n\n".join(
            f"【過去文脈】\n{p.get('context_text','')}\n【橋本新の返答】\n{p.get('reply','')}"
            for p in hits["pairs"][:6]
        ) or "なし"

        messages = "\n".join(
            f"- {m.get('text','')}"
            for m in hits["messages"][:6]
        ) or "なし"

        trigger_block = self.format_trigger_block(hits)
        recent = "\n".join(context.splitlines()[-self.history_len:])
        recent_bot = "\n".join(self.last_bot_replies[chat_id]) or "なし"

        system = self.persona + """

生成ルール:
- 参考例をそのまま貼るのではなく、今回の文脈に合わせて橋本新として生成する。
- ユーザー発言に trigger が含まれている場合、関連エピソード/語録/過去の返し方を必ず反応に混ぜる。
- triggerが出ているのに一般返答だけで流さない。
- 近い過去文脈がある場合、その返し方・温度・語尾を強く参考にする。
- 近い過去文脈が弱い場合でも、「んー」「はい」「うん」だけに逃げない。
- 直近の自分の返答と同じ返答を繰り返さない。
- 感情やテンションを勝手に低く丸めない。
- 文字数を無理に短くしない。
- ChatGPT風に説明しない。
- ユーザー発言の丸写しをしない。
"""

        user = f"""
直近会話:
{recent}

今回の相手発言:
{user_text}

直近の自分の返答（繰り返し禁止）:
{recent_bot}

発火したtriggerと関連エピソード/語録:
{trigger_block}

検索された近い「文脈→橋本新返答」:
{pairs}

関連する本人発言:
{messages}

橋本新として自然に返答。triggerがある場合は、それをちゃんと拾う。
"""
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str:
        context = self.context(chat_id, user_text)
        hits = self.retriever.search(context, user_text=user_text)

        print(
            "retrieval",
            f"triggers={[h['trigger'] for h in hits.get('trigger_hits', [])]}",
            f"pairs={len(hits['pairs'])}",
            f"messages={len(hits['messages'])}",
            f"scores={hits.get('pair_scores', [])[:3]}",
            flush=True,
        )

        if not self.groq_available():
            print("generation path: emergency_local_cooldown", flush=True)
            answer = self.emergency_reply(user_text, hits)
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
                print("generation path: groq_bad_cleaned_using_emergency", flush=True)
                answer = self.emergency_reply(user_text, hits)
            else:
                print("generation path: groq", flush=True)

        except Exception as e:
            print("Groq error:", repr(e), flush=True)
            if "429" in str(e) or "rate_limit" in str(e) or "TPD" in str(e):
                self.disable_groq()
            print("generation path: emergency_local_exception", flush=True)
            answer = self.emergency_reply(user_text, hits)

        self.remember_user(chat_id, user_text)
        self.remember_bot(chat_id, answer)
        return answer
