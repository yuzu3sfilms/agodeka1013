from collections import deque

from config import HISTORY_LEN


class ConversationMemory:
    def __init__(self, history_len: int = HISTORY_LEN):
        self.history_len = history_len
        self._store: dict[str, deque[str]] = {}

    def get_history(self, chat_key: str) -> list[str]:
        return list(self._store.get(chat_key, deque(maxlen=self.history_len)))

    def add(self, chat_key: str, text: str):
        if chat_key not in self._store:
            self._store[chat_key] = deque(maxlen=self.history_len)
        self._store[chat_key].append(text)

    def build_context(self, chat_key: str, user_text: str) -> str:
        return "\n".join(self.get_history(chat_key) + [user_text])
