import re
from collections import Counter

from utils import normalize
from query_intent import intent_profile
from japanese_analysis import analyze_content


CALL_TERMS = ["顎", "アゴ", "橋本", "橋本新", "あらくん", "あらた", "AGODEKA"]
STOP_TERMS = ["もういい", "黙って", "だまって", "やめて", "やめろ", "終わり", "終了", "関係ない", "別の話", "停止"]
ATTENTION_ONLY_TERMS = {"ねえ", "ねぇ", "ちょっと", "おい", "あの", "うん", "はい", "なるほど", "ふむ", "なあ", "なぁ", "うん", "はい", "なるほど", "ふむ"}

QUESTION_RE = re.compile(r"[？?]|何|なに|誰|だれ|どこ|いつ|なんで|なぜ|どう|何個|何人|何枚|何回|いくつ")
COUNT_RE = re.compile(r"何個|何人|何枚|何回|いくつ|何本|何杯")
REACTION_RE = re.compile(r"^(笑|草|w+|www+|え|え？|は？|まじ|マジ|やば|きも|きゃぴ|ｷｬﾋﾟ|ぽつ|ぽつお|うんち|ペヤング)$", re.I)
NOSTALGIA_CUES = ["なつかしい", "懐かしい"]
EXPAND_CUES = ["なに", "何", "それ何", "どんな", "話", "エピソード", "説明", "由来", "なんだっけ", "覚えてる"]


def extract_topic_terms(text: str):
    """Fallback only; primary terms should come from DynamicSearch."""
    return list(analyze_content(text).topics)


class CurrentStateEngine:
    """
    v14.7:
    Understand current LINE conversation state before retrieval.

    This does not try to be a full human mind-reader.
    It gives the bot enough state to avoid treating every message as an isolated query.
    """

    def __init__(self):
        pass

    def called_directly(self, text: str) -> bool:
        nt = normalize(text)
        return any(normalize(t) in nt for t in CALL_TERMS)

    def stopped(self, text: str) -> bool:
        nt = normalize(text)
        return any(normalize(t) in nt for t in STOP_TERMS)

    def classify(self, user_text: str, history=None, last_topic_terms=None, search_result=None, is_first_message: bool = False):
        history = list(history or [])
        last_topic_terms = list(last_topic_terms or [])
        search_result = search_result or {}

        text = user_text or ""
        stripped = text.strip()
        recent_text = "\n".join(history[-8:])

        topic_terms = list(search_result.get("topic_terms") or [])
        if not topic_terms:
            topic_terms = extract_topic_terms(text)

        attention_only = stripped in ATTENTION_ONLY_TERMS

        inherited_topic = False
        if not attention_only and not topic_terms and last_topic_terms and (QUESTION_RE.search(text) or len(stripped) <= 14):
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

        # Current conversation mode
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

        # Whether bot should consider replying without direct call.
        # Group LINE should not answer everything; but if relevant scene exists, short pings can reply.
        should_consider_reply = False
        if stopped:
            should_consider_reply = False
        elif is_first_message:
            # The first incoming utterance is real input, not a wake token to discard.
            should_consider_reply = True
        elif called or is_question or bare_topic or reaction_like or attention_only:
            should_consider_reply = True
        elif search_result.get("episodes"):
            should_consider_reply = True
        elif last_topic_terms and short:
            should_consider_reply = True

        # Preferred route
        if stopped:
            preferred_route = "silence"
        elif is_first_message and reaction_like:
            preferred_route = "fallback_only"
        elif is_first_message and short and not is_question:
            preferred_route = "scene_then_fallback"
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
        elif bare_topic or reaction_like or short:
            preferred_route = "scene_replay"
        elif is_question:
            preferred_route = "canon_then_scene"
        else:
            preferred_route = "scene_then_fallback"

        state = {
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
        }
        return state
