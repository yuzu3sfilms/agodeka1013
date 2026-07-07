import re


TRAINING_KEYWORDS = [
    "筋トレ", "トレーニング", "ワークアウト", "メニュー", "セット", "レップ", "rep", "reps",
    "ベンチ", "スクワット", "デッド", "懸垂", "腕立て", "腹筋", "背筋", "ダンベル",
    "胸", "背中", "脚", "足", "肩", "腕", "二頭", "三頭", "腹", "尻",
    "増量", "減量", "カロリー", "タンパク", "たんぱく", "プロテイン",
    "筋肉痛", "フォーム", "重量", "MAX", "マックス", "有酸素", "休養",
    "全身", "全部位", "フルボディ", "全身法", "全身鍛える",
    "ジム", "今日は胸", "今日胸", "今日脚", "今日肩", "今日背中", "今日腕",
    "ステロイド", "アナボリック", "テストステロン", "成長ホルモン", "SARMs", "サーム", "クレンブテロール",
]

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
    "legs": ["脚", "足", "下半身", "スクワット", "レッグ", "ブルガリアン"],
    "shoulders": ["肩", "三角筋", "サイドレイズ", "ショルダー"],
    "arms": ["腕", "二頭", "三頭", "カール", "プッシュダウン"],
    "core": ["腹", "腹筋", "体幹", "プランク"],
}


def contains_training_intent(text: str) -> bool:
    t = text or ""
    if any(k.lower() in t.lower() for k in TRAINING_KEYWORDS):
        return True
    if any(re.search(p, t, re.I) for p in LOG_PATTERNS):
        return True
    return False


def classify_training_intent(text: str, last_training_context: dict | None = None):
    t = text or ""
    low = t.lower()
    stripped = t.strip()
    last_training_context = last_training_context or {}

    question_like = bool(re.search(r"[？?]|何回|なんかい|何レップ|何セット|どう|やれば|すれば|いいの|いい？|よい？", t))
    followup_only = stripped in {"？", "?", "うん", "はい", "なるほど", "ふむ", "ほう", "で", "それで", "続き", "他の日は？", "他の日は"}
    in_training_context = bool(last_training_context)

    explicit_training_topic = contains_training_intent(t)
    fullbody_topic = any(k in t for k in ["全身", "全部位", "フルボディ", "全身法", "全身鍛える"])
    other_day_question = bool(re.search(r"他の日|別の日|翌日|次の日|週間|週メニュー|週のメニュー|分割", t))

    if not explicit_training_topic and not (in_training_context and (question_like or followup_only or other_day_question)):
        return {"is_training": False, "intent": "none", "parts": [], "is_log": False}

    parts = []
    for part, keys in BODY_PARTS.items():
        if any(k in t for k in keys):
            parts.append(part)

    # inherit body part only for true vague followups.
    # Explicit new topics such as 全身 should not be swallowed by the old context.
    if not parts and last_training_context.get("parts") and not explicit_training_topic:
        parts = list(last_training_context.get("parts", []))

    is_log = any(re.search(p, t, re.I) for p in LOG_PATTERNS)

    # Safety/pain first.
    if any(k in t for k in ["痛い", "痛み", "筋肉痛", "違和感", "怪我", "ケガ", "腫れ", "しびれ", "痺れ"]):
        intent = "pain_or_injury"

    # Questions must beat log detection.
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

    # Short follow-up inside training context.
    elif in_training_context and followup_only:
        intent = "training_ack_or_followup"

    # Then logs.
    elif any(k in t for k in ["記録", "メモ", "やった", "完了", "終わった"]) or is_log:
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
        "inherited_training_context": in_training_context and not contains_training_intent(t),
    }
