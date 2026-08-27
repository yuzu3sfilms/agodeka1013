from __future__ import annotations

import glob
import os
import re
from collections import Counter, defaultdict


HASHIMOTO_NAMES = {
    "橋本新", "Arata Hashimoto", "LIAR  OF  ARAKUN", "LIAR OF ARAKUN",
    "あらくん", "顎", "AGODEKA", "サブ垢です", "Unknown",
}

# Identity aliases only. Values/feelings are NEVER encoded here.
STATIC_ALIASES = {
    "Reiji Shioda": {"Reiji Shioda", "塩田", "塩田さん", "れーじ", "レージ", "れいじ"},
    "Ryo Sekiguchi": {"Ryo Sekiguchi", "関口", "関口さん", "関口諒", "せきぐち", "せっきー", "セッキー", "せっき", "セッキ"},
    "中山 貴文": {"中山 貴文", "中山", "中山さん", "貴文", "ぽつぉ", "ぽつお", "ポツォ", "ポッツォ", "ぽつ", "ぽっつぉ"},
    "村田": {"村田", "村田さん", "ムタ", "むた"},
    "坂口": {"坂口", "坂口さん", "さかぐち"},
}

DISCOURSE_PREFIX_RE = re.compile(r"^(?:じゃあ|じゃ|なら|では|で、|えっと|まあ|まぁ)\s*")
PERSON_QUESTION_TAIL_RE = re.compile(
    r"(?:のこと|について|って)?\s*(?:は)?\s*(?:どう思(?:ってる|う)|どう感じる|好き(?:なの)?|嫌い(?:なの)?)?.*$"
)
MEDIA_RE = re.compile(r"^\[(?:写真|スタンプ|動画|ファイル|アルバム)\]$|https?://", re.I)
EVALUATION_RE = re.compile(
    r"好き|嫌い|嫌いじゃない|かっこいい|かわいい|面白|おもろ|楽しい|怖|こわ|"
    r"すご|微妙|大丈夫|やば|ヤバ|クソ|きも|キモ|うざ|優し|変|天才|雑魚|強い|弱い"
)

SIGNAL_PATTERNS = {
    "short_reaction": re.compile(r"^.{1,12}$"),
    "questioning": re.compile(r"[？?]|(?:何|どこ|いつ|誰|どう|なんで|なぜ)"),
    "laughter": re.compile(r"草|笑|ｗ|w{2,}|ワロ|くさ", re.I),
    "planning": re.compile(r"(?:今日|明日|今度|何時|集合|行く|行こ|やる|しよう|大丈夫|会う|食べ|飲み)"),
    "agreement": re.compile(r"^(?:そう|それな|たしかに|確かに|いいよ|大丈夫|はい|うん|おけ|OK)", re.I),
    "strong_banter": re.compile(r"(?:クソ|雑魚|ハゲ|デブ|ホモ|うんこ|キモ|きも|バカ|アホ|煽)"),
}
SIGNAL_LABELS = {
    "short_reaction": "短い即応が多い",
    "questioning": "質問・返しが多い",
    "laughter": "笑い反応が出る",
    "planning": "予定・行動の相談がある",
    "agreement": "同意・了承の応答がある",
    "strong_banter": "強めの冗談・いじり語が出る",
}


