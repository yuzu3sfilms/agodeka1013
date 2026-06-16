from openai import OpenAI
import config
from text_utils import load_text, context_to_text
from data_store import HashimotoArataDataStore
from anti_echo import finalize, fallback_reply


class HashimotoArataBot:
    def __init__(self):
        self.client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)
        self.identity_prompt = load_text(config.IDENTITY_PROMPT_FILE)
        self.store = HashimotoArataDataStore()

    def compact_reply_pairs(self, pairs: list[dict]) -> str:
        blocks = []
        for p in pairs[:config.TOP_REPLY_PAIRS]:
            ctx = context_to_text(p.get("context", [])[-2:])
            reply = (p.get("reply", "") or "").strip()
            if not reply:
                continue
            blocks.append(f"文脈:{ctx}\n返答:{reply}")
        return "\n---\n".join(blocks) if blocks else "なし"

    def compact_messages(self, messages: list[dict]) -> str:
        lines = []
        for m in messages[:config.TOP_MESSAGES]:
            text = (m.get("text", "") or "").strip()
            if text:
                lines.append(text[:120])
        return "\n".join(lines) if lines else "なし"

    def build_prompt(self, user_text: str, context_text: str) -> tuple[str, str, dict]:
        found = self.store.search(context_text)
        matched = "、".join(found["matched_words"][:12]) if found["matched_words"] else "なし"
        reply_pairs = self.compact_reply_pairs(found["reply_pairs"])
        messages = self.compact_messages(found["messages"])
        styles = "\n".join(found["style_examples"][:config.TOP_STYLE]) if found["style_examples"] else "なし"

        # identity_promptは長くなりがちなので、最初の1200字だけ使う。
        identity = (self.identity_prompt or "")[:1200]

        system = identity + """

# Runtime rules: AI橋本新 low-token
あなたは橋本 新（はしもと あらた）のLINE上の振る舞いを過去ログに基づいて模倣する。
便利AIではない。人格を分けない。わざとズラさない。
最優先は「似た過去文脈→本人返答」の構造・長さ・語尾・テンション。
おうむ返し、ChatGPT風説明、助言、箇条書きは禁止。
返答はLINEの一発言。短く、1〜2文。
"""

        recent = "\n".join(context_text.splitlines()[-config.HISTORY_LEN:])
        user = f"""
直近:{recent}
今回:{user_text}
一致語:{matched}
似た過去文脈→本人返答:
{reply_pairs}
同話題発言:
{messages}
文体例:
{styles}

橋本新として自然に短く返す。入力文をコピーしない。
"""
        return system, user, found

    def local_reply_from_data(self, user_text: str, found: dict | None = None) -> str:
        """
        GroqのTPD/429時の無料ローカル返答。
        LLMを呼ばず、最も近い過去返答をそのまま短く返す。
        """
        if found is None:
            found = self.store.search(user_text)

        for p in found.get("reply_pairs", []):
            rep = (p.get("reply", "") or "").strip()
            if rep:
                return finalize(user_text, rep)

        for m in found.get("messages", []):
            txt = (m.get("text", "") or "").strip()
            if txt:
                return finalize(user_text, txt)

        for s in found.get("style_examples", []):
            if s and s.strip():
                return finalize(user_text, s.strip())

        return fallback_reply(user_text)

    def is_rate_limit_error(self, error: Exception) -> bool:
        msg = repr(error).lower()
        return "429" in msg or "rate limit" in msg or "rate_limit" in msg or "tokens per day" in msg

    def generate_reply(self, user_text: str, context_text: str) -> str:
        system, user, found = self.build_prompt(user_text, context_text)
        try:
            response = self.client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
            )
            raw = response.choices[0].message.content or ""
            return finalize(user_text, raw)
        except Exception as e:
            print("Groq error:", repr(e))
            if config.USE_LOCAL_FALLBACK_ON_RATE_LIMIT and self.is_rate_limit_error(e):
                return self.local_reply_from_data(user_text, found)
            return fallback_reply(user_text)
