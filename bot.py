import os
import time
from collections import defaultdict, deque

from openai import OpenAI

from dynamic_search import DynamicSearch
from utils import clean_reply, normalize, de_ai_tone


ERROR_FALLBACK = "ｷｬﾋﾟｨ"
CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA", "LIAR", "ARAKUN"]


class HashimotoArataBot:
    def __init__(self):
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.max_tokens = int(os.environ.get("MAX_TOKENS", "120"))
        self.temperature = float(os.environ.get("TEMPERATURE", "1.05"))
        self.history_len = int(os.environ.get("HISTORY_LEN", "4"))
        self.cooldown_seconds = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
        self.groq_disabled_until = 0.0

        self.client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )

        self.searcher = DynamicSearch()
        self.histories = defaultdict(lambda: deque(maxlen=self.history_len))
        self.last_bot_replies = defaultdict(lambda: deque(maxlen=5))

    def remember_user(self, chat_id: str, text: str):
        self.histories[chat_id].append(text)

    def remember_bot(self, chat_id: str, text: str):
        if text:
            self.last_bot_replies[chat_id].append(text)

    def context(self, chat_id: str, user_text: str) -> str:
        return "\n".join(list(self.histories[chat_id]) + [user_text])

    def called_directly(self, user_text: str) -> bool:
        nt = normalize(user_text)
        return any(normalize(t) in nt for t in CALL_TERMS)

    def groq_available(self) -> bool:
        return time.time() >= self.groq_disabled_until

    def disable_groq(self):
        self.groq_disabled_until = time.time() + self.cooldown_seconds

    def build_prompt(self, user_text: str, context: str, search_result: dict, chat_id: str):
        episode_block = self.searcher.format_episodes(search_result)
        style_block = self.searcher.format_style(search_result)
        terms = ", ".join(search_result.get("terms", [])[:14])
        recent = "\n".join(context.splitlines()[-self.history_len:])
        recent_bot = "\n".join(self.last_bot_replies[chat_id]) or "なし"

        system = """
あなたはLINEグループにいた「橋本新」を模倣するAI。
過去LINEログ全文検索で見つかったエピソードを材料に返答する。
ただし、説明AIになってはいけない。

禁止:
- 丁寧な解説
- 「〜だよね」「〜なんだよね」「〜します」「〜ます！」「気を付けて」
- 一般知識の説明
- ChatGPT風のまとめ
- ユーザー発言のオウム返し
- 怒り・罵倒・攻撃

やること:
- エピソード内の出来事・語を1つ拾う
- 下の「口調サンプル」の温度感・短さ・雑さに寄せる
- 返答は1文、長くても2文
- 句点や感嘆符を使いすぎない
""".strip()

        user = f"""
今回の発言:
{user_text}

抽出検索語:
{terms}

直近会話:
{recent}

直近の自分の返答:
{recent_bot}

過去ログ全文検索でヒットした発言・エピソード:
{episode_block}

口調サンプル:
{style_block}

橋本新として返答。説明ではなく、LINEの会話として返す。
""".strip()
        return system, user

    def reply(self, chat_id: str, user_text: str) -> str | None:
        context = self.context(chat_id, user_text)
        result = self.searcher.search(user_text)
        called = self.called_directly(user_text)

        print(
            "dynamic_search",
            f"terms={result.get('terms', [])[:12]}",
            f"hits={len(result.get('hits', []))}",
            f"episodes={len(result.get('episodes', []))}",
            f"called={called}",
            flush=True,
        )

        if not result.get("episodes"):
            self.remember_user(chat_id, user_text)
            if called:
                print("generation path: no_episode_called_capyi", flush=True)
                answer = ERROR_FALLBACK
                self.remember_bot(chat_id, answer)
                return answer
            print("generation path: no_episode_ignore", flush=True)
            return None

        if not self.groq_available():
            print("generation path: groq_cooldown_capyi", flush=True)
            answer = ERROR_FALLBACK
            self.remember_user(chat_id, user_text)
            self.remember_bot(chat_id, answer)
            return answer

        try:
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

            if not answer or answer in set(self.last_bot_replies[chat_id]):
                print("generation path: groq_bad_capyi", flush=True)
                answer = ERROR_FALLBACK
            else:
                print("generation path: groq_dynamic_episode", flush=True)

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