class RelationshipEvidenceIndex:
    """Single source of truth for people, aliases and relationship evidence.

    The same canonical person id produced here is intended to survive through
    search -> behavior inference -> generation -> judge.  No downstream layer
    should re-guess a nickname independently.
    """

    def __init__(self, roots=None):
        self.roots = roots or ["data", "."]
        self.messages = []
        self.participants = set()
        self.alias_to_name = {}
        self.name_to_aliases = defaultdict(set)
        self._exchange_cache = defaultdict(list)
        self._interaction_counts = Counter()
        self._direct_mentions = defaultdict(list)
        self._load()

    def _candidate_files(self):
        seen, out = set(), []
        patterns = ["*[LINE]*.txt", "*LINE*.txt", "*.txt"]
        for root in self.roots:
            for pat in patterns:
                for path in glob.glob(os.path.join(root, pat)):
                    ap = os.path.abspath(path)
                    if ap in seen:
                        continue
                    seen.add(ap)
                    name = os.path.basename(path)
                    if "トーク" in name or "LINE" in name:
                        out.append(path)
        return out

    @staticmethod
    def _is_hashimoto(name):
        n = re.sub(r"\s+", " ", (name or "").strip())
        return n in HASHIMOTO_NAMES or "橋本" in n or "ARAKUN" in n.upper()

    def _load(self):
        for path in self._candidate_files():
            self._parse_line_export(path)
        self._build_aliases()
        self._build_exchanges()
        self._build_direct_mentions()

    def _parse_line_export(self, path):
        current = None
        try:
            fh = open(path, encoding="utf-8-sig", errors="ignore")
        except OSError:
            return
        with fh:
            for raw in fh:
                line = raw.rstrip("\n\r")
                m = re.match(r"^(\d{1,2}:\d{2})\t([^\t]+)\t(.*)$", line)
                if m:
                    current = {
                        "time": m.group(1),
                        "sender": m.group(2).strip(),
                        "text": m.group(3).strip(),
                        "source": os.path.basename(path),
                    }
                    self.messages.append(current)
                    self.participants.add(current["sender"])
                elif current and line and not re.match(r"^\d{4}/\d", line):
                    current["text"] = (current["text"] + " / " + line.strip()).strip(" / ")

    def _build_aliases(self):
        aliases = defaultdict(set)
        for name in self.participants:
            if self._is_hashimoto(name):
                continue
            aliases[name].add(name)
            base_name = re.sub(r"(?:さん|くん|君|ちゃん)$", "", name).strip()
            if len(base_name) >= 2:
                aliases[name].add(base_name)
            compact = re.sub(r"\s+", "", name)
            if len(compact) >= 2:
                aliases[name].add(compact)
            for part in re.split(r"[\s　]+", name):
                if len(part) >= 2:
                    aliases[name].add(part)

        # Static aliases are valid even if a particular export uses an English
        # display name. Pick the corpus participant when an equivalent exists.
        for preferred, vals in STATIC_ALIASES.items():
            canonical = preferred
            if preferred not in aliases:
                # e.g. Japanese 関口 alias -> Ryo Sekiguchi corpus participant
                candidates = [p for p in aliases if p in vals or any(v in p for v in vals if len(v) >= 2)]
                if candidates:
                    canonical = candidates[0]
            aliases[canonical].update(vals)

        self.name_to_aliases = aliases
        for canonical, vals in aliases.items():
            for alias in vals:
                self.alias_to_name[alias] = canonical

    def _build_exchanges(self):
        msgs = self.messages
        for i in range(1, len(msgs)):
            a, b = msgs[i - 1], msgs[i]
            ah, bh = self._is_hashimoto(a["sender"]), self._is_hashimoto(b["sender"])
            if ah == bh:
                continue
            partner = b["sender"] if ah else a["sender"]
            if self._is_hashimoto(partner):
                continue
            self._interaction_counts[partner] += 1
            h, p = (a, b) if ah else (b, a)
            direction = "hashimoto_to_partner" if ah else "partner_to_hashimoto"
            self._exchange_cache[partner].append({
                "direction": direction,
                "partner_text": p["text"],
                "hashimoto_text": h["text"],
                "source": h["source"],
            })

    def _build_direct_mentions(self):
        for canonical, aliases in self.name_to_aliases.items():
            usable = sorted({a for a in aliases if len(a) >= 2}, key=len, reverse=True)
            if not usable:
                continue
            for m in self.messages:
                if not self._is_hashimoto(m["sender"]):
                    continue
                text = m["text"] or ""
                if MEDIA_RE.search(text):
                    continue
                matched = next((a for a in usable if a in text), None)
                if matched:
                    self._direct_mentions[canonical].append({
                        "text": text,
                        "alias": matched,
                        "evaluative": bool(EVALUATION_RE.search(text)),
                        "source": m["source"],
                    })

    @staticmethod
    def _clean_token(text):
        t = (text or "").strip(" \t\r\n、。！？?『』「」")
        t = DISCOURSE_PREFIX_RE.sub("", t)
        t = re.sub(r"(?:のこと|について)$", "", t).strip()
        t = re.sub(r"(?:さん|くん|君|ちゃん)$", "", t).strip() or t
        return t

    def resolve_alias(self, text):
        raw = self._clean_token(text)
        if raw in {"俺", "おれ", "僕", "ぼく", "私", "わたし", "自分"}:
            return "USER_SELF"
        for alias in sorted(self.alias_to_name, key=len, reverse=True):
            a = re.sub(r"(?:さん|くん|君|ちゃん)$", "", alias).strip()
            if raw == alias or raw == a:
                return self.alias_to_name[alias]
        return None

    def resolve_context(self, user_text, current_speaker=None, behavior=None):
        """Resolve once, early, and return a stable canonical person context."""
        text = (user_text or "").strip()
        behavior = behavior or {}

        if behavior.get("subject_role") == "assistant_self":
            return {"used": False, "kind": "assistant_self", "person_id": "", "canonical": "", "matched_alias": "", "aliases": []}

        # Speaker first-person reference.
        if re.search(r"(?:^|[\s、。！？?])(俺|おれ|僕|ぼく|私|わたし|自分)(?:のこと|について|は|って|を|が|$)", text):
            canonical = self.alias_to_name.get(current_speaker, current_speaker or "")
            if canonical:
                return self._context_payload(canonical, "USER_SELF", "user_self")

        # First try the explicit behavior subject if available.
        subject = str(behavior.get("subject", "") or "").strip()
        for hay in [subject, text]:
            for alias in sorted(self.alias_to_name, key=len, reverse=True):
                if alias and alias in hay:
                    return self._context_payload(self.alias_to_name[alias], alias, "named_person")

        return {"used": False, "kind": "none", "person_id": "", "canonical": "", "matched_alias": "", "aliases": []}

    def _context_payload(self, canonical, matched_alias, kind):
        aliases = sorted(self.name_to_aliases.get(canonical, {canonical}), key=lambda x: (-len(x), x))
        return {
            "used": True,
            "kind": kind,
            "person_id": canonical,
            "canonical": canonical,
            "matched_alias": matched_alias,
            "aliases": aliases,
        }

    def search_text(self, user_text, person_context):
        """Augment retrieval with canonical + aliases while preserving the predicate."""
        pc = person_context or {}
        if not pc.get("used"):
            return user_text
        aliases = [a for a in pc.get("aliases", []) if a and a != pc.get("canonical")]
        # A handful is enough; avoid drowning the predicate in nickname spam.
        anchors = [pc.get("canonical", "")] + aliases[:5]
        anchors = [a for a in anchors if a]
        return f"{' '.join(anchors)} {user_text}".strip()

    def resolve_target(self, user_text, behavior, current_speaker=None, person_context=None):
        pc = person_context or self.resolve_context(user_text, current_speaker, behavior)
        return pc.get("canonical") if pc.get("used") else None

    def evidence(self, user_text, behavior, current_speaker=None, relationship_policy=None, max_examples=6, person_context=None):
        pc = person_context or self.resolve_context(user_text, current_speaker, behavior)
        target = pc.get("canonical") if pc.get("used") else None
        if not target:
            return {
                "used": False, "target": "", "person_context": pc,
                "interaction_count": 0, "examples": [], "direct_mentions": [],
                "signals": [], "action_policy": [], "reason": "no_person_target",
            }

        exchanges = self._exchange_cache.get(target, [])
        viable = [x for x in exchanges if x["partner_text"] and x["hashimoto_text"]
                  and not MEDIA_RE.search(x["partner_text"]) and not MEDIA_RE.search(x["hashimoto_text"])]

        signal_counts = Counter()
        scored_examples = []
        for idx, x in enumerate(viable):
            ht = x["hashimoto_text"]
            local = []
            for key, pat in SIGNAL_PATTERNS.items():
                if pat.search(ht):
                    signal_counts[key] += 1
                    local.append(key)
            score = 3*("strong_banter" in local) + 2*("laughter" in local) + 2*("planning" in local) \
                    + 1*("questioning" in local) + 1*("agreement" in local) + 1*("short_reaction" in local)
            if 2 <= len(ht) <= 70 and 2 <= len(x["partner_text"]) <= 90:
                score += 1
            scored_examples.append((score, idx, x))
        scored_examples.sort(key=lambda t: (t[0], -t[1]), reverse=True)

        picked, seen_pairs = [], set()
        for _score, _idx, x in scored_examples:
            key = (x["partner_text"], x["hashimoto_text"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            picked.append(x)
            if len(picked) >= max_examples:
                break

        ranked_signals = []
        total = max(1, len(viable))
        for key, count in signal_counts.most_common():
            if count >= 2:
                ranked_signals.append({"signal": key, "label": SIGNAL_LABELS[key], "count": int(count), "rate": round(count/total, 3)})
            if len(ranked_signals) >= 5:
                break

        direct = list(self._direct_mentions.get(target, []))
        # Evaluative mentions first, then concise factual mentions.
        direct.sort(key=lambda x: (bool(x.get("evaluative")), 2 <= len(x.get("text", "")) <= 80), reverse=True)
        direct_picked, seen_text = [], set()
        for x in direct:
            if x["text"] in seen_text:
                continue
            seen_text.add(x["text"])
            direct_picked.append(x)
            if len(direct_picked) >= 6:
                break

        policy_node = (relationship_policy or {}).get(target, {}) or {}
        actions = policy_node.get("action_policy", {}) or {}
        ranked_actions = sorted(
            ((k, int(v.get("count", 0)), float(v.get("probability", 0.0))) for k, v in actions.items()),
            key=lambda x: (x[1], x[2]), reverse=True,
        )[:4]

        return {
            "used": bool(viable or direct_picked or ranked_actions),
            "target": target,
            "person_context": pc,
            "interaction_count": int(self._interaction_counts.get(target, 0)),
            "examples": picked,
            "direct_mentions": direct_picked,
            "signals": ranked_signals,
            "action_policy": [{"action": a, "count": c, "probability": round(p, 3)} for a, c, p in ranked_actions if c > 0],
            "reason": "canonical_person_corpus_evidence",
        }

    @staticmethod
    def format(evidence):
        ev = evidence or {}
        if not ev.get("used"):
            return "人物関係の直接資料なし"
        pc = ev.get("person_context") or {}
        lines = [
            f"対象人物ID: {ev.get('target','')}",
            f"入力で使われた呼称: {pc.get('matched_alias','')}",
            f"隣接会話数: {ev.get('interaction_count',0)}",
        ]
        direct = ev.get("direct_mentions") or []
        if direct:
            lines.append("橋本本人が対象へ言及した実発言:")
            for x in direct:
                lines.append(f"- {x['text']}")
        signals = ev.get("signals") or []
        if signals:
            lines.append("観測できる関係シグナル: " + ", ".join(f"{x['label']}({x['count']})" for x in signals))
        actions = ev.get("action_policy") or []
        if actions:
            lines.append("この相手への実測行動傾向: " + ", ".join(f"{x['action']}({x['count']})" for x in actions))
        examples = ev.get("examples") or []
        if examples:
            lines.append("実際の隣接会話例:")
            for x in examples:
                if x.get("direction") == "partner_to_hashimoto":
                    lines.append(f"- {ev.get('target')}: {x['partner_text']} → 橋本新: {x['hashimoto_text']}")
                else:
                    lines.append(f"- 橋本新: {x['hashimoto_text']} → {ev.get('target')}: {x['partner_text']}")
        lines.append(
            "生成規則: この人物IDを最後まで維持する。別名を別人として再解釈しない。"
            "資料があるのに『誰かわからない』『何の略かわからない』へ逃げない。"
            "人物評は上の実発言・実会話から言える範囲だけで答え、未記録の出来事や強い好き嫌いを作らない。"
        )
        return "\n".join(lines)
