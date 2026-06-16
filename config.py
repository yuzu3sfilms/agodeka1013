import os

# ============================================================
# AIあらくん v9 config
# ============================================================

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

PROMPT_FILE = "AGODEKA1013_PROMPT.txt"
TRIGGER_FILE = "arakun_triggers_exhaustive.txt"
EPISODE_FILE = "arakun_episodes_exhaustive.txt"
REPLY_PAIR_FILE = "arakun_reply_pairs_exhaustive.txt"
STYLE_FILE = "arakun_style_examples_exhaustive.txt"
HASHIMOTO_SHIN_FILE = "hashimoto_shin_examples.txt"  # optional

# Render無料枠対策。薄ければ上げる。重ければ下げる。
MAX_TRIGGERS = int(os.environ.get("MAX_TRIGGERS", "12000"))
MAX_EPISODES = int(os.environ.get("MAX_EPISODES", "9000"))
MAX_REPLY_PAIRS = int(os.environ.get("MAX_REPLY_PAIRS", "5000"))
MAX_STYLE = int(os.environ.get("MAX_STYLE", "1400"))
MAX_HASHIMOTO_SHIN = int(os.environ.get("MAX_HASHIMOTO_SHIN", "700"))

# 検索上限
SCAN_EPISODES = int(os.environ.get("SCAN_EPISODES", "9000"))
SCAN_REPLY_PAIRS = int(os.environ.get("SCAN_REPLY_PAIRS", "2800"))
SCAN_STYLE = int(os.environ.get("SCAN_STYLE", "1000"))
SCAN_HASHIMOTO_SHIN = int(os.environ.get("SCAN_HASHIMOTO_SHIN", "800"))

# 返答
MAX_REPLY_CHARS = int(os.environ.get("MAX_REPLY_CHARS", "190"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "130"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "1.02"))

# 会話履歴
HISTORY_LEN = int(os.environ.get("HISTORY_LEN", "5"))

# 全返信モード
ALWAYS_REPLY = True

# ログ
DEBUG_LOG = os.environ.get("DEBUG_LOG", "1") == "1"
