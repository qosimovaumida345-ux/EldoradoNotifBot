"""
Configuration management for Eldorado.gg Order Monitor Bot.
Supports environment variables, .env files, and secure configuration.
"""

import os
from typing import Dict, Any
from dotenv import load_dotenv
import json
import logging
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
class Config:
    """Configuration class for the bot."""
    
    def __init__(self):
        self.config_file = Path(__file__).parent / 'config.json'
        self.env_file = Path(__file__).parent / '.env'
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from multiple sources."""
        # Default configuration
        default_config = {
            "gmail": {
                "user": os.getenv('GMAIL_USER', ''),
                "app_password": os.getenv('GMAIL_APP_PASSWORD', ''),
                "sender_filter": os.getenv('SENDER_FILTER', 'eldorado.gg')
            },
            "telegram": {
                "bot_token": os.getenv('TELEGRAM_BOT_TOKEN', ''),
                "chat_id": os.getenv('TELEGRAM_CHAT_ID', ''),
                "parse_mode": 'HTML'
            },
            "monitoring": {
                "check_interval_seconds": int(os.getenv('CHECK_INTERVAL_SECONDS', '20')),
                "max_emails_to_check": int(os.getenv('MAX_EMAILS_TO_CHECK', '50')),
                "seen_uids_limit": int(os.getenv('SEEN_UIDS_LIMIT', '500'))
            },
            "redis": {
                "host": os.getenv('REDIS_HOST', 'localhost'),
                "port": int(os.getenv('REDIS_PORT', '6379')),
                "db": int(os.getenv('REDIS_DB', '0')),
                "password": os.getenv('REDIS_PASSWORD', '')
            },
            "logging": {
                "level": os.getenv('LOG_LEVEL', 'INFO'),
                "file": os.getenv('LOG_FILE', 'logs/bot.log'),
                "max_size_mb": int(os.getenv('LOG_MAX_SIZE_MB', '10')),
                "backup_count": int(os.getenv('LOG_BACKUP_COUNT', '5'))
            },
            "health_check": {
                "enabled": os.getenv('HEALTH_CHECK_ENABLED', 'true').lower() == 'true',
                "port": int(os.getenv('HEALTH_CHECK_PORT', '8000')),
                "endpoint": '/health'
            }
        }
        
        # Load from config.json if exists
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    file_config = json.load(f)
                    default_config.update(file_config)
            except Exception as e:
                logger.warning(f"Could not load config.json: {e}")
        
        # Override with environment variables
        self._override_with_env(default_config)
        
        self._config = default_config
    
    def _override_with_env(self, config):
        """Override config values with environment variables."""
        env_mappings = {
            'GMAIL_USER': ('gmail', 'user'),
            'GMAIL_APP_PASSWORD': ('gmail', 'app_password'),
            'SENDER_FILTER': ('gmail', 'sender_filter'),
            'TELEGRAM_BOT_TOKEN': ('telegram', 'bot_token'),
            'TELEGRAM_CHAT_ID': ('telegram', 'chat_id'),
            'CHECK_INTERVAL_SECONDS': ('monitoring', 'check_interval_seconds'),
            'MAX_EMAILS_TO_CHECK': ('monitoring', 'max_emails_to_check'),
            'SEEN_UIDS_LIMIT': ('monitoring', 'seen_uids_limit'),
            'REDIS_HOST': ('redis', 'host'),
            'REDIS_PORT': ('redis', 'port'),
            'REDIS_DB': ('redis', 'db'),
            'REDIS_PASSWORD': ('redis', 'password'),
            'LOG_LEVEL': ('logging', 'level'),
            'LOG_FILE': ('logging', 'file'),
            'LOG_MAX_SIZE_MB': ('logging', 'max_size_mb'),
            'LOG_BACKUP_COUNT': ('logging', 'backup_count'),
            'HEALTH_CHECK_ENABLED': ('health_check', 'enabled'),
            'HEALTH_CHECK_PORT': ('health_check', 'port'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value:
                # Convert numeric values
                if key in ['port', 'db', 'check_interval_seconds', 'max_emails_to_check', 
                          'seen_uids_limit', 'max_size_mb', 'backup_count']:
                    try:
                        value = int(value)
                    except ValueError:
                        logger.warning(f"Invalid integer value for {env_var}: {value}")
                elif key == 'enabled':
                    value = value.lower() == 'true'
                
                config[section][key] = value
    
    def get(self, section: str, key: str, default=None):
        """Get configuration value."""
        return self._config.get(section, {}).get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration."""
        return self._config.copy()
    
    def validate(self):
        """Validate required configuration values."""
        required_fields = [
            ('gmail', 'user'),
            ('gmail', 'app_password'),
            ('telegram', 'bot_token'),
            ('telegram', 'chat_id')
        ]
        
        missing_fields = []
        for section, key in required_fields:
            value = self.get(section, key)
            if not value:
                missing_fields.append(f"{section}.{key}")
        
        if missing_fields:
            raise ValueError(f"Missing required configuration fields: {', '.join(missing_fields)}")
        
        logger.info("Configuration validation passed")
# Global configuration instance
config = Config()

# Export commonly used values
GMAIL_USER = config.get('gmail', 'user', '')
GMAIL_APP_PASSWORD = config.get('gmail', 'app_password', '')
SENDER_FILTER = config.get('gmail', 'sender_filter', 'eldorado.gg')

TELEGRAM_BOT_TOKEN = config.get('telegram', 'bot_token', '')
TELEGRAM_CHAT_ID = config.get('telegram', 'chat_id', '')
TELEGRAM_PARSE_MODE = config.get('telegram', 'parse_mode', 'HTML')

CHECK_INTERVAL_SECONDS = config.get('monitoring', 'check_interval_seconds', 20)
MAX_EMAILS_TO_CHECK = config.get('monitoring', 'max_emails_to_check', 50)
SEEN_UIDS_LIMIT = config.get('monitoring', 'seen_uids_limit', 500)

REDIS_HOST = config.get('redis', 'host', 'localhost')
REDIS_PORT = config.get('redis', 'port', 6379)
REDIS_DB = config.get('redis', 'db', 0)
REDIS_PASSWORD = config.get('redis', 'password', '')

LOG_LEVEL = config.get('logging', 'level', 'INFO')
LOG_FILE = config.get('logging', 'file', 'logs/bot.log')

HEALTH_CHECK_ENABLED = config.get('health_check', 'enabled', True)
HEALTH_CHECK_PORT = config.get('health_check', 'port', 8000)

# Validate configuration on import
if __name__ != '__main__':
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise