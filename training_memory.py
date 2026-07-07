from collections import defaultdict, deque
import time


class TrainingMemory:
    """
    Lightweight in-memory workout log.
    Render restarts will reset this.
    For persistent logs, connect DB later.
    """

    def __init__(self, max_items=30):
        self.logs = defaultdict(lambda: deque(maxlen=max_items))

    def add(self, chat_id: str, text: str):
        item = {
            "ts": int(time.time()),
            "text": text,
        }
        self.logs[chat_id].append(item)
        return item

    def recent(self, chat_id: str, limit=5):
        return list(self.logs[chat_id])[-limit:]

    def format_recent(self, chat_id: str, limit=5):
        items = self.recent(chat_id, limit=limit)
        if not items:
            return "まだ筋トレ記録はありません。"
        lines = []
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['text']}")
        return "\n".join(lines)
