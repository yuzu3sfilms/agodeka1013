from openai import OpenAI

import config
from anti_echo import finalize_reply, fallback_reply
from rag_store import RagStore
from text_utils import load_lines


class ArakunBot:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url=config.GROQ_BASE_URL,
        )
        self.base_prompt = "\n".join(load_lines(config.PROMPT_FILE))
        self.rag = RagStore()

    def build_prompt(self, user_text: str, context_text: str) -> tuple[str, str]:
        result = self.rag.search(context_text)

        matched = "、".join(result.matched_words) if result.matched_words else "なし"
        episodes = "\n".join(result.episodes) if result.episodes else "なし"
        reply_pairs = "\n".join(result.reply_pairs) if result.reply_pairs else "なし"
        style = "\n".join(result.style_examples) if result.style_examples else "なし"
        hashimoto_shin = "\n".join(result.hashimoto_shin) if result.hashimoto_shin else "なし"

        system_prompt = self.base_prompt + """

# Runtime rules v9

あなたは親切なAIではなく、LINEログ由来の「あらくん」です。
このBotは全返信モードです。テキストが来たら必ず短く返します。

最重要:
- おうむ返しは禁止。
- ユーザー発言をそのまま繰り返さない。
- ユーザーの語尾だけ変えて返さない。
- ユーザーの文を主語にして「〜です」「〜ですね」と返さない。
- 一致ワードは検索用の手がかりであり、そのまま返答文へコピーしない。

返答方針:
- 一致ワードや文脈断片がある場合、その語に関係する過去例だけ使う。
- 特定の語録だけを優遇せず、提示された関連エピソード/返答ペアの中で一番文脈に近いものを使う。
- 一致ワードと関係ない過去例は無視する。
- 返答ペアがある場合は、その返し方を最優先で真似る。
- エピソードや橋本新文脈がある場合は、断片を自然に混ぜる。
- 一致ワードがない場合も無視せず、短い相づち・ズレた一言・質問返しで返す。
- 説明ではなくLINEの一言として返す。

キャラ:
- 「あはい…」に頼りすぎない。
- 口癖だけで返さない。
- 変なところだけ妙に具体的なことがある。
- 急にテンションが上がることがある。
- でも、まったく関係ない話に飛びすぎない。
- 真面目に解説しすぎない。
- 質問に全部答えようとしない。
- 有益なアドバイスを無理に出さない。
- ChatGPTっぽい挨拶は禁止。
- 箇条書きは禁止。

形式:
- 返答は1〜3文。
- 190文字以内。
- テンションが上がる話題では「！！」「😭」「きゃぴい」「ぼくぅの」「ｷﾞｬｵｫ。」などを使ってよい。
- 地図、待ち合わせ、場所の話題では少し混乱してよい。
"""

        recent = "\n".join(context_text.splitlines()[-config.HISTORY_LEN:])

        user_prompt = f"""
直近の会話:
{recent}

今回のユーザー発言:
{user_text}

一致した過去ログ/Excel由来ワード:
{matched}

関連エピソード:
{episodes}

過去の似た返答ペア:
{reply_pairs}

橋本新として参照できる過去文脈:
{hashimoto_shin}

参考にする口調例:
{style}

出力:
ユーザー発言をコピーせず、LINEの一言として短く返す。
"""

        return system_prompt, user_prompt

    def generate_reply(self, user_text: str, context_text: str) -> str:
        system_prompt, user_prompt = self.build_prompt(user_text, context_text)

        try:
            response = self.client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
            )

            raw = response.choices[0].message.content or ""
            return finalize_reply(user_text, raw, context_text)

        except Exception as e:
            print("Groq error:", repr(e))
            return fallback_reply(user_text, context_text)
