from __future__ import annotations

import glob
import os
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

HASHIMOTO_NAMES = {
    "橋本新", "Arata Hashimoto", "LIAR  OF  ARAKUN", "LIAR OF ARAKUN",
    "あらくん", "顎", "AGODEKA", "サブ垢です", "Unknown",
}

STATIC_ALIASES = {
    "Reiji Shioda": {"Reiji Shioda", "塩田", "塩田さん", "れーじ", "レージ", "れいじ"},
    "Ryo Sekiguchi": {"Ryo Sekiguchi", "関口", "関口さん", "関口諒", "せきぐち", "せっきー", "セッキー", "せっき", "セッキ"},
    "中山 貴文": {"中山 貴文", "中山", "中山さん", "貴文", "ぽつぉ", "ぽつお", "ポツォ", "ポッツォ", "ぽつ", "ぽっつぉ"},
    "村田": {"村田", "村田さん", "ムタ", "むた"},
    "坂口": {"坂口", "坂口さん", "さかぐち"},
}

MEDIA_RE = re.compile(r"^\[(?:写真|スタンプ|動画|ファイル|アルバム)\]$|https?://", re.I)
PERSON_OPINION_RE = re.compile(r"^(?:じゃあ|で、?|なら)?\s*(.+?)(?:のこと|について)?(?:は|って)?\s*(?:どう思(?:ってる|う)|どう感じる|好き(?:なの)?|嫌い(?:なの)?)\s*[？?。!！]*$")
SHORT_PERSON_RE = re.compile(r"^(?:じゃあ|で、?|なら)?\s*(.+?)(?:のこと)?(?:は|って)?\s*[？?]*$")
SELF_STATE_RE = re.compile(r"(?:自我|意識|感情).*(?:芽生|ある|持って|感じ)|(?:芽生|ある).*(?:自我|意識|感情)")
CHOICE_RE = re.compile(r"^(?:どれ|どっち|どちら|どの(?:人|方|やつ)?)\s*[？?]*$")
CALL_RE = re.compile(r"(?:あらくん|橋本|橋本新|顎|アゴ|AGODEKA)", re.I)
QUESTION_RE = re.compile(r"[？?]$|(?:何|誰|どこ|いつ|どう|なんで|なぜ|どれ|どっち)")


def norm(text: str) -> str:
    return re.sub(r"[\s　、。！？!?『』「」・…]+", "", (text or "").lower())


def is_hashimoto(name: str) -> bool:
    n = re.sub(r"\s+", " ", (name or "").strip())
    return n in HASHIMOTO_NAMES or "橋本" in n or "ARAKUN" in n.upper()


@dataclass
class TurnMeaning:
    raw: str
    intent: str
    target_id: str = ""
    target_label: str = ""
    predicate: str = ""
    inherited_predicate: bool = False
    directed: bool = False
    should_reply: bool = True
    ambiguity: str = ""
    stimulus_class: str = ""


@dataclass
class DialogueState:
    last_intent: str = ""
    last_target_id: str = ""
    last_target_label: str = ""
    last_predicate: str = ""
    last_partner: str = ""
    interaction_mode: str = "ordinary"
    mode_strength: int = 0
    mode_age: int = 0
    turns: list[dict] = field(default_factory=list)


@dataclass
class PersonModel:
    person_id: str
    aliases: list[str] = field(default_factory=list)
    interaction_count: int = 0
    mention_count: int = 0
    recurring_terms: list[str] = field(default_factory=list)
    interaction_style_examples: list[dict] = field(default_factory=list)
    direct_mention_examples: list[str] = field(default_factory=list)
    evidence_strength: str = "none"


@dataclass
class ResponsePatternModel:
    stimulus_class: str
    count: int = 0
    response_modes: dict[str, int] = field(default_factory=dict)
    median_response_length: int = 0
    examples: list[dict] = field(default_factory=list)


@dataclass
class PersonaModel:
    line_count: int = 0
    median_length: int = 0
    p75_length: int = 0
    question_rate: float = 0.0
    laughter_rate: float = 0.0
    polite_rate: float = 0.0
    terse_rate: float = 0.0
    mode_examples: dict[str, list[str]] = field(default_factory=dict)


