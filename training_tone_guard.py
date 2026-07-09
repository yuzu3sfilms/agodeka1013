import re


BANNED_AI_PHRASES = [
    "暫定案としては",
    "まずは暫定案として",
    "やってみて",
    "試してみて",
    "感じているかな",
    "教えてくれるかな",
    "できますか？",
    "どうかな？",
    "かな？",
    "無理のない範囲で",
    "おすすめです",
    "重要です",
    "〜しましょう",
]


def guard_training_tone(text: str, user_text: str = "") -> tuple[str, dict]:
    """
    Convert generic fitness-GPT tone into AIあらくん-ish training tone.

    Goal:
    - practical advice remains
    - less polite trainer
    - shorter LINE style
    - no "かな？", no "暫定案としては"
    - no generic soft coach voice
    """
    original = text or ""
    t = original.strip()
    changes = []

    replacements = [
        ("暫定案としては、", ""),
        ("暫定案としては", ""),
        ("まずは暫定案として、", ""),
        ("まずは暫定案として", ""),
        ("やってみてください", "やればいいです"),
        ("やってみて", "やればいいです"),
        ("試してみてください", "試せばいいです"),
        ("試してみて", "試せばいいです"),
        ("おすすめです", "でいいです"),
        ("重要です", "大事です"),
        ("感じているかな？", "ありますか"),
        ("感じているかな", "ありますか"),
        ("教えてくれるかな？", "教えてください"),
        ("教えてくれるかな", "教えてください"),
        ("どうかな？", "どうですか"),
        ("かな？", "ですか"),
        ("しましょう。", "してください。"),
        ("しましょう", "してください"),
        ("無理のない範囲で", "無理せず"),
    ]
    for a, b in replacements:
        if a in t:
            t = t.replace(a, b)
            changes.append(f"replace:{a}->{b}")

    # Remove overly friendly trainer questions at the end.
    t = re.sub(r"肩のトレーニングで、痛みや不快感はありますか[？?]?", "肩に痛みがあるなら重さを落としてください。", t)
    t = re.sub(r"痛みや不快感はありますか[？?]?", "痛みがあるなら重さを落としてください。", t)

    # Normalize polite endings a bit.
    t = t.replace("してみると良いです", "すればいいです")
    t = t.replace("してみるといいです", "すればいいです")
    t = t.replace("すると良いです", "すればいいです")
    t = t.replace("するといいです", "すればいいです")

    # Add AIあらくん-ish edge when it became too bland.
    if not any(x in t for x in ["あはい", "ぼくぅ", "です。", "いいです"]):
        t = "あはい、" + t
        changes.append("prefix_ahai")

    # If user is asking form, make the answer more direct.
    if any(k in user_text for k in ["フォーム", "リアレイズ", "サイドレイズ", "ベンチ", "スクワット", "デッド"]):
        if "フォーム" not in t and "重さ" not in t:
            t += "\n重さよりフォームです。そこでイキるとだいたい変なところに入ります。"
            changes.append("add_form_warning")

    # Trim excessive lines.
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    cleaned = []
    for ln in lines:
        # Remove generic intro lines if too GPT-like.
        if ln in {"もちろんです。", "了解しました。", "わかりました。"}:
            changes.append("remove_generic_intro")
            continue
        cleaned.append(ln)

    # Keep LINE short.
    if len(cleaned) > 7:
        cleaned = cleaned[:7]
        changes.append("trim_lines")

    t = "\n".join(cleaned).strip()

    # Fallback if weirdly empty.
    if not t:
        t = "あはい、重さよりフォームです。痛みがあるならやめてください。"
        changes.append("fallback_empty")

    return t, {
        "changed": t != original,
        "changes": changes,
    }
