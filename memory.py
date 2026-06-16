from collections import deque
import config


class ConversationMemory:
    def __init__(self):
        self.store: dict[str, deque[str]] = {}

    def add(self, chat_key: str, text: str):
        if chat_key not in self.store:
            self.store[chat_key] = deque(maxlen=config.HISTORY_LEN)
        self.store[chat_key].append(text)

    def context(self, chat_key: str, current_text: str) -> str:
        history = list(self.store.get(chat_key, deque(maxlen=config.HISTORY_LEN)))
        return "\n".join(history + [current_text])