class CorpusIndex:
    """Raw-log-backed identity, relationship and style store.

    This is intentionally one store. Person identity and evidence are never
    independently guessed by retrieval and generation layers.
    """

    def __init__(self, roots=None):
        self.roots = roots or ["data", "."]
        self.messages: list[dict] = []
        self.participants: set[str] = set()
        self.alias_to_name: dict[str, str] = {}
        self.name_to_aliases = defaultdict(set)
        self.hashimoto_lines: list[str] = []
        self.exchanges = defaultdict(list)
        self.direct_mentions = defaultdict(list)
        self.person_models: dict[str, PersonModel] = {}
        self.persona_model = PersonaModel()
        self.response_patterns: dict[str, ResponsePatternModel] = {}
        self.response_pairs: list[dict] = []
        self._load()

    def _candidate_files(self):
        seen = set()
        out = []
        for root in self.roots:
            for pat in ("*[LINE]*.txt", "*LINE*.txt", "*トーク*.txt"):
                for p in glob.glob(os.path.join(root, pat)):
                    ap = os.path.abspath(p)
                    if ap not in seen:
                        seen.add(ap)
                        out.append(p)
        return out

    def _parse(self, path):
        cur = None
        try:
            fh = open(path, encoding="utf-8-sig", errors="ignore")
        except OSError:
            return
        with fh:
            for raw in fh:
                line = raw.rstrip("\r\n")
                m = re.match(r"^(\d{1,2}:\d{2})\t([^\t]+)\t(.*)$", line)
                if m:
                    cur = {"sender": m.group(2).strip(), "text": m.group(3).strip(), "source": os.path.basename(path)}
                    self.messages.append(cur)
                    self.participants.add(cur["sender"])
                elif cur and line and not re.match(r"^\d{4}/\d", line):
                    cur["text"] = (cur["text"] + " / " + line.strip()).strip(" / ")

    def _build_aliases(self):
        for name in self.participants:
            if is_hashimoto(name):
                continue
            self.name_to_aliases[name].add(name)
            compact = re.sub(r"\s+", "", name)
            if len(compact) >= 2:
                self.name_to_aliases[name].add(compact)
            for part in re.split(r"[\s　]+", name):
                if len(part) >= 2:
                    self.name_to_aliases[name].add(part)
        for preferred, vals in STATIC_ALIASES.items():
            canonical = preferred
            matches = [p for p in self.name_to_aliases if p in vals or any(v and v in p for v in vals if len(v) >= 2)]
            if preferred not in self.name_to_aliases and matches:
                canonical = matches[0]
            self.name_to_aliases[canonical].update(vals)
        for canonical, aliases in self.name_to_aliases.items():
            for a in aliases:
                self.alias_to_name[a] = canonical
                self.alias_to_name[re.sub(r"(?:さん|くん|君|ちゃん)$", "", a)] = canonical

    def _build_evidence(self):
        for i, m in enumerate(self.messages):
            if is_hashimoto(m["sender"]):
                t = m["text"].strip()
                if t and not MEDIA_RE.search(t):
                    self.hashimoto_lines.append(t)
            if i == 0:
                continue
            a, b = self.messages[i-1], m
            ah, bh = is_hashimoto(a["sender"]), is_hashimoto(b["sender"])
            if ah == bh:
                continue
            partner = b["sender"] if ah else a["sender"]
            if is_hashimoto(partner):
                continue
            h = a if ah else b
            p = b if ah else a
            self.exchanges[partner].append((p["text"], h["text"]))

        for canonical, aliases in self.name_to_aliases.items():
            usable = sorted({a for a in aliases if len(a) >= 2}, key=len, reverse=True)
            if not usable:
                continue
            for m in self.messages:
                if not is_hashimoto(m["sender"]):
                    continue
                t = m["text"]
                if t and not MEDIA_RE.search(t) and any(a in t for a in usable):
                    self.direct_mentions[canonical].append(t)

    def _load(self):
        for p in self._candidate_files():
            self._parse(p)
        self._build_aliases()
        self._build_evidence()
        self._build_persona_model()
        self._build_response_patterns()
        self._build_person_models()

    def resolve_person(self, token: str, current_speaker: str = "") -> tuple[str, str]:
        raw = re.sub(r"^(?:じゃあ|で、?|なら|まあ|まぁ)\s*", "", token or "").strip(" \t、。！？?")
        raw = re.sub(r"(?:のこと|について)$", "", raw).strip()
        raw_bare = re.sub(r"(?:さん|くん|君|ちゃん)$", "", raw).strip()
        if raw_bare in {"俺", "おれ", "僕", "ぼく", "私", "わたし", "自分"}:
            return (current_speaker or "USER_SELF", "俺")
        if raw in self.alias_to_name:
            return self.alias_to_name[raw], raw
        if raw_bare in self.alias_to_name:
            return self.alias_to_name[raw_bare], raw
        # Explicit full participant name only; never fuzzy-invent unknown nicknames.
        if raw in self.participants:
            return raw, raw
        return "", raw

    @staticmethod
    def _score_line(query: str, line: str) -> int:
        nq, nl = norm(query), norm(line)
        if not nq or not nl:
            return 0
        score = 0
        for n in range(2, min(8, len(nq))+1):
            grams = {nq[i:i+n] for i in range(len(nq)-n+1)}
            hits = sum(1 for g in grams if g in nl)
            score += hits * n
        if QUESTION_RE.search(query) == bool(QUESTION_RE.search(line)):
            score += 8
        if 2 <= len(line) <= 60:
            score += 5
        return score

    def style_examples(self, query: str, n=8):
        scored = [(self._score_line(query, x), x) for x in self.hashimoto_lines]
        scored.sort(key=lambda z: z[0], reverse=True)
        seen, out = set(), []
        for s, x in scored:
            if s <= 0 or x in seen:
                continue
            seen.add(x); out.append(x)
            if len(out) >= n:
                break
        if len(out) < n and self.hashimoto_lines:
            pool = self.hashimoto_lines[:]
            random.Random(14).shuffle(pool)
            for x in pool:
                if x not in seen and 2 <= len(x) <= 70:
                    out.append(x); seen.add(x)
                    if len(out) >= n:
                        break
        return out

    def relationship_examples(self, target_id: str, n=8):
        if not target_id:
            return []
        pairs = self.exchanges.get(target_id, [])
        out, seen = [], set()
        for p, h in reversed(pairs):
            key = (p, h)
            if key in seen or MEDIA_RE.search(p or "") or MEDIA_RE.search(h or ""):
                continue
            seen.add(key)
            if 1 <= len(h) <= 100 and 1 <= len(p) <= 120:
                out.append({"other": p, "hashimoto": h})
            if len(out) >= n:
                break
        return out

    def mentions(self, target_id: str, n=8):
        vals = self.direct_mentions.get(target_id, [])
        out, seen = [], set()
        for x in reversed(vals):
            if x not in seen and 2 <= len(x) <= 120:
                seen.add(x); out.append(x)
            if len(out) >= n:
                break
        return out

    @staticmethod
    def _content_terms(texts, limit=10):
        # Lightweight Japanese/ASCII topic hints. These are retrieval hints, not personality labels.
        stop = {"これ","それ","あれ","ここ","そこ","どう","なんか","ちょっと","さん","くん","です","ます","ない","ある","いる","する","した","して","って","から","けど","ので","よう","こと","もの","俺","おれ","僕","私","橋本"}
        c = Counter()
        for text in texts:
            for tok in re.findall(r"[A-Za-z0-9_]{3,}|[一-龥ァ-ヶー]{2,}|[ぁ-ん]{3,}", text or ""):
                if tok.lower() in stop or tok in stop or len(tok) > 18:
                    continue
                c[tok] += 1
        return [w for w,n in c.most_common(limit) if n >= 2]

    @staticmethod
    def _percentile(values, q):
        if not values: return 0
        xs=sorted(values); return xs[int(round((len(xs)-1)*q))]

    @staticmethod
    def _behavior_mode(line):
        t=(line or "").strip()
        if re.search(r"(?:何時|何分|時に|着き|行け|行きます|遅れ|すみません|大丈夫|予定|今日|明日|来週)", t): return "practical"
        if re.search(r"(?:ww+|ｗｗ+|笑|ｷｬ|ほーん|草)", t, re.I): return "playful"
        if QUESTION_RE.search(t): return "questioning"
        if len(t)<=12: return "terse"
        return "ordinary"

    def _build_persona_model(self):
        lines=[x.strip() for x in self.hashimoto_lines if x and not MEDIA_RE.search(x)]
        lengths=[len(x) for x in lines]; buckets=defaultdict(list)
        for x in lines: buckets[self._behavior_mode(x)].append(x)
        def rate(pred): return round(sum(1 for x in lines if pred(x))/max(1,len(lines)),3)
        examples={}
        for mode,vals in buckets.items():
            seen=set(); out=[]
            for x in vals:
                if x not in seen and 2<=len(x)<=90: seen.add(x); out.append(x)
                if len(out)>=120: break
            examples[mode]=out
        self.persona_model=PersonaModel(len(lines),self._percentile(lengths,.5),self._percentile(lengths,.75),
            rate(lambda x:bool(QUESTION_RE.search(x))),rate(lambda x:bool(re.search(r"(?:ww+|ｗｗ+|笑)",x,re.I))),
            rate(lambda x:bool(re.search(r"(?:です|ます|でした|ません|すみません|ありがとう)",x))),
            rate(lambda x:len(x)<=12),examples)

    def persona_for_prompt(self, query, intent, n=10, interaction_mode='ordinary'):
        pm=self.persona_model
        preferred=(["questioning","terse","ordinary"] if intent in {"question","choice_followup","ambiguous_followup"} else
                   ["ordinary","terse","playful"] if intent in {"person_opinion","subject_opinion","self_state"} else
                   ["terse","ordinary","playful"])
        if interaction_mode in self.persona_model.mode_examples:
            preferred = [interaction_mode] + [x for x in preferred if x != interaction_mode]
        cand=[]
        for rank,mode in enumerate(preferred):
            for line in pm.mode_examples.get(mode,[]): cand.append((self._score_line(query,line)+(len(preferred)-rank)*4,line,mode))
        cand.sort(key=lambda z:z[0],reverse=True); out=[]; seen=set()
        for _,line,mode in cand:
            if line in seen: continue
            seen.add(line); out.append({"mode":mode,"text":line})
            if len(out)>=n: break
        return {"line_count":pm.line_count,"median_length":pm.median_length,"p75_length":pm.p75_length,
                "question_rate":pm.question_rate,"laughter_rate":pm.laughter_rate,"polite_rate":pm.polite_rate,
                "terse_rate":pm.terse_rate,"examples":out}

    @staticmethod
    def classify_stimulus(text: str) -> str:
        """Classify the incoming conversational stimulus, not its topic.

        This label is behavioral metadata only. It never changes target/person/intent.
        """
        t=(text or "").strip()
        if not t:
            return "empty"
        if re.search(r"(?:ありがとう|ありがと|助かった|サンキュ|感謝)", t, re.I):
            return "thanks"
        if re.search(r"(?:ごめん|すみません|すまん|申し訳|遅れ|遅刻)", t):
            return "apology"
        if re.search(r"(?:あげる|くれる|もらう|プレゼント|奢る|おごる)", t):
            return "offer_gift"
        if re.search(r"(?:ww+|ｗｗ+|笑|草|ウケ|おもろ|面白)", t, re.I):
            return "joke_laughter"
        if re.search(r"(?:何時|何分|いつ|今日|明日|来週|土曜|日曜|集合|予定|行ける|空いて|予約)", t):
            return "scheduling"
        if re.search(r"(?:やば|まじ|マジ|えっ|ええ|うそ|嘘|！？|!\?)", t, re.I):
            return "surprise"
        if re.search(r"(?:嫌|だる|つら|辛|無理|最悪|困|疲れ|めんど)", t):
            return "complaint"
        if re.search(r"(?:どう思|好き|嫌い|どっち|どれ|おすすめ|良い|いいと思)", t):
            return "opinion_request"
        if QUESTION_RE.search(t):
            return "question"
        if re.search(r"^(?:おは|こんにちは|こんばんは|おつ|乙|よろしく|久しぶり)", t):
            return "greeting"
        if len(t) <= 8:
            return "short_reaction"
        return "statement"

    def _build_response_patterns(self):
        """Learn stimulus -> Hashimoto response pairs from actual adjacency.

        Only non-Hashimoto -> immediately-following Hashimoto messages are used.
        This avoids reversing Hashimoto prompts into fake response evidence.
        """
        grouped=defaultdict(list)
        for i in range(1, len(self.messages)):
            prev, cur = self.messages[i-1], self.messages[i]
            if prev.get("source") != cur.get("source"):
                continue
            if is_hashimoto(prev.get("sender", "")) or not is_hashimoto(cur.get("sender", "")):
                continue
            stimulus=(prev.get("text") or "").strip()
            response=(cur.get("text") or "").strip()
            if not stimulus or not response or MEDIA_RE.search(stimulus) or MEDIA_RE.search(response):
                continue
            if len(stimulus) > 240 or len(response) > 180:
                continue
            cls=self.classify_stimulus(stimulus)
            pair={"stimulus":stimulus,"response":response,"partner":prev.get("sender", ""),
                  "stimulus_class":cls,"response_mode":self._behavior_mode(response)}
            self.response_pairs.append(pair)
            grouped[cls].append(pair)

        for cls,pairs in grouped.items():
            lengths=[len(x["response"]) for x in pairs]
            modes=Counter(x["response_mode"] for x in pairs)
            self.response_patterns[cls]=ResponsePatternModel(
                stimulus_class=cls,
                count=len(pairs),
                response_modes=dict(modes),
                median_response_length=self._percentile(lengths,.5),
                examples=pairs[:80],
            )

    def response_pattern_for_prompt(self, query: str, stimulus_class: str, partner: str="", n=8):
        model=self.response_patterns.get(stimulus_class)
        if not model:
            return {"stimulus_class":stimulus_class,"count":0,"response_modes":{},
                    "median_response_length":0,"examples":[]}
        scored=[]
        canonical_partner=""
        if partner:
            canonical_partner=self.alias_to_name.get(partner, partner)
        for x in self.response_pairs:
            if x["stimulus_class"] != stimulus_class:
                continue
            score=self._score_line(query, x["stimulus"])
            xp=self.alias_to_name.get(x["partner"], x["partner"])
            if canonical_partner and xp == canonical_partner:
                score += 18
            scored.append((score,x))
        scored.sort(key=lambda z:z[0], reverse=True)
        out=[]; seen=set()
        for _,x in scored:
            key=(x["stimulus"],x["response"])
            if key in seen: continue
            seen.add(key); out.append(x)
            if len(out)>=n: break
        return {"stimulus_class":stimulus_class,"count":model.count,
                "response_modes":model.response_modes,
                "median_response_length":model.median_response_length,"examples":out}

    def _build_person_models(self):
        people = set(self.name_to_aliases) | set(self.exchanges) | set(self.direct_mentions)
        for pid in people:
            pairs = self.relationship_examples(pid, 40)
            mentions = self.mentions(pid, 40)
            n = len(self.exchanges.get(pid, []))
            m = len(self.direct_mentions.get(pid, []))
            volume = n + m
            strength = "strong" if volume >= 30 else "medium" if volume >= 10 else "weak" if volume else "none"
            topic_texts = []
            for x in pairs:
                topic_texts.extend([x.get("other", ""), x.get("hashimoto", "")])
            topic_texts.extend(mentions)
            self.person_models[pid] = PersonModel(
                person_id=pid,
                aliases=sorted(self.name_to_aliases.get(pid, {pid}), key=lambda x:(len(x),x))[:20],
                interaction_count=n,
                mention_count=m,
                recurring_terms=self._content_terms(topic_texts),
                interaction_style_examples=pairs[:12],
                direct_mention_examples=mentions[:12],
                evidence_strength=strength,
            )

    def person_model(self, target_id: str):
        return self.person_models.get(target_id)

    def person_model_for_prompt(self, target_id: str, query: str, n=8):
        pm = self.person_model(target_id)
        if not pm:
            return None
        # Rank the person's own evidence against the current utterance instead of
        # taking whichever rows happen to be newest.
        pair_scored = []
        for x in self.relationship_examples(target_id, 60):
            joined = (x.get("other", "") + " " + x.get("hashimoto", "")).strip()
            pair_scored.append((self._score_line(query, joined), x))
        pair_scored.sort(key=lambda z:z[0], reverse=True)
        mention_scored = [(self._score_line(query, x), x) for x in self.mentions(target_id, 60)]
        mention_scored.sort(key=lambda z:z[0], reverse=True)
        return {
            "person_id": pm.person_id,
            "aliases": pm.aliases,
            "interaction_count": pm.interaction_count,
            "mention_count": pm.mention_count,
            "recurring_terms": pm.recurring_terms,
            "evidence_strength": pm.evidence_strength,
            "relationship_examples": [x for _,x in pair_scored[:n]],
            "direct_mentions": [x for _,x in mention_scored[:n]],
        }


