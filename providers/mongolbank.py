"""MongolBank exchange-rate provider.

Rates are obtained from the official MongolBank endpoint using the parsing
logic from btseee/mongolian-bank-exchange-rate.  This replaces the retired
``monxansh.appspot.com`` proxy and keeps the provider's public name and pair
symbols stable for existing watchlists and cached rates.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from lxml import etree

from providers.base import BaseProvider, register_provider
from db.supabase_client import get_daily_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = "https://www.mongolbank.mn/en/currency-rate-movement/data"
_FALLBACK_API_URL = "https://monxansh.appspot.com/xansh.json"

# Ulaanbaatar timezone (UTC+8)
_UB_TZ = timezone(timedelta(hours=8))

_ALL_PAIRS: dict[str, str] = {"RUB/MNT": "Рубль ↔ Tögrög"}

_PAIR_TO_CODE: dict[str, str] = {
    "RUB/MNT": "RUB",
}

# /rates fetches the watchlist and calculator inputs concurrently.  This lock
# prevents those simultaneous calls from starting duplicate daily refreshes.
_daily_refresh_lock = threading.Lock()


def _parse_rate(value: object) -> float | None:
    """Convert the API's numeric strings, including comma-separated values."""
    if value is None:
        return None
    try:
        rate = float(str(value).strip().replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    return rate if rate else None


def _parse_json(payload: object, rate_date: str) -> dict[str, float]:
    """Extract ISO currency rates from the official endpoint's JSON response."""
    if not isinstance(payload, dict):
        return {}

    rows = [row for row in payload.get("data", []) if isinstance(row, dict)]
    for row in rows:
        if row.get("RATE_DATE") != rate_date:
            continue
        return {
            code: rate
            for code, value in row.items()
            if len(code) == 3 and code.isalpha() and (rate := _parse_rate(value)) is not None
        }
    # The official endpoint does not publish a new value on weekends and bank
    # holidays.  Use its latest available rate instead of treating that as a
    # failed fetch.
    if rows:
        latest = max(rows, key=lambda row: str(row.get("RATE_DATE", "")))
        return {
            code: rate
            for code, value in latest.items()
            if len(code) == 3 and code.isalpha() and (rate := _parse_rate(value)) is not None
        }
    return {}


def _parse_xml(payload: str) -> dict[str, float]:
    """Support the endpoint's legacy XML response as in the upstream crawler."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(payload.encode("utf-8"), parser)
    rates: dict[str, float] = {}
    for row in root.xpath("//Ccy"):
        code = row.findtext("CcyNm_EN")
        rate = _parse_rate(row.findtext("Rate"))
        if code and rate is not None:
            rates[code.upper()] = rate
    return rates


def _fetch_official_rates() -> dict[str, float]:
    """Fetch rates from the official MongolBank endpoint."""
    response = requests.post(_API_URL, timeout=(5, 10))
    response.raise_for_status()
    rate_date = datetime.now(_UB_TZ).date().isoformat()
    try:
        return _parse_json(response.json(), rate_date)
    except ValueError:
        return _parse_xml(response.text)


def _fetch_fallback_rates() -> dict[str, float]:
    """Fetch the official-rate proxy when MongolBank's site is unavailable."""
    response = requests.get(_FALLBACK_API_URL, params={"currency": "RUB"}, timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return {}
    for row in payload:
        if isinstance(row, dict) and row.get("code") == "RUB":
            rate = _parse_rate(row.get("rate_float"))
            return {"RUB": rate} if rate is not None else {}
    return {}


def _fetch_rates() -> dict[str, float]:
    """Fetch official rates, with a proxy fallback for network timeouts."""
    try:
        rates = _fetch_official_rates()
        if rates:
            return rates
    except (requests.RequestException, ValueError, etree.XMLSyntaxError) as exc:
        log.warning("MongolBank official endpoint failed; using fallback: %s", exc)
    return _fetch_fallback_rates()


@register_provider
class MongolBankProvider(BaseProvider):
    NAME = "MongolBank"
    PAIRS = _ALL_PAIRS
    FORMULA_FIELDS = {symbol: ("rate",) for symbol in PAIRS}

    def get_rate(self, symbol: str) -> dict[str, Any]:
        """Return today's stored rate, refreshing it at most once per process.

        Supabase is the durable daily store, so this stays effective across
        bot restarts as well as across repeated /rates calls.
        """
        try:
            cached = get_daily_cached_rate(self.NAME, symbol)
            if cached is not None:
                return cached
        except Exception as exc:
            log.warning("MongolBank daily cache read error: %s", exc)

        with _daily_refresh_lock:
            try:
                cached = get_daily_cached_rate(self.NAME, symbol)
                if cached is not None:
                    return cached
            except Exception as exc:
                log.warning("MongolBank daily cache recheck error: %s", exc)

            data = self.fetch(symbol)
            # Do not turn a transient fetch error into an all-day cached result.
            if "rate" in data:
                try:
                    set_cached_rate(self.NAME, symbol, data)
                except Exception as exc:
                    log.warning("MongolBank daily cache write error: %s", exc)
            return data

    def fetch(self, symbol: str) -> dict[str, Any]:
        code = _PAIR_TO_CODE.get(symbol)
        if code is None:
            return {"lines": [f"MongolBank {symbol}: unsupported"]}

        try:
            rate = _fetch_rates().get(code)
        except (requests.RequestException, ValueError, etree.XMLSyntaxError) as exc:
            log.error("MongolBank fetch error: %s", exc)
            return {"lines": [f"MongolBank {symbol}: fetch error"]}

        if rate is None:
            return {"lines": [f"MongolBank {symbol}: not found"]}

        return {"lines": [f"MongolBank {symbol}: `{rate:.2f}`"], "rate": rate}


def fetch_mongolbank_rub_rate() -> dict[str, Any]:
    """Fetch the MongolBank RUB rate (MNT per 1 RUB) using the provider cache."""
    data = MongolBankProvider().get_rate("RUB/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "RUB rate not found"}


def run_daily_refresh() -> None:
    """Pre-warm the daily Supabase snapshot at startup and every 09:05 UB time."""
    provider = MongolBankProvider()
    while True:
        try:
            data = provider.get_rate("RUB/MNT")
            if "rate" in data:
                log.info("MongolBank daily snapshot is ready")
            else:
                log.warning("MongolBank daily snapshot could not be refreshed")
        except Exception as exc:
            log.error("MongolBank daily refresh error: %s", exc)

        now = datetime.now(_UB_TZ)
        next_refresh = now.replace(hour=9, minute=5, second=0, microsecond=0)
        if next_refresh <= now:
            next_refresh += timedelta(days=1)
        time.sleep((next_refresh - now).total_seconds())
