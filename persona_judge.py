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
            r"思う|思わ|かも|強|弱|増|減|変わ|"
            r"わから|分から|知らな|たぶん|多分|まだ|もう",
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
        t = (text or "").strip()
        if not re.search(r"[？?]", t):
            if re.fullmatch(r"(?:きゃぴ|ｷｬﾋﾟ|キャピ|きゃっ|ｷｬｯﾋﾟ[ｲｨ]?)[！!~〜～]*", t, re.I):
                return "burst"
            return "statement"
        if re.search(r"何個|何人|何枚|何回|何本|何杯|いくつ", t):
            return "count"
        if re.search(r"どこ|何処|場所|何口|何線", t):
            return "location"
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
        reasons = []
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

        return {
            "mode": mode,
            "confidence": round(confidence, 2),
            "question_family": family,
            "reasons": reasons,
        }

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
            "playful_burst": (
                "今の発言自体が高テンション語録モード。短い反応や同型のノリを"
                "許可するが、このモード以外へキャピ等を漏らさない。"
            ),
        }
        return instructions.get(mode, instructions["ordinary_direct"])

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
        nc = normalize(c)
        score = 100
        reasons = []

        if not c:
            return -999, ["empty"]

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

        style_bonus, style_reasons = self._corpus_style_prior(
            c,
            user_text,
            search_result,
        )
        score += style_bonus
        reasons.extend(style_reasons)

        return score, reasons

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
            ],
        }
