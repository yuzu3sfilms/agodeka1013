import random
import config
from text_utils import load_jsonl, load_lines, normalize_text, context_to_text, make_query_terms, unique_preserve_order


class HashimotoArataDataStore:
    def __init__(self):
        self.messages = load_jsonl(config.MESSAGES_FILE, config.MAX_MESSAGE_SCAN)
        self.reply_pairs = load_jsonl(config.REPLY_PAIRS_FILE, config.MAX_REPLY_PAIR_SCAN)
        self.style_examples = load_lines(config.STYLE_FILE, config.MAX_STYLE_SCAN)
        self.keywords = load_lines(config.KEYWORDS_FILE, 2500)
        self.keyword_pairs = [(normalize_text(k), k) for k in self.keywords if 2 <= len(normalize_text(k)) <= 40]

        self.message_entries = [(normalize_text(m.get("text", "")), m) for m in self.messages]
        self.reply_entries = []
        for p in self.reply_pairs:
            ctx = context_to_text(p.get("context", []))
            rep = p.get("reply", "")
            joined = ctx + "\n" + rep
            self.reply_entries.append((normalize_text(joined), normalize_text(ctx), normalize_text(rep), p))

    def keyword_hits(self, context_text: str, limit: int = 30) -> list[tuple[str, str]]:
        nt = normalize_text(context_text)
        hits = []
        for nk, raw in self.keyword_pairs:
            if nk in nt:
                hits.append((nk, raw))
                if len(hits) >= limit:
                    break
        return hits

    def score_text(self, normalized_target: str, terms: list[str], context_weight: int = 1) -> int:
        score = 0
        for term in terms:
            if term in normalized_target:
                if len(term) >= 8:
                    score += 70 * context_weight
                elif len(term) >= 5:
                    score += 38 * context_weight
                elif len(term) >= 3:
                    score += 12 * context_weight
        return score

    def search(self, context_text: str) -> dict:
        hits = self.keyword_hits(context_text)
        hit_terms = [nk for nk, _raw in hits]
        terms = make_query_terms(context_text, hit_terms)

        reply_scored = []
        for joined_n, ctx_n, rep_n, p in self.reply_entries:
            # Context match is most important; reply match also useful but weaker.
            score = self.score_text(ctx_n, terms, context_weight=3) + self.score_text(rep_n, terms, context_weight=1)
            if score > 0:
                reply_scored.append((score, p))
        reply_scored.sort(key=lambda x: x[0], reverse=True)

        msg_scored = []
        for text_n, m in self.message_entries:
            score = self.score_text(text_n, terms, context_weight=1)
            if score > 0:
                msg_scored.append((score, m))
        msg_scored.sort(key=lambda x: x[0], reverse=True)

        # Style examples: close examples if possible, otherwise random examples.
        style_scored = []
        for s in self.style_examples:
            sn = normalize_text(s)
            score = self.score_text(sn, terms, context_weight=1)
            if score > 0:
                style_scored.append((score, s))
        style_scored.sort(key=lambda x: x[0], reverse=True)
        styles = [s for _score, s in style_scored[:config.TOP_STYLE]]
        if len(styles) < config.TOP_STYLE and self.style_examples:
            extra = random.sample(self.style_examples, min(config.TOP_STYLE - len(styles), len(self.style_examples)))
            styles.extend(extra)

        return {
            "matched_words": [raw for _nk, raw in hits[:30]],
            "reply_pairs": [p for _score, p in reply_scored[:config.TOP_REPLY_PAIRS]],
            "messages": [m for _score, m in msg_scored[:config.TOP_MESSAGES]],
            "style_examples": unique_preserve_order(styles)[:config.TOP_STYLE],
        }
