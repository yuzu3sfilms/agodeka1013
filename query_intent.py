import re


INTENT_PATTERNS = [
    ("memory_recall", [
        r"覚えてる", r"おぼえてる", r"覚えています", r"記憶", r"前(?:の|に)", r"昔", r"古", r"懐かし", r"なつかし",
    ]),
    ("meaning_explain", [
        r"それ何", r"何それ", r"なにそれ", r"なんだっけ", r"何だっけ", r"どういう", r"どゆこと",
        r"意味", r"説明", r"由来", r"なんで", r"なぜ", r"何の話", r"なんの話",
    ]),
    ("existence_check", [
        r"ある\??$", r"あります\??$", r"あった\??$", r"いる\??$", r"いた\??$", r"存在", r"あんの",
    ]),
    ("count_question", [
        r"何個", r"何人", r"何枚", r"何回", r"いくつ", r"何本", r"何杯",
    ]),
    ("time_question", [
        r"いつ", r"何時", r"何日", r"何年", r"何月", r"どの時", r"いつ頃",
    ]),
    ("place_question", [
        r"どこ", r"何処", r"場所", r"どこで",
    ]),
    ("person_question", [
        r"誰", r"だれ", r"誰が", r"だれが", r"誰の", r"だれの",
    ]),
    ("yesno_check", [
        r"なの\??$", r"だっけ\??$", r"でしょ\??$", r"じゃない\??$", r"よね\??$", r"か\??$",
    ]),
    ("attention_only", [
        r"^(ねえ|ねぇ|ちょっと|おい|あの|なあ|なぁ)$",
    ]),
]


def classify_query_intents(text: str):
    text = text or ""
    intents = []
    for name, patterns in INTENT_PATTERNS:
        if any(re.search(p, text, re.I) for p in patterns):
            intents.append(name)

    # Generic question fallback.
    if not intents and re.search(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|どう", text):
        intents.append("generic_question")

    # Very short topic ping.
    if not intents and len(text.strip()) <= 14:
        intents.append("short_ping")

    return list(dict.fromkeys(intents))


def intent_profile(text: str):
    intents = classify_query_intents(text)
    return {
        "intents": intents,
        "wants_memory": any(x in intents for x in ["memory_recall"]),
        "wants_explanation": any(x in intents for x in ["meaning_explain"]),
        "wants_expansion": any(x in intents for x in ["memory_recall", "meaning_explain", "generic_question"]),
        "wants_exact_answer": any(x in intents for x in ["count_question", "time_question", "place_question", "person_question", "existence_check"]),
        "attention_only": "attention_only" in intents,
    }
