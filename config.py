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

# Shared secret required before a Telegram identity can create an app session.
# Keep this backend-only; the user enters it in the login screen.
APP_API_KEY: str = os.getenv("APP_API_KEY", "").strip()
# Server-to-server key for the external agent integration. Keep this optional
# at startup so existing bot deployments continue to work until configured.
AGENT_RATES_API_KEY: str = os.getenv("AGENT_RATES_API_KEY", "").strip()
# Keep accepting the shorter name so deployments can migrate without a
# simultaneous environment-variable rename.
API_KEY_ALIAS: str = os.getenv("API_KEY", "").strip()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
# Storage can use a separate service-role key when SUPABASE_KEY is the public
# anon key used for database requests.
SUPABASE_STORAGE_KEY: str = os.getenv("SUPABASE_STORAGE_KEY", SUPABASE_KEY)

CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
SESSION_SECRET: str = os.getenv("SESSION_SECRET", TELEGRAM_BOT_TOKEN)
SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
# Persistent login session lifetime. The cookie remains HttpOnly and signed.
SESSION_MAX_AGE: int = int(os.getenv("SESSION_MAX_AGE", str(60 * 60 * 24 * 30)))
# Telegram's signed Mini App data can be reused when Telegram restores a
# recently opened webview. Keep the replay window bounded but practical.
AUTH_MAX_AGE: int = int(os.getenv("AUTH_MAX_AGE", "86400"))

# Instance of btseee/mongolian-bank-exchange-rate used for commercial-bank
# rates. MongolBank itself is fetched from the official BOM endpoint.
MONGOLIAN_BANK_API_URL: str = os.getenv(
    "MONGOLIAN_BANK_API_URL",
    "https://bank-api.oyuns.mn",
).rstrip("/")
