import re

# Domain evidence and conversational purpose are separate.
EXERCISE_TERMS = [
    "筋トレ", "トレーニング", "ワークアウト", "ジム", "全身法", "フルボディ",
    "ベンチプレス", "スクワット", "デッドリフト", "懸垂", "腕立て", "ダンベル",
    "ケーブルロウ", "ローイング", "ラットプル", "ショルダープレス",
    "サイドレイズ", "リアレイズ", "カール", "フライ", "プッシュダウン",
    "ブルガリアンスクワット", "筋肥大", "増量", "減量", "有酸素",
    "1rm", "max",
]
NUTRITION_TERMS = [
    "プロテイン", "タンパク質", "たんぱく質", "蛋白質",
    "カロリー", "食事", "栄養",
]
HIGH_RISK_TERMS = [
    "ステロイド", "アナボリック", "sarms", "サーム", "クレンブテロール",
]
BODY_PART_TERMS = [
    "胸", "大胸筋", "背中", "広背筋", "脚", "下半身", "肩", "三角筋",
    "腕", "二頭", "三頭", "腹", "腹筋", "体幹", "尻", "臀部",
]

TRAINING_REQUEST_CUES = [
    "教えて", "どうすれば", "どうしたら", "どうやる", "やり方", "フォーム",
    "メニュー", "組んで", "何回", "何レップ", "何セット", "何kg", "何キロ",
    "重量", "回数", "セット数", "効かせ", "効いて", "鍛え", "でかく",
    "デカく", "増やしたい", "減らしたい", "おすすめ", "どれがいい",
    "何やる", "今日何", "週何回", "休養", "頻度",
]
NUTRITION_QUESTION_CUES = [
    "意味あん", "意味ある", "必要", "効果", "効く", "飲む", "摂る",
    "何g", "何グラム", "どのくらい", "タイミング", "いつ",
]
TRAINING_LOG_CUES = ["記録", "メモ", "やった", "完了", "終わった"]
LOG_PATTERNS = [
    r"(ベンチ|スクワット|デッド|懸垂|ダンベル|プレス|カール|フライ|ロー|ラット|レッグ)",
    r"\d+\s*(kg|キロ)",
    r"\d+\s*(回|rep|reps|レップ)",
    r"\d+\s*(セット|set|sets)",
]
BODY_PARTS = {
    "fullbody": ["全身", "全部位", "フルボディ", "全身法", "全身鍛える"],
    "chest": ["胸", "大胸筋", "ベンチ", "プレス", "フライ"],
    "back": ["背中", "広背筋", "懸垂", "ラット", "ロー", "デッド"],
    "legs": ["脚", "下半身", "スクワット", "レッグ", "ブルガリアン"],
    "shoulders": ["肩", "三角筋", "サイドレイズ", "リアレイズ", "ショルダー"],
    "arms": ["腕", "二頭", "三頭", "カール", "プッシュダウン"],
    "core": ["腹", "腹筋", "体幹", "プランク"],
    "glutes": ["尻", "臀部", "ヒップスラスト"],
}


def _contains_any(text: str, terms) -> bool:
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)


def _has_log_pattern(text: str) -> bool:
    return any(re.search(pattern, text or "", re.I) for pattern in LOG_PATTERNS)


def _is_bare_domain_ping(text: str) -> bool:
    stripped = re.sub(r"[！!。…\s]+$", "", (text or "").strip())
    domain_terms = EXERCISE_TERMS + NUTRITION_TERMS
    return any(stripped.lower() == term.lower() for term in domain_terms)


def contains_training_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    exercise_domain = _contains_any(t, EXERCISE_TERMS)
    nutrition_domain = _contains_any(t, NUTRITION_TERMS)
    high_risk = _contains_any(t, HIGH_RISK_TERMS)
    request = _contains_any(t, TRAINING_REQUEST_CUES)
    nutrition_request = _contains_any(t, NUTRITION_QUESTION_CUES)
    question = bool(re.search(r"[？?]", t))
    log_signal = _contains_any(t, TRAINING_LOG_CUES) or _has_log_pattern(t)
    body_part = _contains_any(t, BODY_PART_TERMS)

    # A one-word shout such as 「プロテイン！」 is ordinary conversation.
    if _is_bare_domain_ping(t):
        return False

    if high_risk:
        return True
    if nutrition_domain:
        return question or nutrition_request or request or log_signal
    if exercise_domain:
        return request or question or log_signal
    if body_part and (request or log_signal):
        return True
    return False


