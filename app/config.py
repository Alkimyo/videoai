import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

DB_PATH = os.getenv("DB_PATH", "data/bot.db")
LOG_PATH = os.getenv("LOG_PATH", "data/bot.log")
BACKUP_DIR = os.getenv("BACKUP_DIR") or os.path.join(
    os.path.dirname(DB_PATH) or "data",
    "backups",
)

BACKUP_TZ = os.getenv("BACKUP_TZ", "Asia/Tashkent")

AUTO_RESTORE_DB = os.getenv("AUTO_RESTORE_DB", "0") == "1"
AUTO_RESTORE_ONLY_IF_NEWER = os.getenv("AUTO_RESTORE_ONLY_IF_NEWER", "1") == "1"

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "10000")))
WEBAPP_ENABLED = os.getenv("WEBAPP_ENABLED", "1") == "1"

SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "0") or 0)

USERBOT_API_ID = int(os.getenv("USERBOT_API_ID", "0") or 0)
USERBOT_API_HASH = os.getenv("USERBOT_API_HASH", "").strip()
USERBOT_SESSION = os.getenv("USERBOT_SESSION", "").strip()
IMPORT_GROUP_ID = int(os.getenv("IMPORT_GROUP_ID", "0") or 0)

LOW_RESOURCE_MODE = os.getenv("LOW_RESOURCE_MODE", "0") == "1"
VIP_REMINDER_INTERVAL = int(os.getenv("VIP_REMINDER_INTERVAL", "0") or 0) or (
    10800 if LOW_RESOURCE_MODE else 3600
)
CONTACT_REPLY_MAXLEN = int(os.getenv("CONTACT_REPLY_MAXLEN", "0") or 0) or (
    500 if LOW_RESOURCE_MODE else 3000
)
USERBOT_IDLE_TIMEOUT = int(os.getenv("USERBOT_IDLE_TIMEOUT", "0") or 0) or (
    600 if LOW_RESOURCE_MODE else 0
)
BROADCAST_BATCH_EVERY = int(os.getenv("BROADCAST_BATCH_EVERY", "0") or 0) or (
    50 if LOW_RESOURCE_MODE else 0
)
BROADCAST_BATCH_SLEEP = float(os.getenv("BROADCAST_BATCH_SLEEP", "0") or 0) or (
    1.0 if LOW_RESOURCE_MODE else 0.0
)
CACHE_CLEAN_INTERVAL = int(os.getenv("CACHE_CLEAN_INTERVAL", "0") or 0) or (
    3600 if LOW_RESOURCE_MODE else 0
)

# In-memory sessions/cache TTL for handlers (seconds).
# Used to prevent unbounded growth of global dict/set state.
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "0") or 0) or (
    3600 if LOW_RESOURCE_MODE else 21600
)
