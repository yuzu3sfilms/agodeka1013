import json
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
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.pairs = self._load_jsonl("pairs.jsonl")
        self.messages = self._load_jsonl("messages.jsonl")
        self.keywords = self._load_txt("keywords.txt")
        self.style_profile = self._load_json("style_profile.json", {})
        self.emotion_profile = self._load_json("emotion_profile.json", {})
        self.presence_profile = self._load_json("presence_profile.json", {})

        self.keyword_norm = [normalize(k) for k in self.keywords[:10000] if len(normalize(k)) >= 2]
        self.pair_index = []
        self.message_index = []
        self._build_index()
        self.safe_replies = self._build_safe_replies()

    def _load_jsonl(self, name: str) -> list[dict]:
        path = self.data_dir / name
        if not path.exists():
            return []
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows

    def _load_txt(self, name: str) -> list[str]:
        path = self.data_dir / name
        if not path.exists():
            return []
        return [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def _load_json(self, name: str, default):
        path = self.data_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _terms(self, text: str) -> set[str]:
        nt = normalize(text)
        terms = set()

        for kw in self.keyword_norm:
            if kw and kw in nt:
                terms.add(kw)

        for n in (10, 9, 8, 7, 6, 5, 4, 3, 2):
            for i in range(max(0, len(nt) - n + 1)):
                terms.add(nt[i:i+n])

        return {t for t in terms if len(t) >= 2}

    def _build_index(self):
        for p in self.pairs:
            text = "\n".join([
                p.get("context_text", ""),
                p.get("last_other", ""),
                p.get("reply", ""),
                p.get("emotion", ""),
                p.get("response_function", ""),
                " ".join(p.get("behavior_tags", [])),
            ])
            self.pair_index.append((p, self._terms(text)))

        for m in self.messages:
            text = "\n".join([
                m.get("text", ""),
                m.get("emotion", ""),
                m.get("response_function", ""),
                " ".join(m.get("behavior_tags", [])),
            ])
            self.message_index.append((m, self._terms(text)))

    def _build_safe_replies(self) -> list[str]:
        candidates = []
        for p in self.pairs:
            r = (p.get("reply") or "").strip()
            if 1 <= len(r) <= 90 and not too_harsh(r):
                candidates.append(r)
        for m in self.messages:
            t = (m.get("text") or "").strip()
            if 1 <= len(t) <= 90 and not too_harsh(t):
                candidates.append(t)
        candidates += ["難しいです。", "お願いします…。", "ちょっと分からないです。", "それは違います。", "これは良いです。"]

        out, seen = [], set()
        for c in candidates:
            if c not in seen:
                out.append(c)
                seen.add(c)
        return out

    def _base_score(self, query_terms: set[str], cand_terms: set[str], cand_text: str) -> int:
        overlap = query_terms & cand_terms
        score = 0
        for t in overlap:
            l = len(t)
            if l >= 7:
                score += 80 + l
            elif l >= 5:
                score += 45 + l
            elif l >= 3:
                score += 16 + l
            else:
                score += 4

        if not any(len(t) >= 4 for t in overlap):
            score = int(score * 0.35)

        # presence profile: most replies are short
        if len(cand_text) <= 30:
            score += 12
        elif len(cand_text) > 90:
            score -= 25

        return score

    def _emotion_bonus(self, item: dict, target_emotion: str, user_emotion: str) -> int:
        emotion = item.get("emotion", "neutral")
        intensity = int(item.get("intensity", 1))

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
        for p, terms in self.pair_index:
            reply = p.get("reply", "")
            score = 24 + self._base_score(query_terms, terms, reply)
            score += self._emotion_bonus(p, target_emotion, user_emotion)
            score += self._function_bonus(p, target_function)

            last_other = p.get("last_other", "")
            if last_other:
                score += self._base_score(query_terms, self._terms(last_other), reply)

            if too_harsh(reply):
                score -= 100

            if score > 35:
                pair_hits.append((score, p))

        pair_hits.sort(key=lambda x: x[0], reverse=True)

        msg_hits = []
        for m, terms in self.message_index:
            text = m.get("text", "")
            score = self._base_score(query_terms, terms, text)
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
