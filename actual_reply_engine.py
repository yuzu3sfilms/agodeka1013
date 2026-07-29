import gzip
import json
import os
import re
from pathlib import Path
from collections import Counter
import math

from utils import normalize
from query_intent import intent_profile
from persona_policy import PersonaPolicy
from behavior_taxonomy import classify_reply, classify_stimulus


MEDIA_REPLIES = {
    "[写真]", "[動画]", "[スタンプ]",
    "グループ通話が終了しました。",
    "グループ音声通話が開始されました。",
    "Liveが終了しました。",
}
BAD_DIRECT_REPLIES = MEDIA_REPLIES | {"?", "？", "↑", "…", "…。", ""}
ASSERTION_WORDS = ["好き", "嫌い", "予定", "つもり", "食べました", "食べたこと", "絶対", "いつも"]

NOSTALGIA_CUES = ["なつかしい", "懐かしい"]
EXPAND_CUES = ["なに", "何", "それ何", "どんな", "話", "エピソード", "説明", "由来", "なんだっけ", "覚えてる"]




def _reply_has_substantive_episode_content(reply: str):
    r = reply or ""
    # Not a hard truth detector; just a general signal that the reply carries
    # more than an exact topic echo.
    return (
        len(r) >= 16
        or bool(re.search(r"とは|という|呼び|なつかし|懐かし|あります|ありま|いた|いました|何時|どこ|誰|だれ|ぼくぅ|です|ます", r))
    )


def _is_bare_topic_echo(reply: str, topic_terms):
    topic_terms = [t for t in (topic_terms or []) if t]
    if not topic_terms:
        return False
    r = re.sub(r"[。…。！？!?、\s]+", "", reply or "")
    joined = "".join(topic_terms)
    # e.g. reply "グランド土塚…。" when topic_terms are ["グランド", "土塚"]
    return r == joined or all(t in r for t in topic_terms) and len(r) <= len(joined) + 4


def extract_tokens(text: str):
    toks = re.findall(
        r"[ぁ-んー]{2,}|[ァ-ヴｦ-ﾟー]{2,}|[A-Za-z][A-Za-z0-9_\-]{2,}|[一-龥々〆ヵヶ]{2,}|[0-9０-９]+\s*(?:個|人|枚|回|本|杯|兆個|兆)",
        text or "",
    )
    bad = {"今日", "明日", "昨日", "これ", "それ", "あれ", "する", "した", "して", "いる", "ある", "ない", "何個", "何回", "ねえ", "ちょっと", "おい", "あの", "えっと", "うん", "はい"}
    return [t for t in toks if t not in bad]


