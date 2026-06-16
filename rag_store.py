import random
from dataclasses import dataclass

import config
from text_utils import normalize_text, load_lines, unique_preserve_order


DEFAULT_TRIGGERS = [
    "あらくん", "橋本", "橋本新", "新橋本", "新橋本新", "顎", "アゴ",
    "あご", "agodeka", "きゃぴい", "きゃぴぃ", "キャピい", "キャピイ",
    "キャピィ", "きゃっぴい", "かわいいでしょ", "ぼくぅ", "フリーポーズ",
    "表情", "無理ゲー", "難しいです", "お願いします", "牛角多すぎます",
    "地図はからっきし", "美味しいよ", "いきなりステーキ", "エスターク",
    "ブックオフ", "二郎", "野猿", "ボンジョヴィ", "ボン・ジョヴィ",
    "玩具", "ｷﾞｬｵｫ", "ギャオ", "トーマス", "アナザーアラクン",
    "橋本新名言集", "筋トレ", "スクワット", "ベンチプレス", "デッドリフト",
    "ゴールドジム", "小杉湯", "高円寺", "阿佐ヶ谷", "サイゼ",
    "バーミヤン", "ムタァ", "ムタファ", "ポッツォ", "ポツォ",
]

GENERIC_WORDS = {
    "今日", "明日", "昨日", "予定", "仕事", "大丈夫", "了解", "はい",
    "いい", "そう", "これ", "それ", "どれ", "ここ", "そこ", "あれ",
    "です", "ます", "した", "する", "ある", "ない", "こと", "もの",
    "www", "wwww", "笑", "草", "w", "ok", "ng", "やばい", "まじ",
    "えぐい", "line", "twitter", "instagram", "(emoji)", "(thinking)",
}


@dataclass
class RagResult:
    matched_words: list[str]
    episodes: list[str]
    reply_pairs: list[str]
    style_examples: list[str]
    hashimoto_shin: list[str]


