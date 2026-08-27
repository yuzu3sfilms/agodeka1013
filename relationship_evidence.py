from __future__ import annotations

import glob
import os
import re
from collections import Counter, defaultdict


HASHIMOTO_NAMES = {
    "橋本新", "Arata Hashimoto", "LIAR  OF  ARAKUN", "LIAR OF ARAKUN",
    "あらくん", "顎", "AGODEKA", "サブ垢です", "Unknown",
}

# Only identity aliases, never personality/value assertions.
STATIC_ALIASES = {
    "Reiji Shioda": {"Reiji Shioda", "塩田", "れーじ", "レージ"},
    "Ryo Sekiguchi": {"Ryo Sekiguchi", "関口", "せきぐち"},
    "中山 貴文": {"中山 貴文", "中山", "貴文"},
    "村田": {"村田", "ムタ"},
    "坂口": {"坂口"},
}

DISCOURSE_PREFIX_RE = re.compile(r"^(?:じゃあ|じゃ|なら|では|で、|えっと|まあ|まぁ)\s*")
SUBJECT_TAIL_RE = re.compile(r"(?:のこと|について|って|は|を|が)?\s*(?:どう思(?:ってる|う)|どう感じる|好き|嫌い).*$")


class RelationshipEvidenceIndex:
    """Corpus-derived relationship evidence for every participant in LINE logs.

    This does not invent a relationship label. It stores observable interaction
    counts and real adjacent exchanges between Hashimoto and each participant.
    """

    def __init__(self, roots=None):
        self.roots = roots or ["data", "."]
        self.messages = []
        self.participants = set()
        self.alias_to_name = {}
        self._exchange_cache = defaultdict(list)
        self._interaction_counts = Counter()
        self._load()

    def _candidate_files(self):
        seen = set()
        out = []
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

    def _load(self):
        for path in self._candidate_files():
            self._parse_line_export(path)
        self._build_aliases()
        self._build_exchanges()

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

    @staticmethod
    def _is_hashimoto(name):
        n = re.sub(r"\s+", " ", (name or "").strip())
        return n in HASHIMOTO_NAMES or "橋本" in n or "ARAKUN" in n.upper()

    def _build_aliases(self):
        aliases = defaultdict(set)
        for name in self.participants:
            if self._is_hashimoto(name):
                continue
            aliases[name].add(name)
            compact = re.sub(r"\s+", "", name)
            if len(compact) >= 2:
                aliases[name].add(compact)
            for part in re.split(r"[\s　]+", name):
                if len(part) >= 2:
                    aliases[name].add(part)
        for canonical, vals in STATIC_ALIASES.items():
            if canonical in self.participants:
                aliases[canonical].update(vals)
        for canonical, vals in aliases.items():
            for alias in vals:
                self.alias_to_name[alias] = canonical

    def _build_exchanges(self):
        msgs = self.messages
        for i in range(1, len(msgs)):
            a, b = msgs[i - 1], msgs[i]
            ah = self._is_hashimoto(a["sender"])
            bh = self._is_hashimoto(b["sender"])
            if ah == bh:
                continue
            partner = b["sender"] if ah else a["sender"]
            if self._is_hashimoto(partner):
                continue
            self._interaction_counts[partner] += 1
            h = a if ah else b
            p = b if ah else a
            direction = "hashimoto_to_partner" if ah else "partner_to_hashimoto"
            self._exchange_cache[partner].append({
                "direction": direction,
                "partner_text": p["text"],
                "hashimoto_text": h["text"],
                "source": h["source"],
            })

    def resolve_target(self, user_text, behavior, current_speaker=None):
        behavior = behavior or {}
        role = behavior.get("subject_role", "")
        if role == "assistant_self":
            return None
        if role == "user_self" and current_speaker:
            return self.alias_to_name.get(current_speaker, current_speaker)

        subject = str(behavior.get("subject", "") or "").strip()
        subject = DISCOURSE_PREFIX_RE.sub("", subject)
        subject = SUBJECT_TAIL_RE.sub("", subject).strip(" 、。？?")
        haystacks = [subject, user_text or ""]
        # Longest aliases first to avoid partial-name collisions.
        aliases = sorted(self.alias_to_name, key=len, reverse=True)
        for hay in haystacks:
            for alias in aliases:
                if alias and alias in hay:
                    return self.alias_to_name[alias]
        return None

    def evidence(self, user_text, behavior, current_speaker=None, relationship_policy=None, max_examples=6):
        target = self.resolve_target(user_text, behavior, current_speaker)
        if not target:
            return {
                "used": False,
                "target": "",
                "interaction_count": 0,
                "examples": [],
                "action_policy": [],
                "reason": "no_person_target",
            }

        exchanges = self._exchange_cache.get(target, [])
        # Prefer concise, text-bearing exchanges; sample across the corpus rather
        # than taking only the first/last cluster.
        viable = [x for x in exchanges if x["partner_text"] and x["hashimoto_text"]]
        if len(viable) > max_examples:
            step = max(1, len(viable) // max_examples)
            picked = viable[::step][:max_examples]
        else:
            picked = viable[:max_examples]

        policy_node = (relationship_policy or {}).get(target, {}) or {}
        actions = policy_node.get("action_policy", {}) or {}
        ranked_actions = sorted(
            ((k, int(v.get("count", 0)), float(v.get("probability", 0.0))) for k, v in actions.items()),
            key=lambda x: (x[1], x[2]), reverse=True,
        )[:4]

        return {
            "used": bool(viable or ranked_actions),
            "target": target,
            "interaction_count": int(self._interaction_counts.get(target, 0)),
            "examples": picked,
            "action_policy": [
                {"action": a, "count": c, "probability": round(p, 3)}
                for a, c, p in ranked_actions if c > 0
            ],
            "reason": "corpus_relationship_evidence" if viable else "policy_relationship_evidence",
        }

    @staticmethod
    def format(evidence):
        ev = evidence or {}
        if not ev.get("used"):
            return "人物関係の直接資料なし"
        lines = [
            f"対象人物: {ev.get('target','')}",
            f"隣接会話数: {ev.get('interaction_count',0)}",
        ]
        actions = ev.get("action_policy") or []
        if actions:
            lines.append("この相手への実測行動傾向: " + ", ".join(
                f"{x['action']}({x['count']})" for x in actions
            ))
        examples = ev.get("examples") or []
        if examples:
            lines.append("実際の隣接会話例:")
            for x in examples:
                if x.get("direction") == "partner_to_hashimoto":
                    lines.append(f"- {ev.get('target')}: {x['partner_text']} → 橋本新: {x['hashimoto_text']}")
                else:
                    lines.append(f"- 橋本新: {x['hashimoto_text']} → {ev.get('target')}: {x['partner_text']}")
        lines.append("注意: 会話量・口調・反応様式の根拠であり、好き嫌い等の未記録な内面を断定する根拠ではない。")
        return "\n".join(lines)
