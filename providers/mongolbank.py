"""
providers.mongolbank – Mongol Bank (central bank) exchange rate fetcher.

Uses the monxansh.appspot.com proxy for the MongolBank official rates:
  GET https://monxansh.appspot.com/xansh.json?currency=RUB

Returns the official MongolBank RUB/MNT rate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = "https://monxansh.appspot.com/xansh.json"

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
    try:
        resp = requests.get(
            _API_URL,
            params={"currency": "RUB"},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("MongolBank fetch error: %s", exc)
        return {"error": "fetch error"}

    if not body or not isinstance(body, list):
        return {"error": "unexpected response"}

    for row in body:
        if row.get("code") == "RUB":
            rate = float(row["rate_float"])
            date = row.get("rate_date", datetime.now(_UB_TZ).strftime("%Y-%m-%d"))
            result = {"rate": rate, "date": date}
            set_cached_rate(_PROVIDER_NAME, "RUB", result)
            return result

    return {"error": "RUB rate not found"}
