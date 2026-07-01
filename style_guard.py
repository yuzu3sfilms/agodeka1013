import re


def guard_reply(text: str, user_text: str = ""):
    """
    v14:
    Light guard only.

    Earlier versions over-edited endings and broke Japanese.
    In v14, actual past replies are preferred, so do not mechanically
    rewrite normal Japanese. Only remove obvious AI self-explanations,
    candidate labels, and broken fragments.
    """
    info = {"changed": False, "bad_before": False, "reason": [], "bad_after": False}
    t = (text or "").strip()

    before = t
    t = re.sub(r"^候補[A-Da-d0-9]*[:：]\s*", "", t).strip()
    t = re.sub(r"^(橋本新|橋本|あらくん)[:：]\s*", "", t).strip()
    if t != before:
        info["changed"] = True
        info["reason"].append("label_removed")

    bad_ai = ["AIとして", "私はAI", "橋本新では", "本人では", "モデルとして"]
    for b in bad_ai:
        if b in t:
            info["bad_before"] = True
            t = t.replace(b, "")
            info["changed"] = True
            info["reason"].append(f"ai_self_removed:{b}")

    # Fix known broken fragments from older cleanup.
    before = t
    t = t.replace("だわか", "ですか").replace("んだわか", "んですか")
    if t != before:
        info["changed"] = True
        info["reason"].append("broken_fragment_fixed")

    # Keep it LINE-like, but don't destroy Japanese.
    t = t.strip()
    if len(t) > 80:
        t = t[:80].rstrip()
        info["changed"] = True
        info["reason"].append("trimmed")

    if any(b in t for b in bad_ai):
        info["bad_after"] = True

    return t, info
