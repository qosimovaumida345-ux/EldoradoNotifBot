"""
Configuration management for Eldorado.gg Order Monitor Bot.
Supports environment variables, .env files, and cloud platforms (Render, Railway, VPS).
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Force UTF-8 on standard streams if possible
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Configure logging with UTF-8 support
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
handlers = [logging.StreamHandler(sys.stdout)]

try:
    file_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
    handlers.append(file_handler)
except Exception:
    pass

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format=log_format,
    handlers=handlers
)
logger = logging.getLogger("EldoradoConfig")


class Config:
    """Configuration class for the bot."""
    
    def __init__(self):
        self.config_file = BASE_DIR / "config.json"
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from environment and defaults."""
        default_config = {
            "gmail": {
                "user": os.getenv("GMAIL_USER", "").strip(),
                "app_password": os.getenv("GMAIL_APP_PASSWORD", "").strip(),
                "sender_filter": os.getenv("SENDER_FILTER", "eldorado.gg").strip()
            },
            "telegram": {
                "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
                "chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
                "parse_mode": "HTML"
            },
            "monitoring": {
                "check_interval_seconds": int(os.getenv("CHECK_INTERVAL_SECONDS", "20")),
                "max_emails_to_check": int(os.getenv("MAX_EMAILS_TO_CHECK", "50")),
                "seen_uids_limit": int(os.getenv("SEEN_UIDS_LIMIT", "500")),
                "lookback_days": int(os.getenv("LOOKBACK_DAYS", "3"))
            },
            "health_check": {
                "port": int(os.getenv("PORT", os.getenv("HEALTH_CHECK_PORT", "10000")))
            }
        }
        
        # Load from config.json if exists
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    default_config.update(file_config)
            except Exception as e:
                logger.warning(f"Could not load config.json: {e}")
        
        self._config = default_config
    
    def get(self, section: str, key: str, default=None):
        """Get configuration value."""
        return self._config.get(section, {}).get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration."""
        return self._config.copy()
    
    def validate(self):
        """Validate required configuration values."""
        required = [
            ("GMAIL_USER", self.get("gmail", "user")),
            ("GMAIL_APP_PASSWORD", self.get("gmail", "app_password")),
            ("TELEGRAM_BOT_TOKEN", self.get("telegram", "bot_token")),
            ("TELEGRAM_CHAT_ID", self.get("telegram", "chat_id"))
        ]
        
        missing = [name for name, val in required if not val]
        if missing:
            logger.warning(f"Missing environment variables: {', '.join(missing)}")
            return False
        return True


# Global configuration instance
config = Config()

# Export commonly used values
GMAIL_USER = config.get("gmail", "user", "")
GMAIL_APP_PASSWORD = config.get("gmail", "app_password", "")
SENDER_FILTER = config.get("gmail", "sender_filter", "eldorado.gg")

TELEGRAM_BOT_TOKEN = config.get("telegram", "bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram", "chat_id", "")
TELEGRAM_PARSE_MODE = config.get("telegram", "parse_mode", "HTML")

CHECK_INTERVAL_SECONDS = config.get("monitoring", "check_interval_seconds", 20)
MAX_EMAILS_TO_CHECK = config.get("monitoring", "max_emails_to_check", 50)
SEEN_UIDS_LIMIT = config.get("monitoring", "seen_uids_limit", 500)
LOOKBACK_DAYS = config.get("monitoring", "lookback_days", 3)

HEALTH_CHECK_PORT = config.get("health_check", "port", 10000)