import json
import os
import random
from pathlib import Path

from utils import normalize, too_harsh


def detect_user_emotion(text: str) -> str:
    t = text or ""
    if any(x in t for x in ["ありがとう", "助か", "いいね", "最高", "かわいい", "美味しい", "うれしい", "嬉しい"]):
        return "pleased"
    if any(x in t for x in ["？", "?", "どう", "なんで", "わから", "分から", "無理", "難しい"]):
        return "confused"
    if any(x in t for x in ["つら", "疲れ", "しんど", "泣", "😭", "ごめん", "すまん"]):
        return "weak"
    if any(x in t for x in ["！！", "!!", "やば", "すご", "きゃぴ", "ギャオ", "ｷﾞｬｵ"]):
        return "excited"
    if any(x in t for x in ["ムカ", "キレ", "うざ", "腹立", "怒", "黙", "クソ", "くそ"]):
        return "angry"
    if any(x in t for x in ["怖", "不安", "大丈夫", "心配", "まずい"]):
        return "anxious"
    if any(x in t for x in ["ｗ", "笑", "草"]):
        return "teasing"
    return "neutral"


def infer_response_function(user_text: str, user_emotion: str) -> str:
    t = user_text or ""
    if user_emotion in {"confused", "anxious"}:
        return "difficulty"
    if user_emotion == "weak":
        return "appeal"
    if user_emotion in {"pleased", "excited"}:
        return "positive"
    if user_emotion == "teasing":
        return "tease"
    if user_emotion == "angry":
        return "plain_reply"
    if "?" in t or "？" in t:
        return "ask_back"
    return "plain_reply"