def classify_training_intent(
    text: str,
    last_training_context: dict | None = None,
):
    t = text or ""
    stripped = t.strip()
    last_training_context = last_training_context or {}

    question_like = bool(re.search(
        r"[？?]|何回|なんかい|何レップ|何セット|どう|やれば|すれば|"
        r"いいの|いい？|よい？",
        t,
    ))
    followup_normalized = re.sub(r"[？?！!。\s]+$", "", stripped)
    followup_only = followup_normalized in {
        "", "うん", "はい", "なるほど", "ふむ", "ほう",
        "で", "それで", "続き",
    }
    in_training_context = bool(
        last_training_context.get("intent")
        or last_training_context.get("parts")
    )
    explicit_training_topic = contains_training_intent(t)
    fullbody_topic = any(
        key in t
        for key in ["全身", "全部位", "フルボディ", "全身法", "全身鍛える"]
    )
    nutrition_topic = _contains_any(t, NUTRITION_TERMS)
    other_day_question = bool(re.search(
        r"他の日|別の日|翌日|次の日|週間|週メニュー|週のメニュー|分割",
        t,
    ))
    context_followup = in_training_context and (
        followup_only or other_day_question
    )

    if not explicit_training_topic and not context_followup:
        return {
            "is_training": False,
            "intent": "none",
            "parts": [],
            "is_log": False,
            "question_like": question_like,
            "inherited_training_context": False,
            "reason": "no_training_purpose_and_domain",
        }

    parts = []
    for part, keys in BODY_PARTS.items():
        if any(key in t for key in keys):
            parts.append(part)

    if (
        not parts
        and last_training_context.get("parts")
        and not explicit_training_topic
    ):
        parts = list(last_training_context.get("parts", []))

    is_log = _has_log_pattern(t)

    if any(
        key in t
        for key in [
            "痛い", "痛み", "筋肉痛", "違和感", "怪我", "ケガ",
            "腫れ", "しびれ", "痺れ",
        ]
    ):
        intent = "pain_or_injury"
    elif nutrition_topic and question_like:
        if _contains_any(t, ["何g", "何グラム", "どのくらい"]):
            intent = "nutrition_amount_question"
        elif _contains_any(t, ["いつ", "タイミング"]):
            intent = "nutrition_timing_question"
        else:
            intent = "nutrition_effectiveness_question"
    elif question_like:
        if other_day_question:
            intent = "weekly_plan_followup"
        elif fullbody_topic:
            intent = "fullbody_program_request"
        elif any(
            key in t
            for key in ["何回", "何レップ", "1セット", "１セット", "一セット", "レップ"]
        ):
            intent = "rep_scheme_question"
        elif any(key in t for key in ["何セット", "セット"]):
            intent = "set_scheme_question"
        elif any(
            key in t
            for key in ["減量", "痩せ", "絞", "カロリー", "食事"]
        ):
            intent = "nutrition_cut"
        elif any(
            key in t
            for key in ["フォーム", "効か", "効いて", "やり方"]
        ):
            intent = "form_advice"
        else:
            intent = "training_followup_question"
    elif in_training_context and followup_only:
        intent = "training_ack_or_followup"
    elif _contains_any(t, TRAINING_LOG_CUES) or is_log:
        intent = "log_workout"
    elif fullbody_topic and any(
        key in t
        for key in ["メニュー", "組んで", "鍛える", "やる"]
    ):
        intent = "fullbody_program_request"
    elif other_day_question:
        intent = "weekly_plan_followup"
    elif any(
        key in t
        for key in ["メニュー", "何やる", "組んで", "今日", "セット", "レップ"]
    ):
        intent = "program_request"
    elif any(
        key in t
        for key in ["減量", "痩せ", "絞", "カロリー", "食事"]
    ):
        intent = "nutrition_cut"
    elif any(
        key in t
        for key in ["増量", "デカく", "でかく", "筋肥大", "バルク"]
    ):
        intent = "hypertrophy"
    elif any(
        key in t
        for key in ["フォーム", "効か", "効いて", "やり方"]
    ):
        intent = "form_advice"
    else:
        intent = "general_training"

    return {
        "is_training": True,
        "intent": intent,
        "parts": parts,
        "is_log": is_log and not question_like,
        "question_like": question_like,
        "inherited_training_context": (
            context_followup and not explicit_training_topic
        ),
        "reason": (
            "current_training_purpose_and_domain"
            if explicit_training_topic
            else "verified_training_followup"
        ),
    }
