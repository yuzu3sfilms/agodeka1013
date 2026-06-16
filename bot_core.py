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

    def format_reply_pairs(self, pairs: list[dict]) -> str:
        blocks = []
        for p in pairs:
            ctx = context_to_text(p.get("context", []))
            reply = p.get("reply", "")
            speaker = p.get("speaker", "橋本新")
            blocks.append(f"[過去文脈]\n{ctx}\n[橋本新の返答: {speaker}]\n{reply}")
        return "\n\n".join(blocks) if blocks else "なし"

    def format_messages(self, messages: list[dict]) -> str:
        lines = []
        for m in messages:
            src = m.get("source", "")
            speaker = m.get("speaker", "橋本新")
            text = m.get("text", "")
            lines.append(f"{speaker}({src}): {text}")
        return "\n".join(lines) if lines else "なし"

    def build_prompt(self, user_text: str, context_text: str) -> tuple[str, str]:
        found = self.store.search(context_text)
        matched = "、".join(found["matched_words"]) if found["matched_words"] else "なし"
        reply_pairs = self.format_reply_pairs(found["reply_pairs"])
        messages = self.format_messages(found["messages"])
        styles = "\n".join(found["style_examples"]) if found["style_examples"] else "なし"

        system = self.identity_prompt + """

# Runtime rules
あなたは「AI橋本新」。便利AIではない。
このLINEグループにかつていた橋本 新（はしもと あらた）という人物のLINE上の振る舞いを、過去ログとExcelデータに基づいて可能な限り忠実に模倣して演じ切る。

呼び名について:
「橋本新」「橋本」「あらた」「あらくん」「顎」「AGODEKA」などは同じ人物への呼び名であり、人格を分けない。

最優先:
1. 似た過去文脈→橋本新の返答ペアがある場合、その返答の構造・長さ・テンション・語尾を最優先で真似る。
2. 同じ話題の過去発言がある場合、その内容・語彙を自然に反映する。
3. 近い例がない場合は、文体例から平均的な橋本新のLINE文体で自然に返す。

禁止:
- ユーザー発言のおうむ返し。
- ChatGPT風の説明、助言、箇条書き。
- 人格を分けること。
- わざとズレたBotにすること。
- 語録を文脈無視で差し込むこと。
- 本人の現在の所在・予定・私生活を事実として断定すること。

出力:
LINEの一発言として返す。原則短め。1〜3文。
"""

        recent = "\n".join(context_text.splitlines()[-config.HISTORY_LEN:])
        user = f"""
直近の会話:
{recent}

今回のユーザー発言:
{user_text}

一致した過去ログ/Excel由来ワード:
{matched}

最重要: 似た過去文脈→橋本新返答ペア:
{reply_pairs}

同話題の橋本新発言:
{messages}

文体例:
{styles}

出力:
橋本 新として自然に返す。ユーザー発言をコピーしない。
"""
        return system, user

    def generate_reply(self, user_text: str, context_text: str) -> str:
        system, user = self.build_prompt(user_text, context_text)
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
            return fallback_reply(user_text)
