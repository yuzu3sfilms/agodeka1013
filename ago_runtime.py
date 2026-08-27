from __future__ import annotations

import glob
import os
import random
import re
from collections import defaultdict
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


@dataclass
class DialogueState:
    last_intent: str = ""
    last_target_id: str = ""
    last_target_label: str = ""
    last_predicate: str = ""
    last_partner: str = ""
    turns: list[dict] = field(default_factory=list)


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


class MeaningResolver:
    """Resolve semantics exactly once before retrieval/generation."""

    def __init__(self, corpus: CorpusIndex):
        self.corpus = corpus

    def resolve(self, text: str, state: DialogueState, current_speaker: str, is_group: bool) -> TurnMeaning:
        raw = (text or "").strip()
        called = bool(CALL_RE.search(raw))
        directed = called or bool(QUESTION_RE.search(raw))

        if SELF_STATE_RE.search(raw):
            return TurnMeaning(raw, "self_state", predicate="self_state", directed=True)

        m = PERSON_OPINION_RE.match(raw)
        if m:
            person_id, label = self.corpus.resolve_person(m.group(1), current_speaker)
            if person_id:
                return TurnMeaning(raw, "person_opinion", person_id, label, "opinion", False, True)
            return TurnMeaning(raw, "subject_opinion", "", label, "opinion", False, True)

        # Narrow ellipsis: only a recognizable person can inherit a person-opinion predicate.
        sm = SHORT_PERSON_RE.match(raw)
        if sm and state.last_intent == "person_opinion" and state.last_predicate == "opinion":
            person_id, label = self.corpus.resolve_person(sm.group(1), current_speaker)
            if person_id:
                return TurnMeaning(raw, "person_opinion", person_id, label, "opinion", True, True)

        # Choice words are never allowed to inherit a person predicate.
        if CHOICE_RE.match(raw):
            recent_text = "\n".join(t.get("text", "") for t in state.turns[-4:])
            has_options = bool(re.search(r"(?:A|B|1|2|どっち|どちら|か、|それとも|or)", recent_text, re.I))
            return TurnMeaning(raw, "choice_followup" if has_options else "ambiguous_followup", predicate="choice", directed=True, ambiguity="" if has_options else "no_visible_options")

        if QUESTION_RE.search(raw):
            return TurnMeaning(raw, "question", predicate="question", directed=True)

        if called:
            return TurnMeaning(raw, "called_chat", predicate="chat", directed=True)

        # Group first-message fragments like 「えー」 are not assumed to address AGO.
        if is_group:
            return TurnMeaning(raw, "group_chatter", predicate="chat", directed=False, should_reply=False)
        return TurnMeaning(raw, "chat", predicate="chat", directed=True)

    @staticmethod
    def commit(state: DialogueState, meaning: TurnMeaning, partner: str):
        state.last_intent = meaning.intent
        state.last_target_id = meaning.target_id
        state.last_target_label = meaning.target_label
        state.last_predicate = meaning.predicate
        state.last_partner = partner
