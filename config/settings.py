"""Load environment variables and expose typed config."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required environment variable '{key}' is not set. See .env.example.")
    return val


class Config:
    # Paths
    ROOT_DIR: Path = _ROOT
    DATA_DIR: Path = _ROOT / "data"
    CACHE_DIR: Path = _ROOT / "data" / "cache"
    LOGS_DIR: Path = _ROOT / "logs"
    DB_PATH: Path = _ROOT / "data" / "compliance.db"

    # API keys (lazy — validated at first access, not import time)
    @staticmethod
    def anthropic_api_key() -> str:
        return _require("ANTHROPIC_API_KEY")

    @staticmethod
    def gmail_address() -> str:
        return _require("GMAIL_ADDRESS")

    @staticmethod
    def gmail_app_password() -> str:
        return _require("GMAIL_APP_PASSWORD")

    # Email sender identity
    GMAIL_FROM_NAME: str = os.getenv("GMAIL_FROM_NAME", "Andersen Compliance Intelligence")

    # Behaviour
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "12"))


# Create required directories on import
for _d in (Config.DATA_DIR, Config.CACHE_DIR, Config.LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
