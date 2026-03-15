"""
providers.mongolbank – Mongol Bank (central bank) exchange rate provider.

Uses the monxansh.appspot.com proxy for the MongolBank official rates:
  GET https://monxansh.appspot.com/xansh.json?currency=USD|EUR|RUB|CNY|...

Registered as a subscribable provider AND exposes
``fetch_mongolbank_rub_rate()`` for formula calculations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from providers.base import BaseProvider, register_provider
from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = "https://monxansh.appspot.com/xansh.json"

# Ulaanbaatar timezone (UTC+8)
_UB_TZ = timezone(timedelta(hours=8))

_ALL_PAIRS: dict[str, str] = {
    "USD/MNT": "US Dollar ↔ Tögrög",
    "EUR/MNT": "Euro ↔ Tögrög",
    "RUB/MNT": "Рубль ↔ Tögrög",
    "CNY/MNT": "Yuan ↔ Tögrög",
    "GBP/MNT": "Pound ↔ Tögrög",
    "JPY/MNT": "Yen ↔ Tögrög",
    "KRW/MNT": "Won ↔ Tögrög",
}

# Map our pair names to the currency code used by the API
_PAIR_TO_CODE: dict[str, str] = {
    "USD/MNT": "USD",
    "EUR/MNT": "EUR",
    "RUB/MNT": "RUB",
    "CNY/MNT": "CNY",
    "GBP/MNT": "GBP",
    "JPY/MNT": "JPY",
    "KRW/MNT": "KRW",
}


def _fetch_from_api(currency_codes: str) -> list[dict]:
    """Fetch rates for the given pipe-separated currency codes."""
    resp = requests.get(_API_URL, params={"currency": currency_codes}, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if not body or not isinstance(body, list):
        return []
    return body


@register_provider
class MongolBankProvider(BaseProvider):
    NAME = "MongolBank"
    PAIRS = _ALL_PAIRS

    def fetch(self, symbol: str) -> dict[str, Any]:
        code = _PAIR_TO_CODE.get(symbol)
        if code is None:
            return {"lines": [f"MongolBank {symbol}: unsupported"]}

        try:
            rows = _fetch_from_api(code)
        except (requests.RequestException, ValueError) as exc:
            log.error("MongolBank fetch error: %s", exc)
            return {"lines": [f"MongolBank {symbol}: fetch error"]}

        for row in rows:
            if row.get("code") == code:
                rate = float(row["rate_float"])
                line = f"MongolBank {symbol}: `{rate:.2f}`"
                return {"lines": [line], "rate": rate}

        return {"lines": [f"MongolBank {symbol}: not found"]}


# ── Legacy helper used by formula calculations ──────────────────────────

def fetch_mongolbank_rub_rate() -> dict[str, Any]:
    """Fetch the MongolBank RUB rate (MNT per 1 RUB).

    Returns dict with 'rate' key on success, or 'error' key on failure.
    Uses the provider cache.
    """
    provider = MongolBankProvider()
    data = provider.get_rate("RUB/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "RUB rate not found"}
