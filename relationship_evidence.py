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
    "Ryo Sekiguchi": {"Ryo Sekiguchi", "関口", "関口さん", "せきぐち", "せっきー", "セッキー", "せっき", "セッキ"},
    "中山 貴文": {"中山 貴文", "中山", "中山さん", "貴文", "ぽつぉ", "ぽつお", "ポツォ", "ポッツォ", "ぽつ", "ぽっつぉ"},
    "村田": {"村田", "村田さん", "ムタ", "むた"},
    "坂口": {"坂口", "坂口さん", "さかぐち"},
}

DISCOURSE_PREFIX_RE = re.compile(r"^(?:じゃあ|じゃ|なら|では|で、|えっと|まあ|まぁ)\s*")
SUBJECT_TAIL_RE = re.compile(r"(?:のこと|について|って|は|を|が)?\s*(?:どう思(?:ってる|う)|どう感じる|好き|嫌い).*$")

MEDIA_RE = re.compile(r"^\[(?:写真|スタンプ|動画|ファイル|アルバム)\]$|https?://", re.I)
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

    def resolve_alias(self, text):
        """Resolve a person alias without inferring any relationship semantics."""
        raw = (text or "").strip(" \t\r\n、。！？?『』「」")
        raw = re.sub(r"(?:さん|くん|君|ちゃん)$", "", raw).strip() or raw
        if raw in {"俺", "おれ", "僕", "ぼく", "私", "わたし", "自分"}:
            return "USER_SELF"
        aliases = sorted(self.alias_to_name, key=len, reverse=True)
        for alias in aliases:
            a = re.sub(r"(?:さん|くん|君|ちゃん)$", "", alias).strip()
            if raw == alias or raw == a:
                return self.alias_to_name[alias]
        return None

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
                "signals": [],
                "action_policy": [],
                "reason": "no_person_target",
            }

        exchanges = self._exchange_cache.get(target, [])
        viable = [
            x for x in exchanges
            if x["partner_text"] and x["hashimoto_text"]
            and not MEDIA_RE.search(x["partner_text"])
            and not MEDIA_RE.search(x["hashimoto_text"])
        ]

        # Build an observable relationship signature from Hashimoto's actual
        # adjacent utterances. These are behavior signals, not inferred feelings.
        signal_counts = Counter()
        scored_examples = []
        for idx, x in enumerate(viable):
            ht = x["hashimoto_text"]
            local = []
            for key, pat in SIGNAL_PATTERNS.items():
                if pat.search(ht):
                    signal_counts[key] += 1
                    local.append(key)
            # Prefer exchanges that reveal interaction style and keep samples
            # spread across the corpus instead of simply taking recent lines.
            relational_score = (
                3 * ("strong_banter" in local)
                + 2 * ("laughter" in local)
                + 2 * ("planning" in local)
                + 1 * ("questioning" in local)
                + 1 * ("agreement" in local)
                + 1 * ("short_reaction" in local)
            )
            if 2 <= len(ht) <= 70 and 2 <= len(x["partner_text"]) <= 90:
                relational_score += 1
            scored_examples.append((relational_score, idx, x))

        scored_examples.sort(key=lambda t: (t[0], -t[1]), reverse=True)
        picked = []
        seen_pairs = set()
        for _score, _idx, x in scored_examples:
            key = (x["partner_text"], x["hashimoto_text"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            picked.append(x)
            if len(picked) >= max_examples:
                break

        total = max(1, len(viable))
        ranked_signals = []
        for key, count in signal_counts.most_common():
            if count < 2:
                continue
            ranked_signals.append({
                "signal": key,
                "label": SIGNAL_LABELS[key],
                "count": int(count),
                "rate": round(count / total, 3),
            })
            if len(ranked_signals) >= 5:
                break

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
            "signals": ranked_signals,
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
        signals = ev.get("signals") or []
        if signals:
            lines.append("観測できる関係シグナル: " + ", ".join(
                f"{x['label']}({x['count']})" for x in signals
            ))
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
        lines.append("注意: 会話量・口調・反応様式の根拠であり、好き嫌い等の未記録な内面を断定する根拠ではない。人物評価を答える時は、無難な「微妙」「別に」だけで逃げず、この観測シグナルのどれかを内容に反映する。")
        return "\n".join(lines)
