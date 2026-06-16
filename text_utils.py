import unicodedata


def normalize_text(text) -> str:
    text = "" if text is None else str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = text.replace(" ", "").replace("　", "")
    text = text.replace("！", "!").replace("？", "?")
    return text


def load_lines(filename: str, max_lines: int | None = None) -> list[str]:
    try:
        result = []
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.lstrip().startswith("#"):
                    continue
                result.append(line)
                if max_lines and len(result) >= max_lines:
                    break
        return result
    except FileNotFoundError:
        return []


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        item = str(item).strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out
