"""
config.py – centralised configuration loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "")
TELEGRAM_APP_SHORT_NAME: str = os.getenv("TELEGRAM_APP_SHORT_NAME", "")
TELEGRAM_OIDC_CLIENT_ID: str = os.getenv(
    "TELEGRAM_OIDC_CLIENT_ID", TELEGRAM_BOT_TOKEN.split(":", 1)[0]
)
TELEGRAM_OIDC_CLIENT_SECRET: str = os.getenv("TELEGRAM_OIDC_CLIENT_SECRET", "")

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]

CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
SESSION_SECRET: str = os.getenv("SESSION_SECRET", TELEGRAM_BOT_TOKEN)
SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
AUTH_MAX_AGE: int = int(os.getenv("AUTH_MAX_AGE", "900"))