class HashimotoStore:
    """
    Render-safe store.

    v5は起動時に全データを読み込み、全件term indexを作ったため512MiBを超えた。
    v5.1では起動時に巨大indexを作らず、必要時だけJSONLを軽くスキャンする。
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.pairs_path = self.data_dir / "pairs.jsonl"
        self.messages_path = self.data_dir / "messages.jsonl"
        self.keywords_path = self.data_dir / "keywords.txt"
        self.style_profile = self._load_json("style_profile.json", {})
        self.emotion_profile = self._load_json("emotion_profile.json", {})
        self.presence_profile = self._load_json("presence_profile.json", {})

        self.max_pair_scan = int(os.environ.get("MAX_PAIR_SCAN", "1800"))
        self.max_message_scan = int(os.environ.get("MAX_MESSAGE_SCAN", "1800"))
        self.max_keywords = int(os.environ.get("MAX_KEYWORDS", "2500"))

        # Small only. Do not load huge data.
        self.keywords = self._load_keywords_small()
        self.safe_replies = self._load_safe_replies_small()

    def _load_json(self, name: str, default):
        path = self.data_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _load_keywords_small(self) -> list[str]:
        if not self.keywords_path.exists():
            return []
        out = []
        with self.keywords_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    n = normalize(line)
                    if len(n) >= 2:
                        out.append(n)
                if len(out) >= self.max_keywords:
                    break
        return out

    def _iter_jsonl(self, path: Path, limit: int):
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _load_safe_replies_small(self) -> list[str]:
        replies = []
        for p in self._iter_jsonl(self.pairs_path, 500):
            r = (p.get("reply") or "").strip()
            if 1 <= len(r) <= 80 and not too_harsh(r):
                replies.append(r)
        for m in self._iter_jsonl(self.messages_path, 500):
            t = (m.get("text") or "").strip()
            if 1 <= len(t) <= 80 and not too_harsh(t):
                replies.append(t)

        replies += ["難しいです。", "お願いします…。", "ちょっと分からないです。", "それは違います。", "これは良いです。"]

        out, seen = [], set()
        for r in replies:
            if r not in seen:
                out.append(r)
                seen.add(r)
        return out

    def _terms(self, text: str) -> set[str]:
        nt = normalize(text)
        terms = set()

        for kw in self.keywords:
            if kw and kw in nt:
                terms.add(kw)

        # Fewer ngrams than v5 to save CPU/memory.
        for n in (8, 7, 6, 5, 4, 3):
            for i in range(max(0, len(nt) - n + 1)):
                g = nt[i:i+n]
                if len(g) >= 3:
                    terms.add(g)

        # hard cap
        return set(sorted(terms, key=len, reverse=True)[:80])

    def _base_score(self, query_terms: set[str], candidate_text: str) -> int:
        nc = normalize(candidate_text)
        score = 0
        has_long = False

        for t in query_terms:
            if t in nc:
                l = len(t)
                if l >= 7:
                    score += 80 + l
                    has_long = True
                elif l >= 5:
                    score += 45 + l
                    has_long = True
                elif l >= 3:
                    score += 16 + l

        if not has_long:
            score = int(score * 0.4)

        if len(candidate_text) <= 30:
            score += 12
        elif len(candidate_text) > 90:
            score -= 25

        return score

    def _emotion_bonus(self, item: dict, target_emotion: str, user_emotion: str) -> int:
        emotion = item.get("emotion", "neutral")
        intensity = int(item.get("intensity", 1) or 1)

        if emotion == target_emotion:
            return 42 + 6 * intensity

        close = {
            "confused": {"weak", "anxious", "polite"},
            "weak": {"confused", "anxious", "polite"},
            "pleased": {"excited", "polite"},
            "excited": {"pleased", "teasing"},
            "teasing": {"excited", "neutral"},
            "anxious": {"weak", "confused", "polite"},
            "neutral": {"polite"},
            "polite": {"neutral", "confused"},
        }
        if emotion in close.get(target_emotion, set()):
            return 18 + 3 * intensity

        if user_emotion == "angry" and emotion == "angry":
            return -35

        return 0

    def _function_bonus(self, item: dict, target_function: str) -> int:
        f = item.get("response_function", "plain_reply")
        if f == target_function:
            return 45

        close = {
            "difficulty": {"appeal", "ask_back", "plain_reply"},
            "appeal": {"difficulty", "plain_reply"},
            "positive": {"high_reaction", "plain_reply"},
            "tease": {"high_reaction", "plain_reply"},
            "ask_back": {"difficulty", "plain_reply"},
            "plain_reply": {"ask_back", "positive"},
        }
        if f in close.get(target_function, set()):
            return 15
        return 0

    def infer_target_emotion(self, context: str) -> str:
        last = context.splitlines()[-1] if context.splitlines() else context
        user_emotion = detect_user_emotion(last)

        if user_emotion == "angry":
            return "polite"
        if user_emotion in {"confused", "weak", "anxious"}:
            return "confused"
        if user_emotion in {"pleased", "excited", "teasing"}:
            return user_emotion
        return "neutral"

    def search(self, context: str, top_pairs: int = 8, top_messages: int = 6) -> dict:
        last = context.splitlines()[-1] if context.splitlines() else context
        query_terms = self._terms(context)
        user_emotion = detect_user_emotion(last)
        target_emotion = self.infer_target_emotion(context)
        target_function = infer_response_function(last, user_emotion)

        pair_hits = []
        for p in self._iter_jsonl(self.pairs_path, self.max_pair_scan):
            reply = p.get("reply", "")
            if not reply:
                continue

            candidate = "\n".join([
                p.get("context_text", ""),
                p.get("last_other", ""),
                reply,
                p.get("emotion", ""),
                p.get("response_function", ""),
                " ".join(p.get("behavior_tags", [])),
            ])

            score = 24 + self._base_score(query_terms, candidate)
            score += self._base_score(query_terms, p.get("last_other", ""))
            score += self._emotion_bonus(p, target_emotion, user_emotion)
            score += self._function_bonus(p, target_function)

            if too_harsh(reply):
                score -= 100

            if score > 35:
                pair_hits.append((score, p))

        pair_hits.sort(key=lambda x: x[0], reverse=True)

        msg_hits = []
        for m in self._iter_jsonl(self.messages_path, self.max_message_scan):
            text = m.get("text", "")
            if not text:
                continue

            candidate = "\n".join([
                text,
                m.get("emotion", ""),
                m.get("response_function", ""),
                " ".join(m.get("behavior_tags", [])),
            ])

            score = self._base_score(query_terms, candidate)
            score += self._emotion_bonus(m, target_emotion, user_emotion)
            score += self._function_bonus(m, target_function)

            if too_harsh(text):
                score -= 100

            if score > 25:
                msg_hits.append((score, m))

        msg_hits.sort(key=lambda x: x[0], reverse=True)

        return {
            "target_emotion": target_emotion,
            "user_emotion": user_emotion,
            "target_function": target_function,
            "pairs": [p for _s, p in pair_hits[:top_pairs]],
            "messages": [m for _s, m in msg_hits[:top_messages]],
            "pair_scores": [s for s, _p in pair_hits[:top_pairs]],
            "message_scores": [s for s, _m in msg_hits[:top_messages]],
        }

    def local_reply(self, context: str) -> str:
        hits = self.search(context, top_pairs=10, top_messages=8)
        candidates = []
        candidates += [p.get("reply", "") for p in hits["pairs"]]
        candidates += [m.get("text", "") for m in hits["messages"]]

        if self.safe_replies:
            candidates += random.sample(self.safe_replies, min(20, len(self.safe_replies)))

        for c in candidates:
            c = str(c).strip()
            if 1 <= len(c) <= 120 and not too_harsh(c):
                return c

        return "難しいです。"
