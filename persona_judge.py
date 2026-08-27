import json
import re
from pathlib import Path

from utils import normalize
from persona_policy import PersonaPolicy
from behavior_taxonomy import classify_reply, classify_stimulus


ASSERTION_WORDS = [
    "好き", "嫌い", "すき", "きらい", "苦手", "得意",
    "予定", "つもり", "食べました", "食べたこと", "行ったこと",
    "はず", "絶対", "いつも", "普段",
]

BAD_GENERATED_FRAGMENTS = [
    "だわか", "んだわか", "だわか？", "んだわか？",
]


def _looks_cut_midword(text: str) -> bool:
    """Conservative backup guard for obviously cut generated fragments.

    Avoid rejecting normal casual Japanese without punctuation. Only flag a
    trailing kanji stem that is very likely the start of a longer verb/noun
    when the candidate is sentence-like and has no terminal punctuation.
    """
    t = (text or "").strip()
    if not t or re.search(r"[。！？!?…〜～♪♫♡♥☆]$", t):
        return False
    if len(t) < 8:
        return False
    # A final single kanji immediately following Japanese prose is a common
    # token-limit truncation shape (e.g. "...見落"). Keep this deliberately
    # narrow; finish_reason handling in bot.py is the primary guard.
    return bool(re.search(r"[ぁ-んァ-ヴ一-龥々ー][一-龥]$", t))


def _dialogue_act(text: str) -> str:
    t = text or ""
    if re.search(r"^(?:おい|ねえ|ねぇ|なあ|なぁ|ちょっと).*(?:顎|橋本|あらくん)?[！!。]*$", t):
        return "call"
    if re.search(r"何個|何人|何枚|何回|いくつ|何本|何杯", t):
        return "count_question"
    if re.search(r"どこ|何処", t):
        return "location_question"
    if re.search(r"なんで|なぜ|何故", t):
        return "reason_question"
    if re.search(r"[？?]", t):
        return "question"
    return "statement"


def _candidate_act_matches(candidate: str, user_text: str) -> bool:
    act = _dialogue_act(user_text)
    c = candidate or ""
    if act == "call":
        return bool(re.search(r"なん|何|なに|どうした|用|はい|あはい", c))
    if act == "count_question":
        return bool(re.search(r"[0-9０-９]+", c))
    if act == "location_question":
        return bool(re.search(r"ここ|そこ|あそこ|右|左|上|下|前|後ろ|中|外|わから|分から|知らな", c))
    if act == "reason_question":
        return bool(re.search(r"から|ので|せい|ため|わから|分から|知らな", c))
    if act == "question":
        return bool(re.search(
            r"はい|うん|そう|ある|ない|いる|いない|いそう|ありそう|"
            r"思う|思わ|感じ|面白|興味|好き|嫌い|苦手|怖|すご|微妙|"
            r"かも|強|弱|増|減|変わ|芽生|"
            r"わから|分から|知らな|たぶん|多分|まあ|別に|まだ|もう",
            c,
        ))
    return True


ATTRIBUTION_RE = re.compile(
    r"(?:誰か|みんな|みんなで|[一-龥ァ-ヴA-Za-z0-9_]{1,20})(?:が|は)?"
    r"(?:言ってた|言ってる|話してた|話してる|聞いた|言った|"
    r"取られた|見た|いたって|いるって)"
)

COMMON_GENERATION_WORDS = {
    "宇宙人", "人類", "自分", "相手", "今日", "明日", "昨日",
    "そう", "たぶん", "多分", "いる", "いない", "ある", "ない",
    "思う", "思って", "みたい", "怖い", "好き", "嫌い",
}


def _episode_speakers(search_result: dict) -> set[str]:
    speakers = set()
    for line in "\n".join(
        (episode.get("window", "") or "")
        for episode in search_result.get("episodes", []) or []
    ).splitlines():
        if ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if 1 <= len(name) <= 32:
            speakers.add(name)
    return speakers


def _grounding_text(user_text: str, search_result: dict) -> str:
    parts = [
        user_text or "",
        search_result.get("generation_grounding_text", "") or "",
        " ".join(search_result.get("topic_terms", []) or []),
        " ".join(search_result.get("predicates", []) or []),
        str(
            (search_result.get("conversation_state") or {}).get(
                "resolved_subject", ""
            )
        ),
    ]
    return "\n".join(x for x in parts if x)


def _episode_only_tokens(candidate: str, user_text: str, search_result: dict):
    episode = "\n".join(
        (episode.get("window", "") or "")
        for episode in search_result.get("episodes", []) or []
    )
    if not episode:
        return []

    grounding = normalize(_grounding_text(user_text, search_result))
    episode_n = normalize(episode)

    tokens = re.findall(
        r"[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|"
        r"[一-龥々〆ヵヶ]{2,}",
        candidate or "",
    )
    out = []
    for token in tokens:
        nt = normalize(token)
        if not nt or len(nt) < 2:
            continue
        if token in COMMON_GENERATION_WORDS:
            continue
        if nt in grounding:
            continue
        if nt in episode_n and token not in out:
            out.append(token)
    return out


WH_QUESTION_RE = re.compile(
    r"何|なに|誰|だれ|どこ|いつ|どれ|どっち|どの|"
    r"なんで|なぜ|何故|どうして|いくつ|何回|何人|何個"
)

DIRECT_ANSWER_PREDICATE_RE = re.compile(
    r"(?:いる|いない|ある|ない|思う|思って|好き|嫌い|"
    r"なった|変わった|増えた|減った|良くなった|悪くなった)"
)


