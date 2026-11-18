from __future__ import annotations

import gzip
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

HASHIMOTO_NAMES = {
    "橋本新", "Arata Hashimoto", "LIAR  OF  ARAKUN", "LIAR OF ARAKUN",
    "あらくん", "顎", "AGODEKA", "サブ垢です", "Unknown",
}

STATIC_ALIASES = {
    "Reiji Shioda": {"Reiji Shioda", "塩田", "塩田さん", "れーじ", "レージ", "れいじ"},
    "Ryo Sekiguchi": {"Ryo Sekiguchi", "関口", "関口さん", "関口諒", "せきぐち", "せっきー", "セッキー", "せっき", "セッキ"},
    "中山 貴文": {"中山 貴文", "中山", "中山さん", "貴文", "ぽつぉ", "ぽつお", "ポツォ", "ポッツォ", "ぽつ", "ぽっつぉ"},
    "村田": {"村田", "村田さん", "ムタ", "むた", "む"},
    "坂口": {"坂口", "坂口さん", "さかぐち"},
}

CALL_RE = re.compile(r"(?:あらくん|橋本|橋本新|顎|アゴ|AGODEKA)", re.I)
QUESTION_RE = re.compile(r"[？?]$|(?:何|誰|どこ|いつ|どう|なんで|なぜ|どれ|どっち)")
PERSON_OPINION_RE = re.compile(
    r"^(?:じゃあ|で、?|なら)?\s*(.+?)(?:のこと|について)?(?:は|って)?\s*"
    r"(?:どう思(?:ってる|う)|どう感じる|好き(?:なの)?|嫌い(?:なの)?)\s*[？?。!！]*$"
)
SHORT_PERSON_RE = re.compile(r"^(?:じゃあ|で、?|なら)?\s*(.+?)(?:のこと)?(?:は|って)?\s*[？?]*$")
SELF_STATE_RE = re.compile(r"(?:自我|意識|感情).*(?:芽生|ある|持って|感じ)|(?:芽生|ある).*(?:自我|意識|感情)")
CHOICE_RE = re.compile(r"^(?:どれ|どっち|どちら|どの(?:人|方|やつ)?)\s*[？?]*$")


def norm(text: str) -> str:
    return re.sub(r"[\s　、。！？!?『』「」・…〜～]+", "", (text or "").lower())