class ConversationDynamics:
    """State transition for *how* Hashimoto is currently interacting.

    This never decides semantic intent or factual content. It only carries
    conversational behavior across turns so persona does not reset every message.
    """

    MODES = {"ordinary", "terse", "playful", "practical", "questioning"}

    @staticmethod
    def signal(text: str) -> tuple[str, int]:
        t=(text or "").strip()
        if not t:
            return "ordinary", 0
        if re.search(r"(?:ww+|ｗｗ+|笑|草|ｷｬ|！？|!\?|ほーん)", t, re.I):
            return "playful", 3
        if re.search(r"(?:何時|何分|時に|着く|着き|行ける|行きます|遅れ|予定|今日|明日|来週|集合|予約)", t):
            return "practical", 3
        if QUESTION_RE.search(t):
            return "questioning", 2
        if len(t) <= 10:
            return "terse", 1
        return "ordinary", 1

    def observe(self, state: DialogueState, text: str, speaker_changed: bool=False):
        proposed, force = self.signal(text)
        if speaker_changed and state.mode_age >= 2:
            state.mode_strength = max(0, state.mode_strength - 1)

        # Strong cues switch immediately. Weak cues need repetition or an expired state.
        if proposed == state.interaction_mode:
            state.mode_strength = min(5, state.mode_strength + max(1, force))
            state.mode_age = 0
        elif force >= 3 or state.mode_strength <= 1 or state.mode_age >= 3:
            state.interaction_mode = proposed
            state.mode_strength = min(5, force)
            state.mode_age = 0
        else:
            state.mode_strength -= 1
            state.mode_age += 1
        return state.interaction_mode

    def after_reply(self, state: DialogueState, answer: str):
        # AGO's own output can reinforce a mode, but cannot abruptly invent a new one.
        proposed, force = self.signal(answer)
        if proposed == state.interaction_mode:
            state.mode_strength = min(5, state.mode_strength + 1)
            state.mode_age = 0
        else:
            state.mode_age += 1