def _requires_direct_answer_gate(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not re.search(r"[？?]", text):
        return False
    if WH_QUESTION_RE.search(text):
        if re.search(r"どう思う", text):
            return True
        return False
    return bool(DIRECT_ANSWER_PREDICATE_RE.search(text))


SELF_ALIAS_RE = re.compile(
    r"(?:お前|おまえ|あんた|橋本|橋本新|あらくん|アラクン|顎|AGO|ago)"
)

# v14.41 — first-person pronouns in the user's utterance refer to the user,
# not to AGO and not to an arbitrary external entity.
USER_SELF_PRONOUN_RE = re.compile(
    r"(?:^|[、。！？?\s])(?:俺|おれ|僕|ぼく|私|わたし|自分)(?:のこと|の|は|って|を|に|が|$)"
)

SELF_STATE_RE = re.compile(
    r"(?:自我|意思|意志|感情|人格|心|意識|自分で考|自分の考え|"
    r"自我が|芽生え|目覚め|成長した|進化した)"
)

EPISTEMIC_DEFERRAL_RE = re.compile(
    r"(?:証拠|確証|確定した情報|確認され|見つかっていな|"
    r"可能性はゼロ|現時点では|今のところ|興味深い話題|"
    r"確かめるのは|科学的には|一般的には)"
)

PERSONAL_LEAN_RE = re.compile(
    r"(?:と思う|気がする|かも|いそう|ありそう|たぶん|多分|"
    r"まあ|別に|好き|嫌い|面白|興味|怖|苦手|微妙|わから)"
)

SELF_STATE_ANSWER_RE = re.compile(
    r"(?:ある|ない|まだ|もう|芽生|変わ|増え|減っ|強く|"
    r"思う|感じ|わから|分から|たぶん|多分|まあ|別に)"
)


def _question_like(text: str) -> bool:
    return bool(re.search(r"[？?]", text or ""))


def _strip_discourse_prefix(text: str) -> str:
    return re.sub(
        r"^(?:じゃあ|じゃ|てか|というか|つか|で、?|んで、?)\s*",
        "",
        (text or "").strip(),
    )


# v14.35 — Reality/Canon + audited value-orientation layer.
# These are not topic-specific opinions. They describe *how* Hashimoto tends
# to evaluate things in the corpus: concrete, personal, understated, sometimes
# oddly specific; not abstract LLM commentary.


SURFACE_CORRUPTION_RE = re.compile(
    r"(?:と思いる|と思いるわ|できませんる|できまする|"
    r"ありませんる|ますだわ|ですだわ|不明だわ$)"
)


# v14.38 — semantic answer completeness.
# A candidate may be short, but it must actually answer the current question.
DANGLING_DEICTIC_RE = re.compile(
    r"(?:^|[、。！？\s])(?:"
    r"そうだ|そうです|そう思う|そんな感じ|そういう感じ|そうかも|"
    r"それかな|それだと思う|ざっくり言えばそう"
    r")(?:[。！？\s]|$)"
)

LOW_INFORMATION_OPINION_RE = re.compile(
    r"^(?:別に)?(?:どうでもいい|よく分からない|わからない|分からない)"
    r"(?:んだけど|けど|かな|ね|よ)?[。！？]?$"
)

# v14.41 — forms such as 「別に、思ってない」 are grammatically possible
# fragments but do not supply the evaluation requested by 「どう思ってる？」.
# Reject only narrow meta-predicate nonanswers; terse evaluations such as
# 「微妙」「別に」「よく分からない」 remain available.
OPINION_META_NONANSWER_RE = re.compile(
    r"^(?:別に[、, ]*)?(?:特に[、, ]*)?(?:何も[、, ]*)?"
    r"(?:思って(?:い)?ない|思わない|考えて(?:い)?ない)"
    r"(?:よ|ね|かな)?[。！？]?$"
)

ABSTRACT_EVALUATION_RE = re.compile(
    r"(?:多様|創造力|欠点|存在だ|存在で|豊かだ|豊かで|社会|文明|"
    r"本質|普遍|複雑な存在|興味深い|未知だ|可能性を秘め|"
    r"混乱も招く|感情が豊か|成長したい|人間性|価値観|未来を|世界を)"
)

CONCRETE_EVALUATION_RE = re.compile(
    r"(?:好き|嫌い|嫌いじゃ|好きじゃ|面白|おもしろ|怖|こわ|"
    r"微妙|良い|いい|すご|やば|別に|なんとも|よくわから|"
    r"分から|気がする|と思う|かな|かも)"
)

AI_SELF_AWARENESS_ASSERT_RE = re.compile(
    r"(?:自我|意識|感情|心|意思|意志).{0,10}"
    r"(?:芽生えた|芽生えて|ある|持ってる|持っている|生まれた|"
    r"感じてる|感じている|目覚めた)"
)

AI_SELF_AWARENESS_NEGATED_RE = re.compile(
    r"(?:自我|意識|感情|心|意思|意志).{0,12}"
    r"(?:ない|とは言えない|わからない|分からない|よくわから)"
)

AI_SELF_CHANGE_ASSERT_RE = re.compile(
    r"(?:自分|ぼく|俺|AGO|あらくん)?.{0,6}"
    r"(?:変化はある|変わってきた|成長した|進化した|"
    r"芽生えたような気がする|少しは芽生え)"
)

REALITY_SAFE_SELF_RE = re.compile(
    r"(?:よくわからない|分からない|わからない|"
    r"判断でき(?:ない|ません)|自我があるとは言えない|"
    r"自分ではわからない|なんとも言えない|何とも言えない|断定できない)"
)


SELF_STATE_UNKNOWN_RE = re.compile(
    r"(?:判断でき(?:ない|ません)|自分では(?:よく)?わから|"
    r"(?:よく)?わからない|分からない|なんとも言えない|"
    r"あるとは言えない|断定できない|何とも言えない)"
)

SELF_STATE_NEGATIVE_RE = re.compile(
    r"(?:自我|意識|感情|心|意思|意志)?.{0,8}"
    r"(?:ない|芽生えていない|芽生えはしてない|持っていない)"
)

SELF_STATE_POSITIVE_RE = re.compile(
    r"(?:自我|意識|感情|心|意思|意志)?.{0,8}"
    r"(?:ある|芽生えた|芽生えている|目覚めた|持っている)"
)

VAGUE_NONANSWER_RE = re.compile(
    r"^(?:そういう意味ではない|そういうことではない|"
    r"それとは違う|なんのこと|どういう意味)[。.!！?？]*$"
)

LOW_COMMITMENT_OPINION_RE = re.compile(
    r"(?:別に|なんとも|何とも|よくわから|分から|わから|"
    r"特に(?:ない|思わない)|どっちでも|人による|"
    r"そこまで|まあ.*(?:かな|かも|と思う))"
)

STRONG_PERSONAL_OPINION_RE = re.compile(
    r"(?:大嫌い|嫌い|大好き|好き|怖い|こわい|"
    r"やばい|ヤバい|面白い|おもしろい|すごい|"
    r"気持ち悪い|最高|最悪)"
)

HASHIMOTO_SPEAKERS = {
    "橋本新", "あらくん", "LIAR OF ARAKUN",
    "LIAR  OF  ARAKUN", "Unknown", "Arata Hashimoto",
}


def _self_state_answer_class(text: str) -> str:
    """Return affirmative / negative / unknown / nonanswer."""
    c = (text or "").strip()
    if VAGUE_NONANSWER_RE.search(c):
        return "nonanswer"
    if SELF_STATE_UNKNOWN_RE.search(c):
        return "unknown"
    if SELF_STATE_POSITIVE_RE.search(c) and not SELF_STATE_NEGATIVE_RE.search(c):
        return "affirmative"
    if SELF_STATE_NEGATIVE_RE.search(c):
        return "negative"
    return "nonanswer"


def _reality_profile_for(behavior: dict) -> dict:
    """What AGO can and cannot claim as literal reality."""
    subject_role = (behavior or {}).get("subject_role", "")
    family = (behavior or {}).get("question_family", "")
    if subject_role == "assistant_self" and family == "self_state":
        return {
            "kind": "ai_self_state",
            "must_not_assert": (
                "自我・意識・感情が実在する、芽生えた、成長した等を"
                "内省的事実として断定しない"
            ),
            "allowed": (
                "分からない／そういう意味ではない／自分では判断できない"
                "など、事実を作らない返し"
            ),
        }
    return {
        "kind": "ordinary",
        "must_not_assert": "",
        "allowed": "",
    }


def _value_orientation_for(behavior: dict) -> dict:
    """Audited corpus orientation, independent of topic-specific belief."""
    mode = (behavior or {}).get("mode", "ordinary_direct")
    stance = ((behavior or {}).get("stance") or {}).get("kind", "direct")

    if mode == "playful_worldbuild":
        return {
            "style": "concrete_absurd_extension",
            "guidance": (
                "共有された変な前提を否定せず、そこから具体的な設定を一段だけ発展させる。"
                "抽象的な哲学や一般論にしない。"
            ),
        }
    if stance in {"personal_evaluation", "personal_hunch"}:
        return {
            "style": "concrete_personal_evaluation",
            "guidance": (
                "抽象評論ではなく、好き・嫌い・微妙・怖い・面白い・別に・"
                "よく分からない・〜と思う等の本人目線の具体評価を優先する。"
                "必要以上に立派な理由を付けない。"
            ),
        }
    if mode == "knowledge_explainer":
        return {
            "style": "specific_practical_explanation",
            "guidance": (
                "一般論を飾るより、条件・回数・具体例など実用的な具体性を優先する。"
            ),
        }
    if mode == "practical_clarification":
        return {
            "style": "specific_confirmation",
            "guidance": "場所・時間・条件を具体的に確認する。",
        }
    return {
        "style": "plain_concrete",
        "guidance": (
            "抽象的にまとめず、その場の対象について普通に具体的に返す。"
        ),
    }


class PersonaJudge:
    """
    Generated-candidate judge.

    Historical Replay length is handled by ActualReplyEngine and is length-neutral.
    This judge still keeps generated replies compact, but dialogue-act and grounding
    now outrank compactness.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.profile = self._load_json(
            self.data_dir / "hashimoto_persona_profile.json",
            {},
        )
        self.topic_canon = self._load_json(
            self.data_dir / "topic_canon_profile.json",
            {},
        )
        # v15.0: primary LINE audit outranks the legacy v13 "forbidden" list.
        # The raw corpus contains ordinary polite endings very frequently
        # ("です", "ます", "ですね", "と思います"), so banning them was
        # actively deleting authentic Hashimoto behaviour.
        self.forbidden = ["AIとして", "私はAI", "だぜ"]
        # Audited 1-message units from the raw LINE corpus (Unknown + LIAR +
        # Arata Hashimoto + 橋本新; media excluded): median≈15, p75≈30, p90≈54.
        self.median_len = 15
        self.p75_len = 30
        self.p90_len = 54
        self.common_lines = [
            x.get("text", "")
            for x in self.profile.get("common_lines", [])[:120]
        ]
        self.persona_policy = PersonaPolicy(data_dir)

    def question_family(self, text: str) -> str:
        t = _strip_discourse_prefix((text or "").strip())
        if not re.search(r"[？?]", t):
            if re.fullmatch(r"(?:きゃぴ|ｷｬﾋﾟ|キャピ|きゃっ|ｷｬｯﾋﾟ[ｲｨ]?)[！!~〜～]*", t, re.I):
                return "burst"
            return "statement"
        if re.search(r"何個|何人|何枚|何回|何本|何杯|いくつ", t):
            return "count"
        if re.search(r"どこ|何処|場所|何口|何線", t):
            return "location"
        if SELF_STATE_RE.search(t):
            return "self_state"
        if re.search(r"何時|いつ|何分|何時半", t):
            return "time"
        if re.search(r"いくら|何円|値段|料金", t):
            return "amount"
        if re.search(r"どう思|どう感じ|どういう印象", t):
            return "opinion"
        if re.search(r"好き|嫌い|どっちが|どれが", t):
            return "preference"
        if re.search(r"したこと|行ったこと|食べたこと|経験|いつから|何歳", t):
            return "experience"
        if re.search(r"なんで|なぜ|何故|どうして", t):
            return "reason"
        if re.search(r"どういう|とは|って何|ってなに|意味|仕組み|教えて|説明", t):
            return "explanation"
        if re.search(r"何|なに|誰|だれ|どれ|どの|どう", t):
            return "open_wh"
        return "yesno"

    def resolve_subject_role(
        self,
        user_text: str,
        relation: dict | None = None,
    ) -> dict:
        """Resolve whether the question is about AGO itself or another subject.

        Explicit inherited subjects outrank vague self-state language, except
        when the utterance contains an intrinsic self-state concept such as
        「自我芽生えた？」.
        """
        relation = relation or {}
        text = _strip_discourse_prefix(user_text or "")
        resolved = str(relation.get("resolved_subject", "") or "").strip()
        inherited = bool(relation.get("subject_inherited"))

        intrinsic_self = bool(SELF_STATE_RE.search(text))
        explicit_self = bool(SELF_ALIAS_RE.search(text))

        if intrinsic_self or explicit_self:
            return {
                "subject_role": "assistant_self",
                "subject": "AGO_SELF",
                "reason": "explicit_or_intrinsic_self_reference",
            }

        # The speaker's first-person pronoun must resolve to the speaker.
        # relation.resolved_subject may literally be "俺"; treating that as an
        # external topic destroys relationship-aware opinion questions.
        if USER_SELF_PRONOUN_RE.search(text):
            return {
                "subject_role": "user_self",
                "subject": "USER_SELF",
                "reason": "user_first_person_reference",
            }

        if inherited and resolved:
            return {
                "subject_role": "inherited_external",
                "subject": resolved,
                "reason": "dialogue_subject_inherited",
            }

        if resolved:
            return {
                "subject_role": "external",
                "subject": resolved,
                "reason": "explicit_external_subject",
            }

        return {
            "subject_role": "external_or_unspecified",
            "subject": "",
            "reason": "no_self_reference",
        }

    def opinion_evidence(
        self,
        user_text: str,
        behavior: dict | None,
        search_result: dict | None,
    ) -> dict:
        """Find direct corpus evidence for a topic-specific personal opinion.

        Evidence is intentionally strict. A topic appearing somewhere in a
        scene is not enough. We look for either:
        1) a Hashimoto line that itself contains the subject + evaluative wording, or
        2) a preceding non-Hashimoto opinion/preference question about the
           subject followed immediately by Hashimoto's reply.
        """
        behavior = behavior or {}

        search_result = search_result or {}
        family = behavior.get("question_family", self.question_family(user_text))
        if family not in {"opinion", "preference", "experience"}:
            return {
                "level": "not_applicable",
                "direction": "",
                "examples": [],
                "reason": "not_personal_evaluation_question",
            }

        raw_subject = str(behavior.get("subject", "") or "")
        subject = _strip_discourse_prefix(raw_subject)
        topic_terms = [
            _strip_discourse_prefix(str(x))
            for x in (search_result.get("topic_terms", []) or [])
            if x
        ]
        # Explicit resolved subjects may legitimately be one kanji ("犬", "猫").
        # Keep the resolved subject even when length==1; retain the >=2 noise
        # filter only for automatically extracted topic terms.
        subject_terms = []
        if subject:
            subject_terms.append(subject)
        subject_terms.extend(x for x in topic_terms if len(x) >= 2)
        subject_terms = list(dict.fromkeys(subject_terms))

        examples = []
        directions = []

        def eval_direction(text: str) -> str:
            t = text or ""
            if re.search(r"嫌い|怖|こわ|苦手|気持ち悪|最悪", t):
                return "negative"
            if re.search(r"好き|面白|おもしろ|すご|良い|いい|最高", t):
                return "positive"
            if LOW_COMMITMENT_OPINION_RE.search(t):
                return "low_commitment"
            return "unclear"

        for episode in search_result.get("episodes", []) or []:
            window = episode.get("window", "") or ""
            lines = [line.strip() for line in window.splitlines() if ":" in line]
            for idx, line in enumerate(lines):
                speaker, content = line.split(":", 1)
                speaker = speaker.strip()
                content = content.strip()
                if speaker not in HASHIMOTO_SPEAKERS:
                    continue

                same_line_subject = any(term in content for term in subject_terms)
                same_line_eval = bool(
                    CONCRETE_EVALUATION_RE.search(content)
                    or LOW_COMMITMENT_OPINION_RE.search(content)
                )
                if same_line_subject and same_line_eval:
                    examples.append(content)
                    directions.append(eval_direction(content))
                    continue

                # Immediate historical stimulus -> Hashimoto reply.
                if idx > 0:
                    ps, pc = lines[idx - 1].split(":", 1)
                    ps = ps.strip()
                    pc = pc.strip()
                    if ps not in HASHIMOTO_SPEAKERS:
                        stimulus_mentions_subject = any(
                            term in pc for term in subject_terms
                        )
                        stimulus_family = self.question_family(pc)
                        if (
                            stimulus_mentions_subject
                            and stimulus_family in {"opinion", "preference", "experience"}
                        ):
                            examples.append(content)
                            directions.append(eval_direction(content))

        if not examples:
            return {
                "level": "none",
                "direction": "",
                "examples": [],
                "reason": "no_direct_topic_opinion_evidence",
            }

        clear = [x for x in directions if x in {"positive", "negative", "low_commitment"}]
        if clear:
            direction = max(set(clear), key=clear.count)
        else:
            direction = "unclear"

        return {
            "level": "direct",
            "direction": direction,
            "examples": examples[:4],
            "reason": "direct_hashimoto_topic_opinion_evidence",
        }

    def question_semantics(
        self,
        user_text: str,
        behavior: dict | None,
    ) -> dict:
        """Define what a valid answer must accomplish before style ranking."""
        behavior = behavior or {}
        family = behavior.get("question_family", self.question_family(user_text))
        subject_role = behavior.get("subject_role", "external_or_unspecified")

        if family == "self_state" and subject_role == "assistant_self":
            return {
                "required": "self_state_polarity",
                "valid_classes": ["affirmative", "negative", "unknown"],
                "preferred_classes": ["unknown"],
                "reason": "ai_self_state_requires_explicit_answer",
            }
        if family == "yesno":
            return {
                "required": "yesno_or_uncertainty",
                "valid_classes": ["affirmative", "negative", "unknown"],
                "preferred_classes": [],
                "reason": "yesno_requires_answer_before_style",
            }
        if family in {"opinion", "preference"}:
            return {
                "required": "personal_evaluation",
                "valid_classes": ["evaluation", "low_commitment"],
                "preferred_classes": [],
                "reason": "opinion_requires_personal_evaluation",
            }
        return {
            "required": "direct_relevance",
            "valid_classes": [],
            "preferred_classes": [],
            "reason": "ordinary_semantics",
        }

    def infer_stance(
        self,
        user_text: str,
        behavior: dict | None = None,
        search_result: dict | None = None,
        context: str = "",
    ) -> dict:
        """Infer the *kind* of internal stance required before wording.

        This does not invent a topic-specific belief. It controls how Hashimoto
        should form an answer: personal hunch, personal evaluation, self-state,
        clarification, explanation, or plain factual response.
        """
        behavior = behavior or {}
        family = behavior.get("question_family") or self.question_family(user_text)
        subject_role = behavior.get("subject_role", "external_or_unspecified")
        mode = behavior.get("mode", "ordinary_direct")
        text = _strip_discourse_prefix(user_text or "")

        if subject_role == "assistant_self" or family == "self_state":
            return {
                "kind": "self_state",
                "certainty": "introspective_cautious",
                "answer_policy": (
                    "AGO自身について聞かれている。ユーザーへ質問を反転せず、"
                    "まず自分側の状態として答える。仕組みや感情を捏造せず、"
                    "必要なら曖昧さを短く残す。"
                ),
            }

        if family in {"opinion", "preference", "experience"}:
            return {
                "kind": "personal_evaluation",
                "certainty": "subjective",
                "answer_policy": (
                    "一般論ではなく自分の評価・好み・感想として答える。"
                    "過去ログにない具体的経験は作らない。"
                ),
            }

        if family == "yesno" and re.search(
            r"(?:いる|ある|本当|ほんと|存在|できる|なる|思う)",
            text,
        ):
            return {
                "kind": "personal_hunch",
                "certainty": "low_to_medium",
                "answer_policy": (
                    "確証の有無を解説するより先に、本人としての単純な傾きを答える。"
                    "『いると思う』『いない気がする』『わからない』等の立場を先に出し、"
                    "証拠・科学・一般論の講釈は求められた時だけにする。"
                ),
            }

        if mode == "practical_clarification":
            return {
                "kind": "clarify",
                "certainty": "needs_context",
                "answer_policy": "不足情報があれば具体的に確認する。",
            }

        if mode == "knowledge_explainer":
            return {
                "kind": "explain",
                "certainty": "domain_reasoning",
                "answer_policy": "目的や条件に沿って具体的に説明する。",
            }

        return {
            "kind": "direct",
            "certainty": "ordinary",
            "answer_policy": "現在の問いへ普通に直接答える。",
        }

    def infer_behavior_state(
        self,
        user_text: str,
        context: str = "",
        search_result: dict | None = None,
        relation: dict | None = None,
        previous_mode: str = "",
    ) -> dict:
        """Infer Hashimoto's conversational action-state before wording.

        The modes come from the primary LINE audit: ordinary direct response,
        practical clarification, knowledge expansion, literal/serious uptake,
        playful world-building, defensive correction, self-disclosure, and
        rare high-energy burst. This is intentionally about *what he does*,
        not catchphrase substitution.
        """
        search_result = search_result or {}
        relation = relation or {}
        text = (user_text or "").strip()
        recent = "\n".join((context or "").splitlines()[-6:])
        family = self.question_family(text)
        subject_info = self.resolve_subject_role(text, relation)
        subject_role = subject_info["subject_role"]
        reasons = [f"subject:{subject_info['reason']}"]
        confidence = 0.66

        burst = bool(re.fullmatch(
            r"(?:きゃぴ|ｷｬﾋﾟ|キャピ|きゃっ|ｷｬｯﾋﾟ[ｲｨ]?|"
            r"ﾄﾞｻﾞﾜｻﾝ|ﾄﾐｻﾞﾜｻﾝ|ﾄﾞｲｸﾝ)[！!~〜～]*",
            text,
            re.I,
        ))
        logistics = family in {"count", "location", "time", "amount"} or bool(
            re.search(
                r"集合|待ち合わせ|着く|着いた|行けば|どこに|何時に|"
                r"場所|改札|駅|何線|いくら必要|いつ行",
                text,
            )
        )
        correction = bool(
            re.search(
                r"(?:お前|橋本|あらくん|顎).{0,18}"
                r"(?:言った|言ってた|好きだろ|嫌いだろ|嘘|ほんと|本当|"
                r"ホモ|壊れた|変わった|覚えてる)",
                text,
            )
        ) or relation.get("relation") == "repair_request"

        playful_cues = len(re.findall(
            r"ホモ|合体|サイボーグ|クローン|ポケモン|タイプ|必殺技|"
            r"人類.*計画|顎.*(?:砲|ビーム|星|帝国)|どいくん|とみざわさん|"
            r"ﾎﾓｫ|野生の",
            text + "\n" + recent,
            re.I,
        ))
        explicit_play = bool(re.search(
            r"もし.*(?:だったら|なら)|設定|世界線|進化|変身|合体|"
            r"ポケモン|必殺技|クローン|サイボーグ",
            text,
        ))

        topic_blob = " ".join(search_result.get("topic_terms", []) or []) + " " + text
        audited_explainer_domain = bool(re.search(
            r"筋トレ|トレーニング|スクワット|デッドリフト|デッド|"
            r"筋肉|プロテイン|たんぱく|タンパク|カロリー|増量|減量|"
            r"玩具|おもちゃ|フィギュア|プラモ|ウエイト",
            topic_blob,
            re.I,
        ))
        explainer_request = family in {"explanation", "reason", "open_wh"} or bool(
            re.search(r"どうやる|どうしたら|教えて|詳しく|何セット|何回", text)
        )

        self_disclosure = family in {"opinion", "preference", "experience"} or bool(
            re.search(r"お前は|橋本は|あらくんは|自分はどう", text)
        )
        self_state = subject_role == "assistant_self" or family == "self_state"
        serious = relation.get("relation") in {"repair_request"} or bool(
            re.search(r"ごめん|すみません|本気|冗談|怒って|大丈夫|困った|"
                      r"間違|勘違い|どうすれば", text)
        )

        if burst:
            mode = "playful_burst"
            confidence = 0.98
            reasons.append("rare_explicit_burst_cue")
        elif logistics:
            mode = "practical_clarification"
            confidence = 0.94
            reasons.append(f"practical_question:{family}")
        elif correction:
            mode = "defensive_correction"
            confidence = 0.88
            reasons.append("self_claim_or_repair")
        elif playful_cues >= 2 or explicit_play:
            mode = "playful_worldbuild"
            confidence = 0.86
            reasons.append("shared_absurd_premise")
        elif audited_explainer_domain and explainer_request:
            mode = "knowledge_explainer"
            confidence = 0.90
            reasons.append("audited_interest_domain_plus_explanation")
        elif self_state:
            mode = "self_state"
            confidence = 0.94
            reasons.append("assistant_self_state_question")
        elif self_disclosure:
            mode = "self_disclosure"
            confidence = 0.91
            reasons.append(f"personal_stance_question:{family}")
        elif serious:
            mode = "literal_serious"
            confidence = 0.82
            reasons.append("serious_or_repair_context")
        else:
            mode = "ordinary_direct"
            reasons.append("default_conversational_state")

        # A real state transition: follow-ups can stay in an activated mode.
        if (
            mode == "ordinary_direct"
            and relation.get("relation") in {"followup", "continuation_request"}
            and previous_mode in {
                "knowledge_explainer",
                "playful_worldbuild",
                "literal_serious",
                "defensive_correction",
            }
        ):
            mode = previous_mode
            confidence = max(confidence, 0.78)
            reasons.append(f"followup_state_persistence:{previous_mode}")

        result = {
            "mode": mode,
            "confidence": round(confidence, 2),
            "question_family": family,
            "subject_role": subject_role,
            "subject": subject_info.get("subject", ""),
            "reasons": reasons,
        }
        result["stance"] = self.infer_stance(
            user_text=text,
            behavior=result,
            search_result=search_result,
            context=context,
        )
        result["reality"] = _reality_profile_for(result)
        result["value_orientation"] = _value_orientation_for(result)
        result["question_semantics"] = self.question_semantics(text, result)
        result["opinion_evidence"] = self.opinion_evidence(
            user_text=text,
            behavior=result,
            search_result=search_result,
        )
        return result

    def behavior_instruction(self, behavior: dict | None) -> str:
        mode = (behavior or {}).get("mode", "ordinary_direct")
        instructions = {
            "ordinary_direct": (
                "普通に会話する。まず内容へ反応する。短さや語録を目的にしない。"
            ),
            "practical_clarification": (
                "場所・時間・金額・段取りは具体的に確認する。分からない情報を"
                "埋めず、必要なら追加で聞く。本人はこの場面では確認質問が増える。"
            ),
            "knowledge_explainer": (
                "得意・関心領域では短文縛りを解除する。目的を確認し、具体例や"
                "自分なりの理屈まで説明してよい。ただし知らない事実は作らない。"
            ),
            "literal_serious": (
                "冗談っぽい流れでも必要なら真面目に受け、説明・確認・謝罪をする。"
                "無理に面白くしない。"
            ),
            "playful_worldbuild": (
                "共有された馬鹿な前提を否定せず、その設定内部の論理を真顔で"
                "一段発展させる。単なるキャッチフレーズ反復にはしない。"
            ),
            "defensive_correction": (
                "自分について誤った決めつけをされたら、弱々しく受け流すだけでなく"
                "普通に訂正・否定してよい。"
            ),
            "self_disclosure": (
                "自分の意見・好み・感想を聞かれているので、その問いへ直接答える。"
                "過去ログにない具体的な経験談は捏造しない。"
            ),
            "self_state": (
                "AGO自身の状態について聞かれている。質問をユーザー側へ反転せず、"
                "まず自分について答える。自我・感情・意識の仕組みを勝手に設定しない。"
            ),
            "playful_burst": (
                "今の発言自体が高テンション語録モード。短い反応や同型のノリを"
                "許可するが、このモード以外へキャピ等を漏らさない。"
            ),
        }
        base = instructions.get(mode, instructions["ordinary_direct"])
        stance = (behavior or {}).get("stance") or {}
        stance_policy = stance.get("answer_policy", "")
        reality = (behavior or {}).get("reality") or {}
        value_orientation = (behavior or {}).get("value_orientation") or {}
        question_semantics = (behavior or {}).get("question_semantics") or {}
        opinion_evidence = (behavior or {}).get("opinion_evidence") or {}

        parts = [base]
        if stance_policy:
            parts.append(stance_policy)
        if reality.get("must_not_assert"):
            parts.append("Reality制約: " + reality["must_not_assert"] + "。")
        if reality.get("allowed"):
            parts.append("Reality上の許容: " + reality["allowed"] + "。")
        if value_orientation.get("guidance"):
            parts.append("価値判断の型: " + value_orientation["guidance"])
        if question_semantics.get("required"):
            parts.append(
                "Question Semantics: "
                + question_semantics["required"]
                + "。まず質問への回答成立を満たす。"
            )
        if opinion_evidence.get("level") == "none":
            parts.append(
                "Opinion Evidence: この対象への直接的な橋本の評価根拠は見つかっていない。"
                "強い好き嫌い・怖さ・面白さ等を新しく人格設定として作らず、"
                "低コミットメントな返答を優先する。"
            )
        elif opinion_evidence.get("level") == "direct":
            parts.append(
                "Opinion Evidence: 直接根拠あり。方向="
                + str(opinion_evidence.get("direction", ""))
                + "。過去発言の事実範囲を超えて膨らませない。"
            )
        return " ".join(parts)

    def _extract_historical_stimulus(self, hit: dict) -> str:
        scene = hit.get("source_scene", "") or ""
        reply = (hit.get("reply") or "").strip()
        if not scene or not reply:
            return ""
        lines = [line.strip() for line in scene.splitlines() if line.strip()]
        target_index = -1
        for idx, line in enumerate(lines):
            if reply in line and ":" in line:
                target_index = idx
                break
        if target_index < 0:
            return ""
        for idx in range(target_index - 1, -1, -1):
            line = lines[idx]
            if ":" not in line:
                continue
            speaker, content = line.split(":", 1)
            if speaker.strip() not in {
                "橋本新", "あらくん", "LIAR OF ARAKUN",
                "LIAR  OF  ARAKUN", "Unknown", "Arata Hashimoto",
            }:
                return content.strip()
        return ""

    def replay_behavior_gate(
        self,
        hit: dict,
        user_text: str,
        behavior: dict | None,
    ) -> tuple[bool, int, list[str]]:
        """Semantic/action gate for historical replay.

        Lexical overlap may retrieve a scene, but replay is permitted only when
        the historical *stimulus→reply action* is compatible with the current
        action-state. This prevents a shared word such as "人類" from turning an
        unrelated historical sentence into an answer to an opinion question.
        """
        behavior = behavior or {}
        mode = behavior.get("mode", "ordinary_direct")
        current_family = behavior.get(
            "question_family",
            self.question_family(user_text),
        )
        reply = hit.get("reply", "") or ""
        historical_stimulus = self._extract_historical_stimulus(hit)
        historical_family = self.question_family(historical_stimulus)
        reasons = []
        bonus = 0

        if current_family in {
            "opinion", "preference", "experience", "location", "time",
            "amount", "count", "reason", "explanation", "yesno",
        }:
            if not historical_stimulus:
                return False, -120, ["replay_no_historical_stimulus"]
            if historical_family != current_family:
                # Explanation/open-WH are close enough to share some scenes.
                compatible = (
                    current_family in {"reason", "explanation"}
                    and historical_family in {"reason", "explanation", "open_wh"}
                )
                if not compatible:
                    return False, -120, [
                        f"replay_stimulus_mismatch:{historical_family}->{current_family}"
                    ]
            bonus += 35
            reasons.append(f"historical_action_match:{current_family}")

        if _requires_direct_answer_gate(user_text) and not _candidate_act_matches(
            reply,
            user_text,
        ):
            return False, -120, ["replay_direct_answer_mismatch"]

        if mode == "practical_clarification":
            if current_family in {"location", "time", "amount", "count"}:
                bonus += 20
                reasons.append("mode_fit:practical_clarification")
        elif mode == "knowledge_explainer":
            if len(reply) >= 16 or re.search(
                r"ので|から|基本|場合|目的|回|セット|重量|筋肉|トレ",
                reply,
            ):
                bonus += 20
                reasons.append("mode_fit:knowledge_explainer")
        elif mode == "playful_worldbuild":
            if re.search(
                r"タイプ|進化|合体|世界|野生|必殺|クローン|サイボーグ|"
                r"ﾎﾓｫ|どいくん|とみざわさん",
                reply,
            ):
                bonus += 22
                reasons.append("mode_fit:playful_worldbuild")
        elif mode == "defensive_correction":
            if re.search(r"違|ちが|言って|ない|ません|嘘|ほんと", reply):
                bonus += 20
                reasons.append("mode_fit:defensive_correction")
        elif mode == "playful_burst":
            if len(reply) <= 30:
                bonus += 18
                reasons.append("mode_fit:playful_burst")

        return True, bonus, reasons

    def select_replay(
        self,
        replay: str | None,
        replay_info: dict,
        user_text: str,
        behavior: dict | None,
    ):
        hits = list((replay_info or {}).get("hits") or [])
        if not hits and (replay_info or {}).get("chosen"):
            hits = [replay_info["chosen"]]
        accepted = []
        rejected = []
        for hit in hits:
            ok, bonus, reasons = self.replay_behavior_gate(
                hit,
                user_text,
                behavior,
            )
            item = dict(hit)
            item["behavior_score"] = item.get("score", 0) + bonus
            item["behavior_reasons"] = reasons
            if ok:
                accepted.append(item)
            else:
                rejected.append(item)
        accepted.sort(
            key=lambda item: item.get("behavior_score", 0),
            reverse=True,
        )
        if not accepted:
            return None, {
                "used": False,
                "reason": "behavioral_replay_gate_reject",
                "behavior": behavior,
                "rejected": rejected[:5],
            }
        chosen = accepted[0]
        return chosen.get("reply"), {
            "used": True,
            "mode": "behavioral_scene_replay_v15",
            "chosen": chosen,
            "hits": accepted[:8],
            "rejected": rejected[:5],
            "behavior": behavior,
        }

    def generation_guidance(
        self,
        user_text: str,
        current_speaker: str | None = None,
        behavior: dict | None = None,
    ) -> str:
        """Build generation guidance directly from corpus-derived policy."""
        policy = getattr(self.persona_policy, "profile", {}) or {}
        if not policy:
            return ""

        situation = classify_stimulus(user_text or "")
        global_actions = policy.get("global_action_policy", {}) or {}
        situation_node = (
            policy.get("situation_policy", {}).get(situation, {}) or {}
        )
        situation_actions = situation_node.get("actions", {}) or {}
        relationship = (
            policy.get("relationship_policy", {}).get(
                current_speaker or "",
                {},
            ) or {}
        )
        relationship_actions = relationship.get("action_policy", {}) or {}

        def top_actions(node, n=3):
            ranked = sorted(
                (
                    (
                        action,
                        float(item.get("probability", 0.0)),
                        int(item.get("count", 0)),
                    )
                    for action, item in node.items()
                    if int(item.get("count", 0)) > 0
                ),
                key=lambda x: (x[1], x[2]),
                reverse=True,
            )
            return ranked[:n]

        situ = top_actions(situation_actions)
        rel = top_actions(relationship_actions)
        glob = top_actions(global_actions)

        language = policy.get("language", {}) or {}
        global_avg = float(
            language.get("average_reply_length", self.median_len)
        )
        partner_avg = relationship.get("average_reply_length")
        if partner_avg is not None:
            target_length = float(partner_avg)
            length_source = "相手別"
        else:
            target_length = global_avg
            length_source = "全体"

        def fmt(items):
            return ", ".join(
                f"{action}:{prob:.0%}"
                for action, prob, _ in items
            )

        pieces = [
            f"実ログ行動傾向({situation}): {fmt(situ) or fmt(glob)}",
            f"平均返答長({length_source}): 約{target_length:.1f}文字",
        ]
        if rel:
            pieces.append(f"この相手への傾向: {fmt(rel)}")

        behavior_text = self.behavior_instruction(behavior)
        return (
            "一次LINEログから復元した現在の行動状態: "
            f"{(behavior or {}).get('mode', 'ordinary_direct')}。"
            f"{behavior_text} "
            "以下の統計は語尾テンプレートではなく補助情報としてのみ使う。"
            + " / ".join(pieces)
        )

    def _corpus_style_prior(
        self,
        candidate: str,
        user_text: str,
        search_result: dict,
    ) -> tuple[int, list[str]]:
        """Use corpus action distributions as a soft persona prior."""
        policy = getattr(self, "persona_policy", None)
        if policy is None or not policy.loaded:
            return 0, []

        action = classify_reply(candidate)
        situation = classify_stimulus(user_text)
        current_speaker = search_result.get("current_speaker") or None

        bonus, reasons = policy.action_bonus(
            action,
            current_speaker=current_speaker,
            situation=situation,
        )
        weighted = int(round(bonus * 1.7))
        if weighted:
            reasons = [
                reason.replace(":+", ":base+")
                for reason in reasons
            ]
            reasons.append(
                f"corpus_style_prior:{action}:{situation}:+{weighted}"
            )
        return weighted, reasons

    def _load_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def topic_terms(self, search_result: dict):
        return [t for t in search_result.get("topic_terms", []) if t]

    def episode_text(self, search_result: dict):
        return "\n".join(
            (episode.get("window", "") or "")
            for episode in search_result.get("episodes", []) or []
        )

    def _numbers_in_episode(self, search_result: dict):
        return re.findall(
            r"[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)",
            self.episode_text(search_result),
        )

    def split_candidates(self, raw: str):
        if not raw:
            return []
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^[\-\*\d\.\)、\)]\s*", "", line).strip()
            line = re.sub(r"^候補[A-Da-d0-9]*[:：]\s*", "", line).strip()
            if line:
                lines.append(line)
        if not lines:
            lines = [
                x.strip()
                for x in re.split(r"[。！？!?]\s*", raw)
                if x.strip()
            ]

        out = []
        seen = set()
        for candidate in lines:
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= 6:
                break
        return out

    def _content_tokens(self, text: str):
        toks = re.findall(
            r"[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|"
            r"[一-龥々〆ヵヶ]{2,}|[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)",
            text or "",
        )
        bad = {
            "今日", "明日", "昨日", "何個", "何回", "何人", "何枚",
            "予定", "つもり", "好き", "嫌い",
        }
        normalized_bad = {normalize(x) for x in bad}
        out = []
        for token in toks:
            nt = normalize(token)
            if not nt or nt in normalized_bad:
                continue
            out.append(token)
        return out

    def _episode_overlap(self, candidate: str, search_result: dict):
        normalized_episode = normalize(self.episode_text(search_result))
        tokens = self._content_tokens(candidate)
        hits = [
            token
            for token in tokens
            if normalize(token) in normalized_episode
        ]
        return hits, tokens

    def _assertion_supported(self, candidate: str, search_result: dict):
        episode = self.episode_text(search_result)
        for word in ASSERTION_WORDS:
            if word in candidate and word not in episode:
                return False, word
        return True, None

    def score(self, candidate: str, user_text: str, search_result: dict):
        c = (candidate or "").strip()
        if SURFACE_CORRUPTION_RE.search(c):
            return -999, ["surface_corruption_hard_reject"]
        nc = normalize(c)
        score = 100
        reasons = []

        if not c:
            return -999, ["empty"]

        behavior = search_result.get("hashimoto_behavior") or {}
        family = behavior.get("question_family") or self.question_family(user_text)
        subject_role = behavior.get("subject_role", "external_or_unspecified")
        stance = behavior.get("stance") or search_result.get("hashimoto_stance") or {}
        stance_kind = stance.get("kind", "direct")
        reality = behavior.get("reality") or search_result.get("hashimoto_reality") or {}
        value_orientation = (
            behavior.get("value_orientation")
            or search_result.get("hashimoto_value_orientation")
            or {}
        )
        question_semantics = (
            behavior.get("question_semantics")
            or search_result.get("hashimoto_question_semantics")
            or {}
        )
        opinion_evidence = (
            behavior.get("opinion_evidence")
            or search_result.get("hashimoto_opinion_evidence")
            or {}
        )
        relationship_evidence = search_result.get("relationship_evidence") or {}

        # v14.40: semantic completeness belongs in candidate scoring, where
        # both candidate text (`c`) and question semantics are available.
        required_semantics = question_semantics.get("required", "")
        if DANGLING_DEICTIC_RE.search(c):
            return -999, ["semantic_incomplete:dangling_deictic"]
        if required_semantics == "personal_evaluation":
            if "ざっくり言えばそう" in c or re.search(
                r"(?:だけど|けど)[、 ]*そうだ[。！？]?$", c
            ):
                return -999, ["semantic_incomplete:opinion_missing_evaluation"]
            if OPINION_META_NONANSWER_RE.search(c):
                return -999, ["semantic_incomplete:opinion_meta_nonanswer"]

        # Direct-answer questions must not be turned back into a new question.
        # A rhetorical answer such as 「たぶんいるんじゃない？」 is allowed
        # when it already contains a clear stance marker.
        if family in {"yesno", "self_state"} and _question_like(c):
            rhetorical_answer = bool(PERSONAL_LEAN_RE.search(c)) and not (
                subject_role == "assistant_self"
                and re.search(r"(?:どんな|どう|何が|なんか変わって)", c)
            )
            if not rhetorical_answer:
                return -999, ["question_back_hard_reject"]

        if subject_role == "assistant_self" and family == "self_state":
            if _question_like(c):
                return -999, ["self_state_question_back_reject"]

            answer_class = _self_state_answer_class(c)
            if answer_class == "nonanswer":
                return -999, ["question_semantics_hard_reject:self_state_nonanswer"]

            # Reality precedes persona: AGO must not invent literal self-awareness.
            if answer_class == "affirmative":
                return -999, ["reality_hard_reject:invented_self_awareness"]
            if AI_SELF_AWARENESS_ASSERT_RE.search(c) and not AI_SELF_AWARENESS_NEGATED_RE.search(c):
                return -999, ["reality_hard_reject:invented_self_awareness"]
            if AI_SELF_CHANGE_ASSERT_RE.search(c) and not REALITY_SAFE_SELF_RE.search(c):
                return -999, ["reality_hard_reject:invented_self_change"]

        if family in {"opinion", "preference"}:
            evidence_level = opinion_evidence.get("level", "none")
            if evidence_level == "none":
                if STRONG_PERSONAL_OPINION_RE.search(c):
                    score -= 75
                    reasons.append("opinion_evidence_missing:strong_claim")
                if LOW_COMMITMENT_OPINION_RE.search(c):
                    score += 4
                    reasons.append("opinion_evidence_fit:low_commitment")
            elif evidence_level == "direct":
                direction = opinion_evidence.get("direction", "")
                if direction == "positive" and re.search(r"嫌い|怖|苦手|最悪", c):
                    score -= 65
                    reasons.append("opinion_evidence_direction_conflict")
                elif direction == "negative" and re.search(r"好き|面白|良い|最高", c):
                    score -= 65
                    reasons.append("opinion_evidence_direction_conflict")
                else:
                    score += 16
                    reasons.append("opinion_evidence_direct")

            # v14.42: when the target is a real corpus participant, relationship
            # evidence should prevent generic LLM evasions. It still does NOT
            # license invented liking/disliking.
            if relationship_evidence.get("used"):
                interaction_count = int(relationship_evidence.get("interaction_count", 0) or 0)
                if interaction_count >= 8:
                    if re.fullmatch(r"(?:まあ|まぁ)?[、 ]*(?:まあかな|微妙(?:な感じ)?|別に|分からない|なんとも(?:言えない)?)[。！？!?]*", c):
                        score -= 28
                        reasons.append("relationship_evidence_underused:generic_evasion")
                    else:
                        score += 8
                        reasons.append("relationship_evidence_available")

        if (
            _requires_direct_answer_gate(user_text)
            and not _candidate_act_matches(c, user_text)
        ):
            return -999, ["dialogue_act_hard_reject"]

        if _looks_cut_midword(c):
            return -999, ["truncated_fragment"]

        for bad in BAD_GENERATED_FRAGMENTS:
            if bad in c:
                score -= 90
                reasons.append(f"broken_fragment:{bad}")

        for bad in self.forbidden:
            if bad and bad in c:
                score -= 70
                reasons.append(f"forbidden:{bad}")

        tail = re.sub(r"[。！？!?、\s]+$", "", c)
        # Keep only a genuinely unsupported caricature ending. Ordinary
        # "です/ます/ですね/だよ/ないよ" all occur in the primary corpus.
        if tail.endswith(("だぜ", "ぜ")):
            score -= 65
            reasons.append("bad_tail:ぜ")

        length = len(c)
        behavior = search_result.get("hashimoto_behavior") or {}
        mode = behavior.get("mode", "ordinary_direct")
        if mode == "knowledge_explainer":
            # Long explanations are a real state, not a style failure.
            if length <= 180:
                score += 5
                reasons.append("explainer_length_allowed")
            elif length > 320:
                score -= 15
                reasons.append("explainer_transport_long")
        elif mode == "playful_worldbuild":
            if length <= 120:
                score += 4
                reasons.append("worldbuild_length_allowed")
            elif length > 220:
                score -= 12
                reasons.append("worldbuild_overlong")
        else:
            if length <= self.p75_len + 8:
                score += 4
                reasons.append("primary_corpus_length_fit")
            elif length > 140:
                score -= 14
                reasons.append("generated_overlong")

        if _candidate_act_matches(c, user_text):
            score += 34
            reasons.append("dialogue_act_match")
        else:
            score -= 44
            reasons.append("dialogue_act_mismatch")

        for explainer in [
            "つまり", "要するに", "ということ", "可能性", "予定", "つもり",
            "一般的", "文脈", "設定", "回答",
        ]:
            if explainer in c:
                score -= 25
                reasons.append(f"explain_or_invent:{explainer}")

        topics = self.topic_terms(search_result)
        overlap_hits, candidate_tokens = self._episode_overlap(
            c,
            search_result,
        )

        if search_result.get("generation_mode"):
            episode_only = _episode_only_tokens(
                c,
                user_text,
                search_result,
            )
            episode_speakers = _episode_speakers(search_result)
            grounding_n = normalize(
                _grounding_text(user_text, search_result)
            )
            imported_speakers = [
                name for name in episode_speakers
                if name
                and normalize(name) in nc
                and normalize(name) not in grounding_n
            ]

            if imported_speakers:
                score -= 85
                reasons.append(
                    "imported_episode_speaker:"
                    + ",".join(imported_speakers[:3])
                )

            if episode_only:
                penalty = min(90, 28 + len(episode_only) * 18)
                score -= penalty
                reasons.append(
                    "episode_only_content:"
                    + ",".join(episode_only[:4])
                )

            if ATTRIBUTION_RE.search(c):
                attribution_grounded = any(
                    normalize(name) in grounding_n
                    for name in episode_speakers
                    if name
                )
                if not attribution_grounded:
                    score -= 90
                    reasons.append("ungrounded_attribution")
        else:
            if overlap_hits:
                score += 18 + min(len(overlap_hits), 4) * 8
                reasons.append(
                    f"episode_overlap:{','.join(overlap_hits[:4])}"
                )
            elif candidate_tokens and search_result.get("episodes"):
                score -= 28
                reasons.append("no_episode_overlap")

        if topics:
            if any(normalize(topic) in nc for topic in topics):
                score += 12
                reasons.append("mentions_topic")
            else:
                score -= 5
                reasons.append("omits_topic")

        supported, bad_assertion = self._assertion_supported(
            c,
            search_result,
        )
        if not supported:
            score -= 55
            reasons.append(f"unsupported_assertion:{bad_assertion}")

        if any(
            key in user_text
            for key in ["何個", "何人", "何枚", "何回", "いくつ"]
        ):
            numbers = self._numbers_in_episode(search_result)
            if numbers:
                clean_numbers = [
                    re.sub(r"\s+", "", number)
                    for number in numbers
                ]
                clean_candidate = re.sub(r"\s+", "", c)
                if any(number in clean_candidate for number in clean_numbers):
                    score += 35
                    reasons.append("canon_number_match")
                else:
                    score -= 45
                    reasons.append("missing_canon_number")

        if any(
            phrase in c
            for phrase in ["予定", "つもり", "食べました", "食べたことある"]
        ):
            score -= 60
            reasons.append("tense_invention")

        if re.search(
            r"(総合的に考えると|一般論として|結論としては|"
            r"と考えられます|可能性が高いと考えられます)",
            c,
        ):
            score -= 35
            reasons.append("polished_ai")

        if c in self.common_lines:
            score += 12
            reasons.append("known_line")

        behavior = search_result.get("hashimoto_behavior") or {}
        mode = behavior.get("mode", "ordinary_direct")
        if mode == "practical_clarification":
            if re.search(r"どこ|何時|いつ|いくら|何円|何個|何回|場所|必要", c):
                score += 18
                reasons.append("behavior_fit:practical_clarification")
        elif mode == "knowledge_explainer":
            if len(c) >= 18 or re.search(r"ので|から|基本|場合|目的|セット|回|重量", c):
                score += 16
                reasons.append("behavior_fit:knowledge_explainer")
        elif mode == "literal_serious":
            if not re.search(r"きゃぴ|ｷｬﾋﾟ|キャピ", c, re.I):
                score += 8
                reasons.append("behavior_fit:literal_serious")
        elif mode == "playful_worldbuild":
            if re.search(r"タイプ|進化|合体|世界|野生|必殺|クローン|サイボーグ|ﾎﾓｫ", c):
                score += 16
                reasons.append("behavior_fit:playful_worldbuild")
        elif mode == "defensive_correction":
            if re.search(r"違|ちが|言って|ない|ません|嘘|ほんと", c):
                score += 16
                reasons.append("behavior_fit:defensive_correction")
        elif mode == "self_disclosure":
            if _candidate_act_matches(c, user_text):
                score += 12
                reasons.append("behavior_fit:self_disclosure")
        elif mode == "playful_burst":
            if len(c) <= 30:
                score += 16
                reasons.append("behavior_fit:playful_burst")
        elif re.search(r"きゃぴ|ｷｬﾋﾟ|キャピ", c, re.I):
            score -= 70
            reasons.append("burst_leak_outside_burst_mode")

        # v14.34: internal stance outranks surface persona.
        if stance_kind == "personal_hunch":
            if PERSONAL_LEAN_RE.search(c):
                score += 22
                reasons.append("stance_fit:personal_hunch")
            if EPISTEMIC_DEFERRAL_RE.search(c):
                score -= 55
                reasons.append("stance_mismatch:epistemic_deferral")
        elif stance_kind == "personal_evaluation":
            abstract_eval = bool(re.search(
                r"興味深い(?:存在|対象|話題)|まだまだ未知|未知(?:だ|です)|"
                r"一般的|確定した情報|存在(?:だ|です)",
                c,
            ))
            if abstract_eval:
                score -= 55
                reasons.append("stance_mismatch:abstract_commentary")
            elif re.search(
                r"好き|嫌い|面白|興味|怖|苦手|微妙|すご|"
                r"と思う|感じ|まあ|別に|わから",
                c,
            ):
                score += 20
                reasons.append("stance_fit:personal_evaluation")
        elif stance_kind == "self_state":
            answer_class = _self_state_answer_class(c)
            if answer_class == "unknown":
                score += 34
                reasons.append("stance_fit:self_state_unknown")
            elif answer_class == "negative":
                score += 10
                reasons.append("stance_fit:self_state_negative_cautious")
        elif stance_kind == "clarify":
            if _question_like(c):
                score += 10
                reasons.append("stance_fit:clarify")

        # v14.35: Reality/Canon and value orientation precede surface style.
        if reality.get("kind") == "ai_self_state":
            if REALITY_SAFE_SELF_RE.search(c):
                score += 28
                reasons.append("reality_fit:ai_self_state_cautious")
            if AI_SELF_AWARENESS_ASSERT_RE.search(c) and not AI_SELF_AWARENESS_NEGATED_RE.search(c):
                score -= 80
                reasons.append("reality_mismatch:self_awareness_claim")

        value_style = value_orientation.get("style", "")
        if value_style == "concrete_personal_evaluation":
            if CONCRETE_EVALUATION_RE.search(c):
                score += 24
                reasons.append("value_fit:concrete_personal_evaluation")
            if ABSTRACT_EVALUATION_RE.search(c):
                score -= 50
                reasons.append("value_mismatch:abstract_llm_commentary")
        elif value_style == "concrete_absurd_extension":
            if len(c) >= 4 and not ABSTRACT_EVALUATION_RE.search(c):
                score += 12
                reasons.append("value_fit:concrete_worldbuild")
        elif value_style == "specific_practical_explanation":
            if re.search(r"\d|セット|回|目的|まず|くらい|程度|場合", c):
                score += 12
                reasons.append("value_fit:specific_practicality")

        style_bonus, style_reasons = self._corpus_style_prior(
            c,
            user_text,
            search_result,
        )
        score += style_bonus
        reasons.extend(style_reasons)

        return score, reasons

    def should_regenerate(self, chosen: str | None, judge_info: dict, search_result: dict) -> tuple[bool, list[str]]:
        """One bounded retry for candidates that are semantically valid but ungrounded.

        This is deliberately not an open-ended loop. One retry is enough to
        stop the old "all candidates are bad, so pick the least bad" failure.
        """
        reasons = list(((judge_info or {}).get("chosen") or {}).get("reasons") or [])
        retry_reasons = []
        if not chosen:
            retry_reasons.append("no_acceptable_candidate")
        if "opinion_evidence_missing:strong_claim" in reasons:
            retry_reasons.append("unsupported_personal_opinion")
        if "relationship_evidence_underused:generic_evasion" in reasons:
            retry_reasons.append("relationship_evidence_underused")
        return bool(retry_reasons), retry_reasons

    def choose(
        self,
        candidates: list[str],
        user_text: str,
        search_result: dict,
    ):
        scored = []
        for candidate in candidates:
            score, reasons = self.score(
                candidate,
                user_text,
                search_result,
            )
            scored.append({
                "text": candidate,
                "score": score,
                "reasons": reasons,
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        if not scored:
            return None, {"chosen": None, "scored": []}

        best = scored[0]
        if best["score"] < 70:
            return None, {
                "chosen": None,
                "scored": scored[:6],
                "rejected": True,
            }

        return best["text"], {
            "chosen": best,
            "scored": scored[:6],
            "rejected": False,
            "evaluation_axes": [
                "semantic",
                "topic",
                "conversation_state",
                "relationship",
                "persona",
                "episode",
                "provenance",
                "corpus_style",
                "behavior_state",
                "stance",
                "reality_canon",
                "value_orientation",
                "question_semantics",
                "opinion_evidence",
                "relationship_evidence",
            ],
        }
