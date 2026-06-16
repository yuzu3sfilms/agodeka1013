import json
import re
import unicodedata
from pathlib import Path


def normalize_text(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


def load_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def load_lines(path: str, max_lines: int | None = None) -> list[str]:
    try:
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                out.append(line)
                if max_lines and len(out) >= max_lines:
                    break
        return out
    except FileNotFoundError:
        return []


def load_jsonl(path: str, max_lines: int | None = None) -> list[dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
                if max_lines and len(out) >= max_lines:
                    break
    except FileNotFoundError:
        pass
    return out


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        item = str(item).strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def context_to_text(context: list[dict] | list[str]) -> str:
    lines = []
    for item in context:
        if isinstance(item, dict):
            speaker = item.get("speaker", "")
            text = item.get("text", "")
            lines.append(f"{speaker}: {text}")
        else:
            lines.append(str(item))
    return "\n".join(lines)


def make_query_terms(text: str, keyword_hits: list[str]) -> list[str]:
    nt = normalize_text(text)
    terms = list(keyword_hits)

    # Long phrase fragments first. This catches phrases that are in the data but not in keyword list.
    for n in (12, 11, 10, 9, 8, 7, 6, 5, 4, 3):
        for i in range(max(0, len(nt) - n + 1)):
            term = nt[i:i+n]
            if not term:
                continue
            if any(ch in term for ch in "。、,.!?！？[]()（）【】"):
                continue
            terms.append(term)

    stop = {normalize_text(x) for x in [
        "今日", "明日", "昨日", "これ", "それ", "あれ", "どれ", "ここ", "そこ",
        "です", "ます", "した", "する", "ある", "ない", "こと", "もの", "www", "笑", "草",
    ]}

    terms = [t for t in terms if len(t) >= 2 and t not in stop]
    return sorted(set(terms), key=len, reverse=True)[:80]
