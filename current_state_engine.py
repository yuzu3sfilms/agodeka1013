import re

from utils import normalize
from query_intent import intent_profile
from japanese_analysis import analyze_content
from conversation_context import get_context, resolve_query


CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA"]
STOP_TERMS = [
    "もういい", "黙って", "だまって", "やめて", "やめろ",
    "終わり", "終了", "関係ない", "別の話", "停止",
]
ATTENTION_ONLY_TERMS = {
    "ねえ", "ねぇ", "ちょっと", "おい", "あの",
    "うん", "はい", "なるほど", "ふむ", "なあ", "なぁ",
}
QUESTION_RE = re.compile(
    r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|"
    r"何個|何人|何枚|何回|いくつ"
)
COUNT_RE = re.compile(r"何個|何人|何枚|何回|いくつ|何本|何杯")
REACTION_RE = re.compile(
    r"^(笑|草|w+|www+|え|え？|は？|まじ|マジ|やば|きも|"
    r"きゃぴ|ｷｬﾋﾟ|ぽつ|ぽつお|うんち|ペヤング)$",
    re.I,
)


def extract_topic_terms(text: str):
    return list(analyze_content(text).topics)


def _install_dynamic_search_context_hook():
    try:
        from dynamic_search import DynamicSearch
    except Exception:
        return

    original = getattr(DynamicSearch, "search", None)
    if not original or getattr(
        original,
        "_ago_v14_25_context_hook",
        False,
    ):
        return

    def context_aware_search(self, query, *args, **kwargs):
        resolved_query, context = resolve_query(query)
        result = original(self, resolved_query, *args, **kwargs)
        if isinstance(result, dict):
            result["raw_query"] = query
            result["resolved_query"] = resolved_query
            result["conversation_state"] = context
            result["inherited_topic"] = bool(
                context.get("subject_inherited")
            )
            result["resolved_subject"] = context.get(
                "resolved_subject",
                "",
            )
        return result

    context_aware_search._ago_v14_25_context_hook = True
    context_aware_search._ago_v14_25_original = original
    DynamicSearch.search = context_aware_search


_install_dynamic_search_context_hook()


class CurrentStateEngine:
    """Current-message interpretation enriched by conversation state."""

    def __init__(self):
        pass

    def called_directly(self, text: str) -> bool:
        normalized = normalize(text)
        return any(normalize(term) in normalized for term in CALL_TERMS)

    def stopped(self, text: str) -> bool:
        normalized = normalize(text)
        return any(normalize(term) in normalized for term in STOP_TERMS)

    def classify(
        self,
        user_text: str,
        history=None,
        last_topic_terms=None,
        search_result=None,
        is_first_message: bool = False,
    ):
        history = list(history or [])
        last_topic_terms = list(last_topic_terms or [])
        search_result = search_result or {}
        conversation = dict(
            search_result.get("conversation_state")
            or get_context()
        )

        text = user_text or ""
        stripped = text.strip()
        topic_terms = list(search_result.get("topic_terms") or [])
        if not topic_terms:
            topic_terms = extract_topic_terms(
                search_result.get("resolved_query") or text
            )

        attention_only = stripped in ATTENTION_ONLY_TERMS
        inherited_topic = bool(
            search_result.get("inherited_topic")
            or conversation.get("subject_inherited")
        )

        # Root fix: shortness alone never inherits an old topic.
        # Only resolved conversational follow-ups may inherit it.
        if (
            not attention_only
            and not topic_terms
            and last_topic_terms
            and conversation.get("follow_up_question")
            and conversation.get("subject_inherited")
        ):
            topic_terms = last_topic_terms[:4]
            inherited_topic = True

        is_question = bool(QUESTION_RE.search(text))
        is_count_question = bool(COUNT_RE.search(text))
        called = self.called_directly(text)
        stopped = self.stopped(text)
        short = len(stripped) <= 14
        bare_topic = short and bool(topic_terms) and not is_question
        reaction_like = bool(REACTION_RE.search(stripped))
        qprof = intent_profile(text)

        nostalgia_cue = qprof.get("wants_memory", False)
        expand_cue = qprof.get("wants_expansion", False)
        explanation_cue = qprof.get("wants_explanation", False)
        hypothetical = qprof.get("is_hypothetical", False)
        exact_answer_cue = qprof.get("wants_exact_answer", False)

        if stopped:
            intent = "stop"
        elif is_count_question:
            intent = "canon_question"
        elif exact_answer_cue:
            intent = "exact_answer_question"
        elif reaction_like:
            intent = "reaction_ping"
        elif nostalgia_cue or expand_cue:
            intent = "episode_expand"
        elif explanation_cue:
            intent = "explanation_question"
        elif hypothetical:
            intent = "hypothetical_question"
        elif conversation.get("follow_up_question"):
            intent = "follow_up_question"
        elif is_question:
            intent = "question"
        elif called:
            intent = "direct_call"
        elif attention_only:
            intent = "attention_ping"
        elif bare_topic:
            intent = "topic_ping"
        elif short:
            intent = "short_chat"
        else:
            intent = "statement"

        if stopped:
            should_consider_reply = False
        elif is_first_message:
            should_consider_reply = True
        elif called or is_question or bare_topic or reaction_like or attention_only:
            should_consider_reply = True
        elif search_result.get("episodes"):
            should_consider_reply = True
        else:
            should_consider_reply = False

        if stopped:
            preferred_route = "silence"
        elif is_count_question:
            preferred_route = "canon"
        elif exact_answer_cue:
            preferred_route = "canon_then_scene"
        elif reaction_like:
            preferred_route = "fallback_only"
        elif nostalgia_cue or expand_cue:
            preferred_route = "episode_expand"
        elif explanation_cue or hypothetical:
            preferred_route = "scene_then_fallback"
        elif attention_only:
            preferred_route = "fallback_only"
        elif conversation.get("follow_up_question"):
            preferred_route = "scene_replay"
        elif bare_topic:
            preferred_route = "scene_replay"
        elif is_question:
            preferred_route = "canon_then_scene"
        elif short:
            preferred_route = "scene_then_fallback"
        else:
            preferred_route = "scene_then_fallback"

        return {
            "intent": intent,
            "preferred_route": preferred_route,
            "called": called,
            "question": is_question,
            "count_question": is_count_question,
            "short": short,
            "bare_topic": bare_topic,
            "reaction_like": reaction_like,
            "attention_only": attention_only,
            "nostalgia_cue": nostalgia_cue,
            "expand_cue": expand_cue,
            "explanation_cue": explanation_cue,
            "hypothetical": hypothetical,
            "exact_answer_cue": exact_answer_cue,
            "query_intents": qprof.get("intents", []),
            "stopped": stopped,
            "topic_terms": topic_terms,
            "inherited_topic": inherited_topic,
            "last_topic_terms": last_topic_terms[:4],
            "should_consider_reply": should_consider_reply,
            "recent_history_size": len(history),
            "is_first_message": bool(is_first_message),
            "follow_up_question": bool(
                conversation.get("follow_up_question")
            ),
            "subject_inherited": bool(
                conversation.get("subject_inherited")
            ),
            "resolved_subject": conversation.get(
                "resolved_subject",
                "",
            ),
            "resolved_query": (
                search_result.get("resolved_query")
                or conversation.get("resolved_query")
                or text
            ),
            "topic_stack": conversation.get("topic_stack", []),
            "conversation_relation": conversation.get(
                "relation",
                "",
            ),
        }