class MeaningResolver:
    """Resolve semantics exactly once before retrieval/generation."""

    def __init__(self, corpus: CorpusIndex):
        self.corpus = corpus

    def resolve(self, text: str, state: DialogueState, current_speaker: str, is_group: bool) -> TurnMeaning:
        raw = (text or "").strip()
        called = bool(CALL_RE.search(raw))
        directed = called or bool(QUESTION_RE.search(raw))
        stimulus_class = self.corpus.classify_stimulus(raw)

        def tm(*args, **kwargs):
            kwargs["stimulus_class"] = stimulus_class
            return TurnMeaning(*args, **kwargs)

        if SELF_STATE_RE.search(raw):
            return tm(raw, "self_state", predicate="self_state", directed=True)

        m = PERSON_OPINION_RE.match(raw)
        if m:
            person_id, label = self.corpus.resolve_person(m.group(1), current_speaker)
            if person_id:
                return tm(raw, "person_opinion", person_id, label, "opinion", False, True)
            return tm(raw, "subject_opinion", "", label, "opinion", False, True)

        # Narrow ellipsis: only a recognizable person can inherit a person-opinion predicate.
        sm = SHORT_PERSON_RE.match(raw)
        if sm and state.last_intent == "person_opinion" and state.last_predicate == "opinion":
            person_id, label = self.corpus.resolve_person(sm.group(1), current_speaker)
            if person_id:
                return tm(raw, "person_opinion", person_id, label, "opinion", True, True)

        # Choice words are never allowed to inherit a person predicate.
        if CHOICE_RE.match(raw):
            recent_text = "\n".join(t.get("text", "") for t in state.turns[-4:])
            has_options = bool(re.search(r"(?:A|B|1|2|どっち|どちら|か、|それとも|or)", recent_text, re.I))
            return tm(raw, "choice_followup" if has_options else "ambiguous_followup", predicate="choice", directed=True, ambiguity="" if has_options else "no_visible_options")

        if QUESTION_RE.search(raw):
            return tm(raw, "question", predicate="question", directed=True)

        if called:
            return tm(raw, "called_chat", predicate="chat", directed=True)

        # Group first-message fragments like 「えー」 are not assumed to address AGO.
        if is_group:
            return tm(raw, "group_chatter", predicate="chat", directed=False, should_reply=False)
        return tm(raw, "chat", predicate="chat", directed=True)

    @staticmethod
    def commit(state: DialogueState, meaning: TurnMeaning, partner: str):
        state.last_intent = meaning.intent
        state.last_target_id = meaning.target_id
        state.last_target_label = meaning.target_label
        state.last_predicate = meaning.predicate
        state.last_partner = partner