class RagStore:
    """
    全語録をなるべく満遍なく拾うための軽量RAG。
    特定語だけをコード側で強く拾うのではなく、
    trigger hit + 文脈断片 + keyword一致でスコアリングする。
    """

    def __init__(self):
        self.raw_triggers = load_lines(config.TRIGGER_FILE, config.MAX_TRIGGERS)
        self.raw_episodes = load_lines(config.EPISODE_FILE, config.MAX_EPISODES)
        self.raw_reply_pairs = load_lines(config.REPLY_PAIR_FILE, config.MAX_REPLY_PAIRS)
        self.raw_style = load_lines(config.STYLE_FILE, config.MAX_STYLE)
        self.raw_hashimoto_shin = load_lines(config.HASHIMOTO_SHIN_FILE, config.MAX_HASHIMOTO_SHIN)

        self.generic = {normalize_text(w) for w in GENERIC_WORDS}

        self.trigger_pairs = self._build_triggers()
        self.episode_entries = self._build_episodes()
        self.reply_entries = [(normalize_text(line), line) for line in self.raw_reply_pairs]
        self.style_entries = [(normalize_text(line), line) for line in self.raw_style]
        self.hashimoto_shin_entries = self._build_hashimoto_shin()

    def _build_triggers(self) -> list[tuple[str, str]]:
        all_triggers = sorted(set(self.raw_triggers + DEFAULT_TRIGGERS), key=len, reverse=True)
        pairs = []

        for word in all_triggers:
            nw = normalize_text(word)
            if not nw:
                continue
            if nw in self.generic:
                continue
            if 2 <= len(nw) <= 40:
                pairs.append((nw, word))

        return sorted(set(pairs), key=lambda x: len(x[0]), reverse=True)

    def _build_episodes(self) -> list[tuple[list[str], str, str]]:
        entries = []

        for line in self.raw_episodes:
            if "::" in line:
                keywords, episode = line.split("::", 1)
                keys = [normalize_text(k.strip()) for k in keywords.split(",") if k.strip()]
                entries.append((keys, normalize_text(episode), episode.strip()))
            else:
                entries.append(([normalize_text(line)], normalize_text(line), line.strip()))

        return entries

    def _build_hashimoto_shin(self) -> list[tuple[str, str]]:
        entries = [(normalize_text(line), line) for line in self.raw_hashimoto_shin]

        for line in self.raw_reply_pairs:
            if "橋本新" in line:
                entries.append((normalize_text(line), line))

        for line in self.raw_episodes:
            if "橋本新" in line:
                entries.append((normalize_text(line), line))

        for line in self.raw_style:
            if "橋本新" in line:
                entries.append((normalize_text(line), line))

        return entries

    def get_trigger_hits(self, context_text: str, limit: int = 20) -> list[tuple[str, str]]:
        nt = normalize_text(context_text)
        hits = []

        for nw, original in self.trigger_pairs:
            if nw in nt:
                hits.append((nw, original))
            if len(hits) >= limit:
                break

        return hits

    def get_query_terms(self, context_text: str, hits: list[tuple[str, str]]) -> list[str]:
        nt = normalize_text(context_text)
        terms = [nw for nw, _original in hits if nw]

        # 文脈断片。長いものを優先することで複合語を拾う。
        for n in (8, 7, 6, 5, 4, 3):
            for i in range(max(0, len(nt) - n + 1)):
                term = nt[i:i+n]
                if term and term not in self.generic:
                    terms.append(term)

        terms = sorted(set(t for t in terms if len(t) >= 2), key=len, reverse=True)
        return terms[:50]

    def balanced_score(
        self,
        normalized_context: str,
        normalized_line: str,
        keys: list[str],
        hits: list[tuple[str, str]],
        terms: list[str],
    ) -> int:
        score = 0

        # keyword::episode の keyword一致
        for key in keys[:12]:
            if key and key not in self.generic and key in normalized_context:
                score += 140 + min(len(key), 24)

        # trigger hit が候補行にある
        for nw, _original in hits:
            if nw and nw in normalized_line:
                score += 90 + min(len(nw), 24)

        # 文脈断片が候補行にある
        for term in terms:
            if term and term in normalized_line:
                if len(term) >= 6:
                    score += 50 + min(len(term), 20)
                elif len(term) >= 4:
                    score += 28 + min(len(term), 14)
                else:
                    score += 8

        return score

    def find_episodes(self, context_text: str, hits: list[tuple[str, str]], terms: list[str]) -> list[str]:
        nt = normalize_text(context_text)
        scored = []

        for keys, normalized_episode, episode in self.episode_entries[:config.SCAN_EPISODES]:
            score = self.balanced_score(nt, normalized_episode, keys, hits, terms)
            if score > 0:
                scored.append((score, episode))

        scored.sort(key=lambda x: x[0], reverse=True)
        return unique_preserve_order([episode for _score, episode in scored[:7]])

    def find_reply_pairs(self, context_text: str, hits: list[tuple[str, str]], terms: list[str]) -> list[str]:
        if not terms:
            return []

        nt = normalize_text(context_text)
        scored = []

        for normalized_line, line in self.reply_entries[:config.SCAN_REPLY_PAIRS]:
            score = self.balanced_score(nt, normalized_line, [], hits, terms)
            if score >= 35:
                scored.append((score, line))

        scored.sort(key=lambda x: x[0], reverse=True)
        return unique_preserve_order([line for _score, line in scored[:6]])

    def find_style_examples(self, context_text: str, hits: list[tuple[str, str]], terms: list[str]) -> list[str]:
        nt = normalize_text(context_text)
        scored = []

        for normalized_line, line in self.style_entries[:config.SCAN_STYLE]:
            score = self.balanced_score(nt, normalized_line, [], hits, terms)
            if score >= 35:
                scored.append((score, line))

        scored.sort(key=lambda x: x[0], reverse=True)
        examples = unique_preserve_order([line for _score, line in scored[:4]])

        if not examples and self.raw_style:
            examples = random.sample(self.raw_style, min(4, len(self.raw_style)))

        return examples[:4]

    def find_hashimoto_shin(self, context_text: str, hits: list[tuple[str, str]], terms: list[str]) -> list[str]:
        local_terms = list(terms)

        if "橋本新" in context_text:
            local_terms.append(normalize_text("橋本新"))

        if not local_terms:
            return []

        nt = normalize_text(context_text)
        scored = []

        for normalized_line, line in self.hashimoto_shin_entries[:config.SCAN_HASHIMOTO_SHIN]:
            score = self.balanced_score(nt, normalized_line, [], hits, local_terms)
            if score >= 25:
                scored.append((score, line))

        scored.sort(key=lambda x: x[0], reverse=True)
        return unique_preserve_order([line for _score, line in scored[:4]])

    def search(self, context_text: str) -> RagResult:
        hits = self.get_trigger_hits(context_text)
        terms = self.get_query_terms(context_text, hits)

        return RagResult(
            matched_words=[original for _nw, original in hits],
            episodes=self.find_episodes(context_text, hits, terms),
            reply_pairs=self.find_reply_pairs(context_text, hits, terms),
            style_examples=self.find_style_examples(context_text, hits, terms),
            hashimoto_shin=self.find_hashimoto_shin(context_text, hits, terms),
        )