class ActualReplyEngine:
    """
    v14.5:
    Conversation-state replay engine with general query-intent ranking.

    LINE group replies are not always direct replies to the immediately
    previous message. So we index whole scenes around Hashimoto's utterances,
    not only prev-message -> reply pairs.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.scene_path = self.data_dir / "conversation_scenes.jsonl.gz"
        self.max_items = int(os.environ.get("REPLAY_MAX_SCENES", "5546"))
        self.min_score = int(os.environ.get("REPLAY_MIN_SCORE", "120"))
        self.scenes = []
        self.reply_frequency = Counter()
        self.pattern_frequency = Counter()
        self.speaker_frequency = Counter()
        self.persona_policy = PersonaPolicy(data_dir)
        self._load()
        self._build_persona_statistics()

    def _load(self):
        if not self.scene_path.exists():
            return
        with gzip.open(self.scene_path, "rt", encoding="utf-8") as f:
            for n, line in enumerate(f):
                if n >= self.max_items:
                    break
                try:
                    item = json.loads(line)
                    self.scenes.append(item)
                except Exception:
                    continue


    @staticmethod
    def _reply_pattern(reply: str) -> str:
        return classify_reply(reply)

    def _build_persona_statistics(self):
        for scene in self.scenes:
            reply = (scene.get("reply") or "").strip()
            if not reply or self._is_bad_replay(reply):
                continue
            self.reply_frequency[normalize(reply)] += 1
            self.pattern_frequency[self._reply_pattern(reply)] += 1
            for sp in set(scene.get("speakers", []) or scene.get("prev_speakers", []) or []):
                if sp:
                    self.speaker_frequency[sp] += 1

    @staticmethod
    def _context_tokens(context: str):
        recent = "\n".join((context or "").splitlines()[-6:])
        return {normalize(t) for t in extract_tokens(recent) if normalize(t)}

    def _persona_prior(self, scene: dict, reply: str, context: str, current_speaker: str | None):
        """Soft priors applied only after exact-current-anchor eligibility.

        We cap every component so common acknowledgements cannot overpower a
        concrete rare episode.
        """
        bonus = 0
        reasons = []

        exact_freq = self.reply_frequency.get(normalize(reply), 0)
        if exact_freq > 1:
            b = min(10, round(math.log2(exact_freq + 1) * 2))
            bonus += b
            reasons.append(f"exact_reply_frequency:{exact_freq}:+{b}")

        pattern = self._reply_pattern(reply)
        pattern_freq = self.pattern_frequency.get(pattern, 0)
        if pattern_freq > 1:
            b = min(12, round(math.log2(pattern_freq + 1)))
            bonus += b
            reasons.append(f"pattern_frequency:{pattern}:{pattern_freq}:+{b}")

        scene_speakers = set(scene.get("speakers", []) or scene.get("prev_speakers", []) or [])
        if current_speaker and current_speaker in scene_speakers:
            bonus += 15
            reasons.append(f"same_partner:{current_speaker}:+15")

        context_tokens = self._context_tokens(context)
        anchors = self._exact_anchor_set(scene)
        overlap = sorted(context_tokens & anchors)
        if overlap:
            b = min(18, len(overlap) * 10)
            bonus += b
            reasons.append(f"conversation_continuity:{','.join(overlap[:4])}:+{b}")

        # Corpus-derived policy is a soft prior only. Eligibility still comes
        # from the current-turn evidence gate above this reranker.
        policy = getattr(self, "persona_policy", None)
        if policy is not None:
            policy_bonus, policy_reasons = policy.action_bonus(
                pattern,
                current_speaker=current_speaker,
                situation=classify_stimulus((context or "").splitlines()[-1] if (context or "").splitlines() else ""),
            )
        else:
            policy_bonus, policy_reasons = 0, []
        bonus += policy_bonus
        reasons.extend(policy_reasons)
        return bonus, reasons

    def _is_bad_replay(self, reply: str):
        r = (reply or "").strip()
        if not r or r in BAD_DIRECT_REPLIES:
            return True
        if len(r) > 90:
            return True
        return False

    def _query_state(self, user_text: str, context: str, topic_terms=None, context_topic_terms=None, intent: str = ""):
        """Build separate evidence channels.

        v14.13 deliberately does not merge previous topics into the user's text.
        Only lexical anchors present in the current utterance may open replay.
        Conversational topics can rank an already-grounded scene, but can never
        make an otherwise ungrounded scene eligible.
        """
        topic_terms = list(topic_terms or [])
        context_topic_terms = list(context_topic_terms or [])
        current_tokens = list(dict.fromkeys(extract_tokens(user_text or "")))
        recent_context = "\n".join((context or "").splitlines()[-6:])
        speakers = []
        for line in recent_context.splitlines():
            if ":" in line:
                speakers.append(line.split(":", 1)[0])
        return {
            "current_text": user_text or "",
            "current_tokens": current_tokens,
            "speakers": list(dict.fromkeys(speakers[-6:])),
            "is_question": bool(re.search(r"[？?]|何|なに|誰|どこ|いつ|なんで|どう", user_text or "")),
            "topic_terms": topic_terms,
            "context_topic_terms": context_topic_terms,
            "intent": intent or "",
        }

    @staticmethod
    def _exact_anchor_set(scene: dict):
        values = list(scene.get("anchors", []) or []) + list(scene.get("reply_tokens", []) or [])
        return {normalize(v) for v in values if normalize(v)}

    def _unsupported_assertion(self, reply: str, source_scene: str):
        for w in ASSERTION_WORDS:
            if w in reply and w not in source_scene:
                return w
        return None

    def score_scene(self, scene: dict, user_text: str, context: str, topic_terms=None, context_topic_terms=None, intent: str = "", current_speaker: str | None = None):
        reply = scene.get("reply", "")
        if self._is_bad_replay(reply):
            return None

        q = self._query_state(user_text, context, topic_terms, context_topic_terms, intent)
        # Evidence gate: vague reactions, refusals and stop signals are never
        # mapped to a historical scene. They are handled by current-state logic.
        if q["intent"] in {"stop", "reaction_ping", "attention_ping"}:
            return None

        scene_text = scene.get("scene") or scene.get("context", "")
        anchors = self._exact_anchor_set(scene)
        current_norm = [normalize(t) for t in q["current_tokens"] if normalize(t)]
        exact_current_matches = [t for t, nt in zip(q["current_tokens"], current_norm) if nt in anchors]

        # A replay candidate must be grounded in at least one exact lexical anchor
        # from the CURRENT message. Speaker overlap, a previous topic, a question
        # mark, or a substring inside a conjugated phrase cannot open this gate.
        if not exact_current_matches:
            return None

        reply_tokens = {normalize(x) for x in (scene.get("reply_tokens", []) or []) if normalize(x)}
        scene_speakers = set(scene.get("speakers", []) or scene.get("prev_speakers", []) or [])

        score = 70
        reasons = ["evidence_gate:exact_current_anchor"]
        matches = list(dict.fromkeys(exact_current_matches))

        for t in matches:
            nt = normalize(t)
            score += 20 + min(len(nt), 10) * 3
            reasons.append(f"current_anchor:{t}")
            if nt in reply_tokens:
                score += 28
                reasons.append(f"current_anchor_in_reply:{t}")

        # Current-message topic terms strengthen an already-open candidate only.
        for t in q["topic_terms"]:
            nt = normalize(t)
            if nt and nt in anchors:
                score += 24
                reasons.append(f"current_topic_anchor:{t}")

        # Inherited context topics are weak ranking evidence. They never qualify
        # a scene on their own and therefore cannot recreate an augmented query.
        for t in q["context_topic_terms"]:
            nt = normalize(t)
            if nt and nt in anchors:
                score += 6
                reasons.append(f"context_topic_support:{t}")

        # Speaker overlap. Useful in group LINE because the target may be several messages back.
        speaker_hits = []
        for sp in q["speakers"]:
            if sp and sp in scene_speakers:
                speaker_hits.append(sp)
        if speaker_hits:
            score += 8 + min(len(speaker_hits), 3) * 8
            reasons.append("speaker_overlap:" + ",".join(speaker_hits[:3]))

        # Question-ish scene similarity.
        if q["is_question"] and scene.get("has_question_before"):
            score += 15
            reasons.append("question_scene")

        # Prefer real short/medium replies.
        l = len(reply)
        if l <= 4:
            score += 5
            reasons.append("very_short_actual")
        elif l <= 18:
            score += 14
            reasons.append("short_actual")
        elif l <= 35:
            score += 6
            reasons.append("medium_actual")
        else:
            score -= 8
            reasons.append("longish_actual")

        # Generic replies are allowed, but only if scene match is strong.
        if reply in {"すみません", "すみませんわかりません", "わかりません", "ありがとうございます", "はい", "わかりました", "うん"}:
            score -= 18
            reasons.append("generic_reply")

        bad_assert = self._unsupported_assertion(reply, scene_text)
        if bad_assert:
            score -= 35
            reasons.append(f"unsupported_in_actual?:{bad_assert}")

        # v14.5: phrase-level match for hiragana predicates like なつかしい.
        # This fixes cases where "なつかしい?" should prefer
        # "グランド土塚なつかしいわあ" over generic repeated topic replies.
        user_tokens = extract_tokens(user_text or "")
        for ut in user_tokens:
            if len(ut) >= 3 and normalize(ut) in normalize(reply):
                score += 55
                reasons.append(f"user_phrase_in_reply:{ut}")

        # v14.5: general query-intent ranking.
        # Do not special-case only "なつかしい". Categorize the user's follow-up
        # and choose actual replies that fit the category.
        qprof = intent_profile(user_text or "")

        if qprof.get("wants_expansion"):
            if _reply_has_substantive_episode_content(reply):
                score += 42
                reasons.append("intent_expand_substantive_reply")
            if _is_bare_topic_echo(reply, topic_terms):
                score -= 45
                reasons.append("intent_expand_penalize_bare_echo")

        if qprof.get("wants_memory"):
            # Memory/nostalgia questions should prefer actual replies that also
            # sound like recall, not just topic echo.
            if re.search(r"なつかし|懐かし|覚え|昔|前|古", reply):
                score += 70
                reasons.append("intent_memory_reply_match")
            elif _is_bare_topic_echo(reply, topic_terms):
                score -= 30
                reasons.append("intent_memory_penalize_bare_echo")

        if qprof.get("wants_explanation"):
            if re.search(r"とは|という|呼び|です|ます|存在|つまり|だから|ので|ため|ソウル|モード|合体|崇め", reply):
                score += 45
                reasons.append("intent_explain_reply_match")
            if _is_bare_topic_echo(reply, topic_terms):
                score -= 40
                reasons.append("intent_explain_penalize_bare_echo")

        if qprof.get("wants_exact_answer"):
            # Exact-answer prompts benefit from replies containing answer-like forms.
            if re.search(r"[0-9０-９]+|あります|ない|いません|います|何時|どこ|誰|だれ", reply):
                score += 28
                reasons.append("intent_exact_answer_like")

        prior_bonus, prior_reasons = self._persona_prior(
            scene=scene, reply=reply, context=context, current_speaker=current_speaker
        )
        score += prior_bonus
        reasons.extend(prior_reasons)

        if score < self.min_score:
            return None

        return {
            "reply": reply,
            "score": score,
            "reasons": reasons,
            "matches": matches[:8],
            "scene_id": scene.get("id"),
            "source_scene": scene_text[-1000:],
            "source_after": "\n".join(scene.get("after", [])[:4]),
        }

    def search(self, user_text: str, context: str = "", topic_terms=None, context_topic_terms=None, intent: str = "", limit: int = 12, current_speaker: str | None = None):
        results = []
        for scene in self.scenes:
            s = self.score_scene(scene, user_text, context, topic_terms=topic_terms, context_topic_terms=context_topic_terms, intent=intent, current_speaker=current_speaker)
            if s:
                results.append(s)
        results.sort(key=lambda x: x["score"], reverse=True)

        out = []
        seen = set()
        for r in results:
            rep = r["reply"]
            if rep in seen:
                continue
            seen.add(rep)
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def choose(self, user_text: str, context: str = "", topic_terms=None, context_topic_terms=None, intent: str = "", current_speaker: str | None = None):
        hits = self.search(
            user_text,
            context,
            topic_terms=topic_terms,
            context_topic_terms=context_topic_terms,
            intent=intent,
            limit=12,
            current_speaker=current_speaker,
        )
        if not hits:
            return None, {"used": False, "reason": "no_scene_replay_hit", "hits": []}
        best = hits[0]
        return best["reply"], {"used": True, "mode": "scene_replay_v14_21_persona_reranked", "chosen": best, "hits": hits}
