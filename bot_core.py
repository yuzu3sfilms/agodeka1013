import time
from openai import OpenAI
import config
from text_utils import load_text, context_to_text
from data_store import HashimotoArataDataStore
from anti_echo import finalize_reply, fallback_reply


class HashimotoArataBot:
    def __init__(self):
        self.client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)
        self.identity_prompt = load_text(config.IDENTITY_PROMPT_FILE)
        self.store = HashimotoArataDataStore()
        self.groq_disabled_until = 0.0

    def _log(self, *args):
        if config.DEBUG_LOG:
            print(*args)

    def compact_reply_pairs(self, pairs: list[dict]) -> str:
        blocks = []
        for p in pairs[:config.TOP_REPLY_PAIRS]:
            ctx = context_to_text(p.get("context", [])[-2:])
            reply = (p.get("reply", "") or "").strip()
            if reply:
                blocks.append(f"文脈:{ctx}\n返答:{reply}")
        return "\n---\n".join(blocks) if blocks else "なし"

    def compact_messages(self, messages: list[dict]) -> str:
        lines = []
        for m in messages[:config.TOP_MESSAGES]:
            text = (m.get("text", "") or "").strip()
            if text:
                lines.append(text[:100])
        return "\n".join(lines) if lines else "なし"

    def build_prompt(self, user_text: str, context_text: str):
        found = self.store.search(context_text)
        matched = "、".join(found["matched_words"][:10]) if found["matched_words"] else "なし"
        reply_pairs = self.compact_reply_pairs(found["reply_pairs"])
        messages = self.compact_messages(found["messages"])
        styles = "\n".join(found["style_examples"][:config.TOP_STYLE]) if found["style_examples"] else "なし"
        identity = (self.identity_prompt or "")[:800]
        system = identity + """

# Runtime rules: AI橋本新 low-token
橋本 新（はしもと あらた）のLINE上の振る舞いを過去ログに基づいて模倣する。
便利AIではない。人格を分けない。わざとズラさない。
近い過去文脈→本人返答を最優先。おうむ返し、ChatGPT風説明、助言、箇条書きは禁止。
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

    def is_rate_limit_error(self, error: Exception) -> bool:
        msg = repr(error).lower()
        return "429" in msg or "rate limit" in msg or "rate_limit" in msg or "tokens per day" in msg or "tpd" in msg

    def generate_reply(self, user_text: str, context_text: str) -> str:
        found = self.store.search(context_text)
        local = finalize_reply(user_text, self.store.local_reply(context_text, user_text, found))
        if time.time() < self.groq_disabled_until:
            self._log("Groq cooldown active; local reply")
            return local
        try:
            system, user, _found2 = self.build_prompt(user_text, context_text)
            response = self.client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
            )
            raw = response.choices[0].message.content or ""
            return finalize_reply(user_text, raw)
        except Exception as e:
            print("Groq error:", repr(e))
            if self.is_rate_limit_error(e):
                self.groq_disabled_until = time.time() + config.RATE_LIMIT_COOLDOWN_SECONDS
            return local or fallback_reply(user_text)
