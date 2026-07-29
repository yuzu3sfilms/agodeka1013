from dialogue_manager import DialogueManager


def test_role_labelled_history_contains_both_sides():
    dm = DialogueManager()
    dm.add("c", "user", "筋トレ教えて")
    dm.add("c", "assistant", "スクワットとローイングでいいです")
    ctx = dm.context("c", "それ何？")
    assert "user: 筋トレ教えて" in ctx
    assert "assistant: スクワットとローイングでいいです" in ctx
    assert ctx.endswith("user: それ何？")


def test_short_reaction_is_repair_request():
    dm = DialogueManager()
    dm.add("c", "assistant", "カメラ用語")
    rel = dm.classify("c", "え？")
    assert rel["relation"] == "repair_request"
    assert rel["use_previous_assistant"] is True


def test_explicit_reference_uses_previous_answer():
    dm = DialogueManager()
    dm.add("c", "assistant", "ローイングを3セット")
    rel = dm.classify("c", "それって何？")
    assert rel["relation"] == "repair_request"


def test_repeated_term_is_followup_not_new_search():
    dm = DialogueManager()
    dm.add("c", "assistant", "シャッタースローペチョをやります")
    rel = dm.classify("c", "シャッタースローペチョって何？")
    assert rel["relation"] == "followup"
    assert rel["reason"] == "topic_overlap_with_previous_answer"


def test_unrelated_short_question_is_new_utterance():
    dm = DialogueManager()
    dm.add("c", "assistant", "スクワットを3セット")
    rel = dm.classify("c", "明日の天気は？")
    assert rel["relation"] == "new_utterance"


def test_elliptical_followup_uses_previous_exchange():
    dm = DialogueManager()
    dm.add("c", "assistant", "週2回からでいいです")
    rel = dm.classify("c", "じゃあ何回？")
    assert rel["relation"] == "followup"


def test_explicit_topic_shift_does_not_inherit():
    dm = DialogueManager()
    dm.add("c", "assistant", "ベンチをやります")
    rel = dm.classify("c", "ところで映画の話だけど")
    assert rel["relation"] == "topic_shift"
    assert rel["use_previous_assistant"] is False
