from current_state_engine import CurrentStateEngine
from dynamic_search import DynamicSearch
from query_intent import intent_profile
from japanese_analysis import analyze_content


def test_generic_question_is_not_episode_expansion():
    for text in ["壊したら？", "明日行ったらどうなる？", "それを食べたら？"]:
        prof = intent_profile(text)
        assert prof["is_hypothetical"] is True
        assert prof["wants_expansion"] is False


def test_only_explicit_continuation_requests_expand_episode():
    for text in ["その後どうなった？", "続きは？", "もっと詳しく"]:
        assert intent_profile(text)["wants_expansion"] is True


def test_mixed_japanese_content_is_not_split_into_hiragana_noise():
    analysis = analyze_content("手すり折って暴れたら？")
    assert "手すり" in analysis.topics
    assert "って" not in analysis.topics
    assert "れたら" not in analysis.topics


def test_state_routes_hypothetical_as_question_not_episode_expand():
    state = CurrentStateEngine().classify(
        "手すり折って暴れたら？",
        history=["前の発言"],
        last_topic_terms=["別件"],
        search_result={"topic_terms": ["手すり"], "episodes": []},
    )
    assert state["intent"] == "hypothetical_question"
    assert state["preferred_route"] == "scene_then_fallback"
    assert state["expand_cue"] is False


def test_dynamic_search_uses_shared_content_terms(tmp_path):
    # No corpus is needed to verify extraction behavior.
    search = DynamicSearch(data_dir=str(tmp_path))
    terms, predicates, topic_terms, generic_terms = search.extract_terms("手すり折って暴れたら？")
    assert "手すり" in terms
    assert "って" not in terms
    assert "れたら" not in terms
