import re


def guard_reply(
    text: str,
    user_text: str = "",
    preserve_long: bool = False,
):
    """
    Light style guard.

    v14.27:
    Historical Replay can set preserve_long=True so an actual long past reply
    (including lyric/chant-like text) is not truncated merely for length.
    Generated replies keep the existing compact LINE guard.
    """
    info = {
        "changed": False,
        "bad_before": False,
        "reason": [],
        "bad_after": False,
    }
    t = (text or "").strip()
    before = t

    t = re.sub(
        r"^候補[A-Da-d0-9]*[:：]\s*",
        "",
        t,
    ).strip()
    t = re.sub(
        r"^(橋本新|橋本|あらくん)[:：]\s*",
        "",
        t,
    ).strip()
    if t != before:
        info["changed"] = True
        info["reason"].append("label_removed")

    bad_ai = [
        "AIとして",
        "私はAI",
        "橋本新では",
        "本人では",
        "モデルとして",
    ]
    for bad in bad_ai:
        if bad in t:
            info["bad_before"] = True
            t = t.replace(bad, "")
            info["changed"] = True
            info["reason"].append(
                f"ai_self_removed:{bad}"
            )

    before = t
    t = t.replace(
        "だわか",
        "ですか",
    ).replace(
        "んだわか",
        "んですか",
    )
    if t != before:
        info["changed"] = True
        info["reason"].append(
            "broken_fragment_fixed"
        )

    t = t.strip()

    if not preserve_long and len(t) > 80:
        t = t[:80].rstrip()
        info["changed"] = True
        info["reason"].append("trimmed")

    if preserve_long:
        info["reason"].append(
            f"historical_replay_length_preserved:{len(t)}"
        )

    if any(bad in t for bad in bad_ai):
        info["bad_after"] = True

    return t, info