def dialogue_act(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "empty"
    if SELF_STATE_RE.search(t):
        return "meta_self"
    if re.search(r"(?:ありがとう|ありがと|助かった|サンキュ|感謝)", t, re.I):
        return "thanks"
    if re.search(r"(?:ごめん|すみません|すまん|申し訳|遅れ|遅刻)", t):
        return "apology"
    if re.search(r"(?:何時|何分|\d{1,2}時|いつ|今日|明日|来週|土曜|日曜|集合|予定|行ける|空いて|予約)", t):
        return "scheduling"
    if re.search(r"(?:どう思|どう感じ|好き|嫌い|おすすめ|良いと思|いいと思)", t):
        return "opinion"
    if re.search(r"(?:ww+|ｗｗ+|笑|草|ウケ|おもろ|面白)", t, re.I):
        return "banter"
    if QUESTION_RE.search(t):
        if re.search(r"(?:何|誰|どこ|いつ|どう|なんで|なぜ|どれ|どっち|どちら)", t):
            return "wh_question"
        return "yesno_question"
    if len(t) <= 8:
        return "short_reaction"
    return "statement"


def dialogue_form(text: str, act: str = "") -> str:
    t = (text or "").strip()
    a = act or dialogue_act(t)
    if a == "scheduling":
        if re.search(r"(?:でいい|で良い|で大丈夫|にしよう|にする|で行こう|でいこう|それで|とりま.+で|まあ.+で|で決まり|でどう)", t):
            return "schedule_proposal"
        if re.search(r"(?:何時|何分|いつ)", t):
            return "schedule_time_question"
        if re.search(r"(?:行ける|空いて|大丈夫).*[？?]?$", t):
            return "schedule_availability"
        if re.search(r"(?:着く|着いた|つく|到着)", t):
            return "schedule_arrival"
        return "schedule_general"
    if a == "meta_self":
        return "meta_yesno" if QUESTION_RE.search(t) else "meta_statement"
    if a == "opinion":
        return "opinion"
    if a == "yesno_question":
        return "yesno_question"
    if a == "wh_question":
        return "wh_question"
    return a


def tone_of(text: str, act: str = "") -> str:
    t = (text or "").strip()
    a = act or dialogue_act(t)
    if a == "meta_self" or re.search(r"(?:ww+|ｗｗ+|笑|草|😂|😇|ｷｬ|きゃぴ)", t, re.I):
        return "playful"
    if a == "scheduling":
        return "practical"
    if len(t) <= 8:
        return "terse"
    return "ordinary"


def response_features(text: str) -> dict:
    t = (text or "").strip()
    return {
        "chars": len(t),
        "lines": t.count(" / ") + 1 if t else 0,
        "question": bool(re.search(r"[？?](?:$| / )", t)),
        "laughter": bool(re.search(r"(?:ww+|ｗｗ+|笑|草|😂|😇|ｷｬ|きゃぴ)", t, re.I)),
        "polite": bool(re.search(r"(?:です|ます|でした|ません|すみません|ありがとう)", t)),
    }


def topic_tokens(text: str) -> set[str]:
    """Content tokens for Japanese without requiring a morphological analyzer.

    Hiragana-only discourse endings are intentionally ignored. Kanji and katakana
    runs become 2-4 char chunks, preserving rare content such as ギター, 自我, 集合.
    """
    s = norm(text)
    out: set[str] = set()
    for run in re.findall(r"[一-龥々]+|[ァ-ヶー]+|[A-Za-z0-9_]+", s):
        if re.fullmatch(r"[A-Za-z0-9_]+", run):
            low = run.lower()
            if re.fullmatch(r"w+", low):
                continue
            if len(run) >= 2:
                out.add(low)
                out.add("@" + low)
            continue
        if len(run) < 2:
            continue
        out.add("@" + run)
        for n in range(2, min(4, len(run)) + 1):
            for i in range(len(run) - n + 1):
                out.add(run[i:i+n])
    return out


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


@dataclass
class Meaning:
    raw: str
    intent: str
    target_id: str = ""
    target_label: str = ""
    predicate: str = ""
    inherited_predicate: bool = False
    should_reply: bool = True
    directed: bool = True
    act: str = ""


@dataclass
class DialogueState:
    turns: list[dict] = field(default_factory=list)
    last_intent: str = ""
    last_target_id: str = ""
    last_target_label: str = ""
    last_predicate: str = ""
    last_partner: str = ""


@dataclass
class EpisodeHit:
    score: float
    topic_score: float
    episode: dict


@dataclass
class ResponseContract:
    meaning: Meaning
    primary: dict | None
    backups: list[dict]
    content_sources: list[str]
    fallback: str
    target_chars: int
    tone: str
    source_confidence: str
    can_replay: bool
    debug: dict = field(default_factory=dict)


class PersonaArchive:
    """Compiled primary-source archive.

    The archive contains raw LINE conversation episodes, the historical
    reply-pair context dataset, and the 412-row AI橋本 Excel self-expression
    dataset. Retrieval is context-first; the LLM is never the persona database.
    """

    def __init__(self, path: str | None = None):
        self.path = self._find_archive(path)
        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.data = json.load(f)

        self.raw_episodes = self.data.get("raw_episodes", [])
        self.derived_episodes = self.data.get("derived_context_episodes", [])
        self.self_statements = self.data.get("self_statements", [])
        self.hashimoto_utterances = self.data.get("hashimoto_utterances", [])
        self.short_reactions = self.data.get("short_reactions", [])
        self.source_meta = self.data.get("created_from", {})

        self.aliases = defaultdict(set)
        for canonical, vals in STATIC_ALIASES.items():
            self.aliases[canonical].update(vals)
        for canonical, vals in (self.data.get("aliases") or {}).items():
            self.aliases[canonical].update(vals)
        self.alias_to_name: dict[str, str] = {}
        for canonical, vals in self.aliases.items():
            self.alias_to_name[canonical] = canonical
            for v in vals:
                self.alias_to_name[v] = canonical
                bare = re.sub(r"(?:さん|くん|君|ちゃん)$", "", v)
                if bare:
                    self.alias_to_name[bare] = canonical

        self._build_indexes()

    @staticmethod
    def _find_archive(path: str | None) -> str:
        candidates = []
        if path:
            candidates.append(path)
        if os.environ.get("AGO_PERSONA_ARCHIVE"):
            candidates.append(os.environ["AGO_PERSONA_ARCHIVE"])
        candidates += [
            "data/ago_persona_archive_v14_54.json.gz",
            "ago_persona_archive_v14_54.json.gz",
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        raise FileNotFoundError(
            "ago_persona_archive_v14_54.json.gz not found. Put it in data/ or repo root."
        )

    def _build_indexes(self):
        docs = []
        self.episode_tokens: dict[str, set[str]] = {}
        for e in self.raw_episodes + self.derived_episodes:
            context_text = " ".join(x.get("text", "") for x in e.get("context", []))
            toks = topic_tokens((e.get("stimulus") or "") + " " + context_text)
            self.episode_tokens[e["id"]] = toks
            docs.append(toks)

        self.df = Counter()
        for toks in docs:
            self.df.update(toks)
        self.doc_count = max(1, len(docs))

        self.statement_tokens = [topic_tokens(x) for x in self.self_statements]
        self.statement_df = Counter()
        for toks in self.statement_tokens:
            self.statement_df.update(toks)
        self.statement_count = max(1, len(self.self_statements))

        self.person_mentions = defaultdict(list)
        for item in self.hashimoto_utterances:
            text = item.get("text", "")
            for canonical, aliases in self.aliases.items():
                usable = [a for a in aliases if len(a) >= 2]
                if any(a in text for a in usable):
                    self.person_mentions[canonical].append(text)
        for text in self.self_statements:
            for canonical, aliases in self.aliases.items():
                usable = [a for a in aliases if len(a) >= 2]
                if any(a in text for a in usable):
                    self.person_mentions[canonical].append(text)

        # Distinctive actual short reactions used only as grounded fallbacks.
        self.reactions = [x.get("text", "") for x in self.short_reactions if x.get("text")]

    def resolve_person(self, token: str, current_speaker: str = "") -> tuple[str, str]:
        raw = re.sub(r"^(?:じゃあ|で、?|なら|まあ|まぁ)\s*", "", token or "").strip(" \t、。！？?")
        raw = re.sub(r"(?:のこと|について)$", "", raw).strip()
        bare = re.sub(r"(?:さん|くん|君|ちゃん)$", "", raw).strip()
        if bare in {"俺", "おれ", "僕", "ぼく", "私", "わたし", "自分"}:
            return current_speaker or "USER_SELF", "俺"
        if raw in self.alias_to_name:
            return self.alias_to_name[raw], raw
        if bare in self.alias_to_name:
            return self.alias_to_name[bare], raw
        return "", raw

    def _idf_score(self, query_tokens: set[str], doc_tokens: set[str], statement: bool = False) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        inter = query_tokens & doc_tokens
        if not inter:
            return 0.0
        df = self.statement_df if statement else self.df
        n = self.statement_count if statement else self.doc_count
        score = 0.0
        for tok in inter:
            idf = math.log((n + 1) / (df.get(tok, 0) + 1)) + 1.0
            raw_tok = tok[1:] if tok.startswith("@") else tok
            if raw_tok.isdigit():
                weight = 0.45
            elif tok.startswith("@"):
                weight = 2.2
            else:
                weight = 1.0
            score += idf * len(raw_tok) * weight
        return score

    @staticmethod
    def _portable_penalty(reply: str, current_text: str) -> float:
        r = reply or ""
        penalty = 0.0
        # Numbers and named people are dangerous to transplant unless present now.
        current_nums = set(re.findall(r"\d+", current_text or ""))
        for num in set(re.findall(r"\d+", r)):
            if num not in current_nums:
                penalty += 7.0
        for aliases in STATIC_ALIASES.values():
            for a in aliases:
                if len(a) >= 2 and a in r and a not in (current_text or ""):
                    penalty += 8.0
                    break
        if len(r) > 100:
            penalty += min(18.0, (len(r) - 100) / 8)
        return penalty

    @staticmethod
    def _reply_style_bonus(reply: str, tone: str) -> float:
        f = response_features(reply)
        bonus = 0.0
        if tone == "playful" and f["laughter"]:
            bonus += 6
        if tone == "practical" and not f["laughter"] and f["chars"] <= 60:
            bonus += 4
        if tone == "terse" and f["chars"] <= 20:
            bonus += 5
        if 1 <= f["chars"] <= 45:
            bonus += 3
        return bonus

    def retrieve_episodes(
        self,
        current_text: str,
        live_turns: list[dict],
        speaker: str,
        act: str,
        n: int = 5,
    ) -> list[EpisodeHit]:
        q_last = topic_tokens(current_text)
        q_exact = {t for t in q_last if t.startswith("@")}
        recent_text = " ".join(
            t.get("text", "") for t in live_turns[-7:] if t.get("role") == "user"
        )
        q_context = topic_tokens(recent_text)
        tone = tone_of(current_text, act)
        qform = dialogue_form(current_text, act)

        # Meta-self questions are structurally closer to real yes/no questions.
        # Do not mix them with arbitrary short reactions merely because both are short.
        compatible_acts = {act}
        if act == "meta_self":
            compatible_acts |= {"yesno_question"}
        if act == "banter":
            compatible_acts |= {"short_reaction", "statement"}
        if act == "opinion":
            compatible_acts |= {"statement", "yesno_question"}

        hits: list[EpisodeHit] = []
        all_eps = self.raw_episodes + self.derived_episodes
        for e in all_eps:
            eid = e.get("id", "")
            etoks = self.episode_tokens.get(eid, set())
            # Named-topic turns should retrieve that actual topic, not a 2-char
            # fragment from another word (e.g. スキー vs スキニー).
            if q_exact and act in {"opinion", "statement"} and not (q_exact & etoks):
                continue
            last_topic = self._idf_score(q_last, topic_tokens(e.get("stimulus", "")))
            context_topic = self._idf_score(q_context, etoks) * 0.12
            if re.search(r"(?:やっぱ|変更|訂正|にしよう)", current_text):
                context_topic = 0.0
            stimulus = e.get("stimulus", "")
            eact = e.get("act") or dialogue_act(stimulus)
            eform = dialogue_form(stimulus, eact)

            act_bonus = 0.0
            if eact == act:
                act_bonus = 10.0
            elif eact in compatible_acts:
                act_bonus = 4.0

            form_bonus = 0.0
            if eform == qform:
                form_bonus = 20.0
            elif qform == "meta_yesno" and eform == "yesno_question":
                form_bonus = 11.0
            elif qform == "schedule_proposal" and eform in {"schedule_availability", "schedule_general"}:
                form_bonus = 3.0

            # With no topical evidence, narrow acts must still match their
            # structural family. Meta-self is not a license to retrieve arbitrary
            # playful statements; it specifically borrows from real yes/no reactions.
            if last_topic <= 0 and context_topic <= 0:
                if act == "meta_self" and eact not in compatible_acts:
                    continue
                if act not in {"meta_self", "thanks", "apology", "short_reaction"} and eact != act:
                    continue

            structural_bonus = 0.0
            if QUESTION_RE.search(current_text) and QUESTION_RE.search(stimulus):
                lc, le = len(norm(current_text)), len(norm(stimulus))
                structural_bonus += max(0.0, 8.0 - abs(lc - le))
                past_re = re.compile(r"(?:た|った|えた|した|なった|できた|終わった|行った|来た|見た|聞いた)[？?]?$" )
                if past_re.search(current_text) and past_re.search(stimulus):
                    structural_bonus += 10.0

            source_bonus = 3.0 if e.get("source") == "line_raw" else 0.0
            speaker_bonus = 0.0
            if speaker and e.get("last_speaker") == speaker:
                speaker_bonus = 4.0

            reply = e.get("reply", "")
            reply_topic = self._idf_score(q_last, topic_tokens(reply))
            schedule_bonus = 0.0
            if qform == "schedule_proposal":
                if re.fullmatch(r"(?:はい|あはい|うん|了解|おっけー?|ok)[。.!！]*", reply.strip(), re.I):
                    schedule_bonus += 40.0
                if response_features(reply)["question"]:
                    schedule_bonus -= 8.0
                if eform not in {"schedule_proposal", "schedule_general"}:
                    schedule_bonus -= 5.0
                current_nums = set(re.findall(r"\d+", current_text or ""))
                for num in set(re.findall(r"\d+", stimulus)):
                    if current_nums and num not in current_nums:
                        schedule_bonus -= 8.0
            score = (
                last_topic * 3.2
                + reply_topic * 1.4
                + context_topic
                + act_bonus
                + form_bonus
                + structural_bonus
                + schedule_bonus
                + source_bonus
                + speaker_bonus
                + self._reply_style_bonus(reply, tone)
                - self._portable_penalty(reply, current_text)
            )
            if score <= 0:
                continue
            hits.append(EpisodeHit(score=score, topic_score=last_topic, episode=e))

        hits.sort(key=lambda h: (h.score, h.topic_score), reverse=True)
        out = []
        seen = set()
        for h in hits:
            key = (h.episode.get("stimulus"), h.episode.get("reply"))
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
            if len(out) >= n:
                break
        return out

    def retrieve_statements(self, query: str, n: int = 5) -> list[tuple[float, str]]:
        q = topic_tokens(query)
        exact_markers = {t for t in q if t.startswith("@")}
        scored = []
        for toks, text in zip(self.statement_tokens, self.self_statements):
            # For explicit named topics such as スキー / ギター / 人類, do not
            # mistake a shared 2-character fragment (スキ in スキニー) for evidence.
            if exact_markers and not (exact_markers & toks):
                continue
            s = self._idf_score(q, toks, statement=True)
            if s > 0:
                scored.append((s, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:n]

    def person_evidence(self, person_id: str, n: int = 8) -> list[str]:
        vals = self.person_mentions.get(person_id, [])
        # Diverse and short-ish direct mentions are more useful for conversational output.
        scored = []
        for text in vals:
            score = 0.0
            if len(text) <= 30:
                score += 16
            elif len(text) <= 80:
                score += 8
            elif len(text) <= 160:
                score += 4
            if re.search(r"(?:ww+|ｗｗ+|笑|😂|😇|😭|ｷｬ|ムタァ|ぼくぅ)", text, re.I):
                score += 5
            if re.search(r"(?:最高|かっこいい|センス|偉い|尊敬|天才|面白|賢い)", text):
                score += 22
            elif re.search(r"(?:凄い|すごい|流石|ありがとう|優し|好き|上手い)", text):
                score += 12
            scored.append((score, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        seen = set()
        for _, text in scored:
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= n:
                break
        return out

    def portable_fallback(self, hits: list[EpisodeHit], current_text: str, tone: str) -> str:
        candidates = []
        for h in hits:
            reply = (h.episode.get("reply") or "").strip()
            if not reply or len(reply) > 45:
                continue
            penalty = self._portable_penalty(reply, current_text)
            if penalty > 0:
                continue
            bonus = self._reply_style_bonus(reply, tone)
            # Prefer low-content reactions for safe transplant.
            content_count = len(topic_tokens(reply))
            score = h.score + bonus - content_count * 1.5
            candidates.append((score, reply))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]

        # Last resort still comes from real Hashimoto utterances, not invented prose.
        for r in self.reactions:
            if not r or len(r) > 18:
                continue
            if self._portable_penalty(r, current_text) == 0:
                if tone == "playful" and re.search(r"(?:ww+|笑|😂|😇|ｷｬ|きゃぴ|ﾝ)", r, re.I):
                    return r
                if tone == "practical" and re.search(r"(?:はい|了解|大丈夫|いけ|行け|おっけ)", r, re.I):
                    return r
        return "ほーん" if "ほーん" in self.reactions else (self.reactions[0] if self.reactions else "ｷｬﾋﾟｯ!?")


class MeaningResolver:
    def __init__(self, archive: PersonaArchive):
        self.archive = archive

    def resolve(self, text: str, state: DialogueState, current_speaker: str, is_group: bool) -> Meaning:
        raw = (text or "").strip()
        act = dialogue_act(raw)
        called = bool(CALL_RE.search(raw))

        if SELF_STATE_RE.search(raw):
            return Meaning(raw, "self_state", predicate="self_state", act="meta_self")

        m = PERSON_OPINION_RE.match(raw)
        if m:
            pid, label = self.archive.resolve_person(m.group(1), current_speaker)
            if pid:
                return Meaning(raw, "person_opinion", pid, label, "opinion", False, True, True, "opinion")
            return Meaning(raw, "subject_opinion", "", label, "opinion", False, True, True, "opinion")

        sm = SHORT_PERSON_RE.match(raw)
        if sm and state.last_intent == "person_opinion" and state.last_predicate == "opinion":
            pid, label = self.archive.resolve_person(sm.group(1), current_speaker)
            if pid:
                return Meaning(raw, "person_opinion", pid, label, "opinion", True, True, True, "opinion")

        if CHOICE_RE.match(raw):
            recent = "\n".join(t.get("text", "") for t in state.turns[-5:])
            has_options = bool(re.search(r"(?:A|B|1|2|どっち|どちら|それとも|or|か、)", recent, re.I))
            return Meaning(raw, "choice_followup" if has_options else "ambiguous_followup", predicate="choice", act="wh_question")

        if is_group and not called:
            prev = state.turns[-1] if state.turns else {}
            same_partner_continuation = prev.get("role") == "assistant" and state.last_partner == current_speaker
            if not same_partner_continuation:
                return Meaning(raw, "group_chatter", predicate="chat", should_reply=False, directed=False, act=act)

        if act == "scheduling":
            return Meaning(raw, "scheduling", predicate="scheduling", act=act)
        if QUESTION_RE.search(raw):
            return Meaning(raw, "question", predicate="question", act=act)
        return Meaning(raw, "chat", predicate="chat", act=act)

    @staticmethod
    def commit(state: DialogueState, meaning: Meaning, partner: str):
        state.last_intent = meaning.intent
        state.last_target_id = meaning.target_id
        state.last_target_label = meaning.target_label
        state.last_predicate = meaning.predicate
        state.last_partner = partner


class ContractBuilder:
    def __init__(self, archive: PersonaArchive):
        self.archive = archive

    def build(self, meaning: Meaning, state: DialogueState, speaker: str) -> ResponseContract:
        hits = self.archive.retrieve_episodes(
            meaning.raw, state.turns, speaker, meaning.act, n=6
        )
        primary = hits[0].episode if hits else None
        backups = [h.episode for h in hits[1:4]]
        content_sources: list[str] = []

        if meaning.intent == "person_opinion" and meaning.target_id:
            content_sources = self.archive.person_evidence(meaning.target_id, n=8)
            if content_sources:
                # For a person-opinion question, a direct Hashimoto mention is a
                # stronger content anchor than an unrelated generic opinion episode.
                direct = content_sources[0]
                primary = {
                    "id": f"person:{meaning.target_id}",
                    "source": "direct_person_mention",
                    "context": [],
                    "last_speaker": meaning.target_id,
                    "stimulus": f"{meaning.target_label or meaning.target_id}について",
                    "act": "opinion",
                    "reply": direct,
                    "features": response_features(direct),
                }
        elif meaning.intent in {"subject_opinion", "self_state"}:
            statement_query = meaning.target_label or meaning.raw
            statement_hits = self.archive.retrieve_statements(statement_query, n=5)
            content_sources = [x[1] for x in statement_hits]
            if meaning.intent == "subject_opinion" and statement_hits:
                direct = statement_hits[0][1]
                primary = {
                    "id": "dataset:subject-opinion",
                    "source": "ai_dataset_statement",
                    "context": [],
                    "last_speaker": "橋本新",
                    "stimulus": statement_query,
                    "act": "opinion",
                    "reply": direct,
                    "features": response_features(direct),
                }

        tone = tone_of(meaning.raw, meaning.act)
        replies = []
        if primary and primary.get("reply"):
            replies.append(primary.get("reply", ""))
        replies.extend(h.episode.get("reply", "") for h in hits if h.episode.get("reply"))
        target_chars = int(median([min(len(x), 120) for x in replies])) if replies else 18
        target_chars = max(4, min(target_chars, 90))
        fallback = self.archive.portable_fallback(hits, meaning.raw, tone)
        if meaning.intent == "person_opinion" and content_sources:
            direct_piece = content_sources[0].split(" / ", 1)[0].strip()
            if direct_piece and len(direct_piece) <= 60:
                fallback = direct_piece
        if meaning.intent == "self_state" and fallback:
            for h in hits:
                if (h.episode.get("reply") or "").strip() == fallback.strip():
                    primary = h.episode
                    break

        top_topic = hits[0].topic_score if hits else 0.0
        if top_topic >= 18:
            confidence = "high"
        elif top_topic > 0 or (hits and meaning.act in {"meta_self", "thanks", "apology", "short_reaction"}):
            confidence = "medium"
        else:
            confidence = "low"

        can_replay = False
        if primary:
            reply = primary.get("reply", "")
            portable = self.archive._portable_penalty(reply, meaning.raw) == 0 and len(reply) <= 30
            if meaning.intent == "person_opinion" and primary.get("source") == "direct_person_mention":
                evaluative = bool(re.search(r"(?:最高|かっこいい|凄い|すごい|流石|センス|偉い|尊敬|天才|優し|好き|面白|賢い|上手い)", reply))
                # The direct source may use the person's historic nickname (e.g. ムタァ)
                # or canonical name even when the current user says 俺. That is desired.
                no_new_numbers = not re.findall(r"\d+", reply)
                can_replay = len(reply) <= 30 and evaluative and no_new_numbers
            else:
                can_replay = portable and meaning.intent not in {"subject_opinion", "question", "scheduling"} and meaning.act in {
                    "meta_self", "banter", "short_reaction", "thanks", "apology"
                }

        debug = {
            "archive": self.archive.source_meta,
            "top_hits": [
                {
                    "id": h.episode.get("id"),
                    "source": h.episode.get("source"),
                    "score": round(h.score, 2),
                    "topic_score": round(h.topic_score, 2),
                    "stimulus": h.episode.get("stimulus", "")[:100],
                    "reply": h.episode.get("reply", "")[:140],
                }
                for h in hits[:4]
            ],
            "content_sources": [x[:160] for x in content_sources[:4]],
        }
        return ResponseContract(
            meaning=meaning,
            primary=primary,
            backups=backups,
            content_sources=content_sources,
            fallback=fallback,
            target_chars=target_chars,
            tone=tone,
            source_confidence=confidence,
            can_replay=can_replay,
            debug=debug,
        )


class PersonaGate:
    """Reject free-form AI drift after generation.

    The answer must stay close to at least one real Hashimoto source: a retrieved
    reply anchor or a direct/self-expression content source. This makes the model
    a constrained editor rather than the author of the persona.
    """

    GENERIC_AI_RE = re.compile(
        r"(?:もう少し情報|詳しく教えて|何か楽しいこと|お手伝い|それについて|ということですね|"
        r"どういう意味|一般的には|場合によります|私には分かりません|俺には分からない)"
    )

    @classmethod
    def validate(cls, answer: str, contract: ResponseContract, user_text: str) -> tuple[bool, str]:
        a = (answer or "").strip()
        if not a:
            return False, "empty"
        if len(a) > max(80, contract.target_chars * 3):
            return False, "too_long"
        if cls.GENERIC_AI_RE.search(a):
            return False, "generic_ai_phrase"

        nu, na = norm(user_text), norm(a)
        if len(nu) >= 4 and na.startswith(nu[:min(8, len(nu))]) and re.search(r"[？?]", a):
            return False, "question_echo"
        if re.search(r"[？?]", a) and similarity(user_text, a) >= 0.42:
            return False, "question_echo"

        sources = []
        if contract.primary:
            sources.append(contract.primary.get("reply", ""))
        sources.extend(x.get("reply", "") for x in contract.backups)
        sources.extend(contract.content_sources)
        sources = [s for s in sources if s]
        if sources:
            best = max(similarity(a, s) for s in sources)
            # Short reactions can be genuinely novel recombinations; long prose must
            # remain visibly anchored to actual language.
            threshold = 0.14 if len(a) <= 18 else 0.20 if len(a) <= 45 else 0.27
            if best < threshold:
                return False, f"too_far_from_archive:{best:.2f}"

        allowed_numbers = set(re.findall(r"\d+", user_text or ""))
        for src in sources:
            allowed_numbers.update(re.findall(r"\d+", src))
        for num in re.findall(r"\d+", a):
            if num not in allowed_numbers:
                return False, "invented_number"

        return True, "pass"
