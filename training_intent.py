import re

# Domain evidence and conversational intent are deliberately separated.
# A body part alone is NOT a training request.
STRONG_TRAINING_TERMS = [
    "筋トレ", "トレーニング", "ワークアウト", "ジム", "全身法", "フルボディ",
    "ベンチプレス", "スクワット", "デッドリフト", "懸垂", "腕立て", "ダンベル",
    "ケーブルロウ", "ローイング", "ラットプル", "ショルダープレス", "サイドレイズ",
    "リアレイズ", "カール", "フライ", "プッシュダウン", "ブルガリアンスクワット",
    "筋肥大", "増量", "減量", "プロテイン", "有酸素", "1rm", "max",
    "ステロイド", "アナボリック", "sarms", "サーム", "クレンブテロール",
]

BODY_PART_TERMS = [
    "胸", "大胸筋", "背中", "広背筋", "脚", "下半身", "肩", "三角筋",
    "腕", "二頭", "三頭", "腹", "腹筋", "体幹", "尻", "臀部",
]

TRAINING_REQUEST_CUES = [
    "教えて", "どうすれば", "どうしたら", "どうやる", "やり方", "フォーム", "メニュー",
    "組んで", "何回", "何レップ", "何セット", "何kg", "何キロ", "重量", "回数", "セット数",
    "効かせ", "効いて", "鍛え", "でかく", "デカく", "増やしたい", "減らしたい",
    "おすすめ", "どれがいい", "何やる", "今日何", "週何回", "休養", "頻度",
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
    return any(re.search(p, text or "", re.I) for p in LOG_PATTERNS)


def contains_training_intent(text: str) -> bool:
    """Return True only when both domain and purpose support training routing.

    Strong exercise names can establish the domain by themselves. Generic body
    parts require an explicit request/log cue. This prevents statements such as
    'お尻ぬるぬるする' from being converted into workout consultations.
    """
    t = (text or "").strip()
    if not t:
        return False

    strong_domain = _contains_any(t, STRONG_TRAINING_TERMS)
    request = _contains_any(t, TRAINING_REQUEST_CUES)
    log_signal = _contains_any(t, TRAINING_LOG_CUES) or _has_log_pattern(t)
    body_part = _contains_any(t, BODY_PART_TERMS)

    if strong_domain:
        return True
    if body_part and (request or log_signal):
        return True
    return False


def classify_training_intent(text: str, last_training_context: dict | None = None):
    t = text or ""
    stripped = t.strip()
    last_training_context = last_training_context or {}

    question_like = bool(re.search(r"[？?]|何回|なんかい|何レップ|何セット|どう|やれば|すれば|いいの|いい？|よい？", t))
    followup_normalized = re.sub(r"[？?！!。\s]+$", "", stripped)
    followup_only = followup_normalized in {"", "うん", "はい", "なるほど", "ふむ", "ほう", "で", "それで", "続き"}
    in_training_context = bool(last_training_context.get("intent") or last_training_context.get("parts"))

    explicit_training_topic = contains_training_intent(t)
    fullbody_topic = any(k in t for k in ["全身", "全部位", "フルボディ", "全身法", "全身鍛える"])
    other_day_question = bool(re.search(r"他の日|別の日|翌日|次の日|週間|週メニュー|週のメニュー|分割", t))

    context_followup = in_training_context and (followup_only or other_day_question)
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
        if any(k in t for k in keys):
            parts.append(part)

    if not parts and last_training_context.get("parts") and not explicit_training_topic:
        parts = list(last_training_context.get("parts", []))

    is_log = _has_log_pattern(t)

    if any(k in t for k in ["痛い", "痛み", "筋肉痛", "違和感", "怪我", "ケガ", "腫れ", "しびれ", "痺れ"]):
        intent = "pain_or_injury"
    elif question_like:
        if other_day_question:
            intent = "weekly_plan_followup"
        elif fullbody_topic:
            intent = "fullbody_program_request"
        elif any(k in t for k in ["何回", "何レップ", "1セット", "１セット", "一セット", "レップ"]):
            intent = "rep_scheme_question"
        elif any(k in t for k in ["何セット", "セット"]):
            intent = "set_scheme_question"
        elif any(k in t for k in ["減量", "痩せ", "絞", "カロリー", "食事"]):
            intent = "nutrition_cut"
        elif any(k in t for k in ["フォーム", "効か", "効いて", "やり方"]):
            intent = "form_advice"
        else:
            intent = "training_followup_question"
    elif in_training_context and followup_only:
        intent = "training_ack_or_followup"
    elif _contains_any(t, TRAINING_LOG_CUES) or is_log:
        intent = "log_workout"
    elif fullbody_topic and any(k in t for k in ["メニュー", "組んで", "鍛える", "やる"]):
        intent = "fullbody_program_request"
    elif other_day_question:
        intent = "weekly_plan_followup"
    elif any(k in t for k in ["メニュー", "何やる", "組んで", "今日", "セット", "レップ"]):
        intent = "program_request"
    elif any(k in t for k in ["減量", "痩せ", "絞", "カロリー", "食事"]):
        intent = "nutrition_cut"
    elif any(k in t for k in ["増量", "デカく", "でかく", "筋肥大", "バルク"]):
        intent = "hypertrophy"
    elif any(k in t for k in ["フォーム", "効か", "効いて", "やり方"]):
        intent = "form_advice"
    else:
        intent = "general_training"

    return {
        "is_training": True,
        "intent": intent,
        "parts": parts,
        "is_log": is_log and not question_like,
        "question_like": question_like,
        "inherited_training_context": context_followup and not explicit_training_topic,
        "reason": "current_training_purpose_and_domain" if explicit_training_topic else "verified_training_followup",
    }
