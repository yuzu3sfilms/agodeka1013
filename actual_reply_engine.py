import gzip
import json
import os
import re
from pathlib import Path

from utils import normalize
from query_intent import intent_profile


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
        self.min_score = int(os.environ.get("REPLAY_MIN_SCORE", "80"))
        self.scenes = []
        self._load()

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

    def _is_bad_replay(self, reply: str):
        r = (reply or "").strip()
        if not r or r in BAD_DIRECT_REPLIES:
            return True
        if len(r) > 90:
            return True
        return False

    def _query_state(self, user_text: str, context: str, topic_terms=None):
        topic_terms = topic_terms or []
        recent_context = "\n".join((context or "").splitlines()[-8:])
        text = recent_context + "\n" + (user_text or "") + "\n" + " ".join(topic_terms)
        tokens = extract_tokens(text)
        for t in topic_terms:
            if t:
                tokens.append(t)
        speakers = []
        for line in recent_context.splitlines():
            if ":" in line:
                speakers.append(line.split(":", 1)[0])
        return {
            "text": text,
            "tokens": list(dict.fromkeys(tokens)),
            "speakers": list(dict.fromkeys(speakers[-8:])),
            "is_question": bool(re.search(r"[？?]|何|なに|誰|どこ|いつ|なんで|どう", user_text or "")),
            "topic_terms": topic_terms,
        }

    def _unsupported_assertion(self, reply: str, source_scene: str):
        for w in ASSERTION_WORDS:
            if w in reply and w not in source_scene:
                return w
        return None

    def score_scene(self, scene: dict, user_text: str, context: str, topic_terms=None):
        reply = scene.get("reply", "")
        if self._is_bad_replay(reply):
            return None

        q = self._query_state(user_text, context, topic_terms)
        if not q["tokens"] and not q["speakers"]:
            return None

        scene_text = scene.get("scene") or scene.get("context", "")
        nscene = normalize(scene_text)
        anchors = set(scene.get("anchors", []) or scene.get("tokens", []) or [])
        reply_tokens = set(scene.get("reply_tokens", []) or [])
        scene_speakers = set(scene.get("speakers", []) or scene.get("prev_speakers", []) or [])

        score = 0
        reasons = []
        matches = []

        # Token overlap with whole scene, not only direct prev line.
        for t in q["tokens"]:
            nt = normalize(t)
            if not nt:
                continue
            in_anchor = any(normalize(a) == nt for a in anchors)
            in_scene = nt in nscene
            in_reply = any(normalize(rt) == nt for rt in reply_tokens)

            if in_anchor or in_scene:
                add = 16 + min(len(nt), 8) * 2
                score += add
                matches.append(t)
            if in_reply:
                # If the user's actual wording appears in Hashimoto's real reply,
                # this is usually the best replay candidate.
                score += 42
                reasons.append(f"reply_token:{t}")

        if matches:
            reasons.append("scene_overlap:" + ",".join(matches[:6]))

        # Topic terms are strong, but they can appear anywhere in the scene.
        for t in q["topic_terms"]:
            if t and normalize(t) in nscene:
                score += 42
                reasons.append(f"topic_scene:{t}")
            if t and any(normalize(rt) == normalize(t) for rt in reply_tokens):
                score += 20
                reasons.append(f"topic_reply:{t}")

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

    def search(self, user_text: str, context: str = "", topic_terms=None, limit: int = 6):
        results = []
        for scene in self.scenes:
            s = self.score_scene(scene, user_text, context, topic_terms=topic_terms)
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

    def choose(self, user_text: str, context: str = "", topic_terms=None):
        hits = self.search(user_text, context, topic_terms=topic_terms, limit=6)
        if not hits:
            return None, {"used": False, "reason": "no_scene_replay_hit", "hits": []}
        best = hits[0]
        return best["reply"], {"used": True, "mode": "scene_replay", "chosen": best, "hits": hits}
