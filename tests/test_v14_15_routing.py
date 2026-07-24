from training_intent import contains_training_intent, classify_training_intent
from current_state_engine import CurrentStateEngine


def test_body_statement_is_not_training():
    assert not contains_training_intent("お尻ぬるぬるする")
    assert not classify_training_intent("お尻ぬるぬるする")["is_training"]


def test_body_request_is_training():
    assert contains_training_intent("肩のメニュー教えて")
    assert classify_training_intent("肩のメニュー教えて")["is_training"]


def test_exercise_question_is_training():
    assert contains_training_intent("スクワット何kg？")


def test_first_message_is_considered_without_history():
    state = CurrentStateEngine().classify(
        "お尻ぬるぬるする", history=[], last_topic_terms=[], search_result={}, is_first_message=True
    )
    assert state["is_first_message"] is True
    assert state["should_consider_reply"] is True
    assert state["preferred_route"] == "scene_then_fallback"


def test_stop_still_silences_first_message():
    state = CurrentStateEngine().classify(
        "やめて", history=[], last_topic_terms=[], search_result={}, is_first_message=True
    )
    assert state["should_consider_reply"] is False
    assert state["preferred_route"] == "silence"
