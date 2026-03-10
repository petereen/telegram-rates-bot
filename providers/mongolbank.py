"""
providers.mongolbank – Mongol Bank (central bank) exchange rate fetcher.

Uses the official MongolBank API endpoint:
  POST https://www.mongolbank.mn/mn/currency-rates/data
  Body: {"startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD"}

Returns the official MongolBank RUB/MNT rate for today.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = "https://www.mongolbank.mn/mn/currency-rates/data"

_PROVIDER_NAME = "MongolBank"

# Ulaanbaatar timezone (UTC+8)
_UB_TZ = timezone(timedelta(hours=8))


def fetch_mongolbank_rub_rate() -> dict[str, Any]:
    """Fetch the MongolBank RUB rate (MNT per 1 RUB).

    Returns dict with 'rate' key on success, or 'error' key on failure.
    Uses the shared cache (TTL from config).
    """
    cached = get_cached_rate(_PROVIDER_NAME, "RUB")
    if cached is not None:
        log.debug("Cache hit  %s/RUB", _PROVIDER_NAME)
        return cached

    log.info("Fetching   %s/RUB", _PROVIDER_NAME)
    today = datetime.now(_UB_TZ).strftime("%Y-%m-%d")
    try:
        resp = requests.post(
            _API_URL,
            json={"startDate": today, "endDate": today},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("MongolBank fetch error: %s", exc)
        return {"error": "fetch error"}

    if not body.get("success") or not body.get("data"):
        return {"error": "unexpected response"}

    row = body["data"][0]
    rub_str = row.get("RUB")
    if rub_str is None:
        return {"error": "RUB rate not found"}

    # Value comes as "45.22" or "3,565.99" (with commas)
    rate = float(rub_str.replace(",", ""))
    result = {"rate": rate, "date": row.get("RATE_DATE", today)}
    set_cached_rate(_PROVIDER_NAME, "RUB", result)
    return result
