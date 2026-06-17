import os

# AI橋本新 v2.2 guaranteed reply config
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.75"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "70"))
MAX_REPLY_CHARS = int(os.environ.get("MAX_REPLY_CHARS", "140"))

DATA_DIR = os.environ.get("DATA_DIR", "data")
MESSAGES_FILE = f"{DATA_DIR}/hashimoto_arata_messages.jsonl"
REPLY_PAIRS_FILE = f"{DATA_DIR}/hashimoto_arata_reply_pairs.jsonl"
STYLE_FILE = f"{DATA_DIR}/hashimoto_arata_style_examples.txt"
KEYWORDS_FILE = f"{DATA_DIR}/hashimoto_arata_keywords.txt"
IDENTITY_PROMPT_FILE = "HASHIMOTO_ARATA_IDENTITY_PROMPT.txt"

HISTORY_LEN = int(os.environ.get("HISTORY_LEN", "3"))
MAX_REPLY_PAIR_SCAN = int(os.environ.get("MAX_REPLY_PAIR_SCAN", "3500"))
MAX_MESSAGE_SCAN = int(os.environ.get("MAX_MESSAGE_SCAN", "3500"))
MAX_STYLE_SCAN = int(os.environ.get("MAX_STYLE_SCAN", "800"))
TOP_REPLY_PAIRS = int(os.environ.get("TOP_REPLY_PAIRS", "2"))
TOP_MESSAGES = int(os.environ.get("TOP_MESSAGES", "2"))
TOP_STYLE = int(os.environ.get("TOP_STYLE", "2"))

DEBUG_LOG = os.environ.get("DEBUG_LOG", "1") == "1"
USE_LOCAL_FALLBACK_ON_RATE_LIMIT = True
RATE_LIMIT_COOLDOWN_SECONDS = int(os.environ.get("RATE_LIMIT_COOLDOWN_SECONDS", "900"))
