"""MongolBank exchange-rate provider.

Rates are obtained from the official MongolBank endpoint using the parsing
logic from btseee/mongolian-bank-exchange-rate.  This replaces the retired
``monxansh.appspot.com`` proxy and keeps the provider's public name and pair
symbols stable for existing watchlists and cached rates.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from lxml import etree

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_API_URL = "https://www.mongolbank.mn/en/currency-rate-movement/data"
_FALLBACK_API_URL = "https://monxansh.appspot.com/xansh.json"

# Ulaanbaatar timezone (UTC+8)
_UB_TZ = timezone(timedelta(hours=8))

_ALL_PAIRS: dict[str, str] = {
    "USD/MNT": "US Dollar ↔ Tögrög",
    "CNY/MNT": "Chinese Yuan ↔ Tögrög",
    "JPY/MNT": "Japanese Yen ↔ Tögrög",
    "RUB/MNT": "Рубль ↔ Tögrög",
}

_PAIR_TO_CODE: dict[str, str] = {
    "USD/MNT": "USD",
    "CNY/MNT": "CNY",
    "JPY/MNT": "JPY",
    "RUB/MNT": "RUB",
}

_MNT_PAIR_RE = re.compile(r"^[A-Z]{3}/MNT$")

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
    rate_date = datetime.now(_UB_TZ).date().isoformat()
    response = requests.post(
        _API_URL,
        json={"startDate": "2001-01-01", "endDate": rate_date},
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=(5, 10),
    )
    response.raise_for_status()
    try:
        return _parse_json(response.json(), rate_date)
    except ValueError:
        return _parse_xml(response.text)


def _fetch_fallback_rates() -> dict[str, float]:
    """Fetch the official-rate proxy when MongolBank's site is unavailable."""
    rates: dict[str, float] = {}
    for code in ("USD", "CNY", "JPY", "RUB"):
        response = requests.get(_FALLBACK_API_URL, params={"currency": code}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict) or row.get("code") != code:
                continue
            rate = _parse_rate(row.get("rate_float"))
            if rate is not None:
                rates[code] = rate
            break
    return rates


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
    CACHE_DAILY = True
    PAIRS = _ALL_PAIRS
    FORMULA_FIELDS = {symbol: ("rate",) for symbol in PAIRS}

    def supports_pair(self, symbol: str) -> bool:
        """The official feed can provide every published ISO currency/MNT rate."""
        return bool(_MNT_PAIR_RE.fullmatch(symbol))

    def formula_fields(self, symbol: str) -> tuple[str, ...]:
        return ("rate",) if self.supports_pair(symbol) else ()

    @staticmethod
    def _rate_data(symbol: str, rate: float | None) -> dict[str, Any]:
        if rate is None:
            return {"lines": [f"MongolBank {symbol}: not found"]}
        return {"lines": [f"MongolBank {symbol}: `{rate:.2f}`"], "rate": rate}

    def fetch_all(self) -> dict[str, dict[str, Any]]:
        """Fetch every currency/MNT rate currently published by MongolBank."""
        try:
            rates = _fetch_rates()
        except (requests.RequestException, ValueError, etree.XMLSyntaxError) as exc:
            log.error("MongolBank all-rates fetch error: %s", exc)
            return {}
        return {
            f"{code}/MNT": self._rate_data(f"{code}/MNT", rate)
            for code, rate in rates.items()
            if len(code) == 3 and code.isalpha() and code.upper() != "MNT"
        }

    def fetch_many(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        all_rates = self.fetch_all()
        return {
            symbol: all_rates.get(symbol, {"lines": [f"MongolBank {symbol}: not found"]})
            for symbol in symbols
        }

    def fetch(self, symbol: str) -> dict[str, Any]:
        if not self.supports_pair(symbol):
            return {"lines": [f"MongolBank {symbol}: unsupported"]}
        code = symbol.split("/", 1)[0]

        try:
            rate = _fetch_rates().get(code)
        except (requests.RequestException, ValueError, etree.XMLSyntaxError) as exc:
            log.error("MongolBank fetch error: %s", exc)
            return {"lines": [f"MongolBank {symbol}: fetch error"]}

        return self._rate_data(symbol, rate)


def fetch_mongolbank_rub_rate() -> dict[str, Any]:
    """Fetch the MongolBank RUB rate (MNT per 1 RUB) using the provider cache."""
    data = MongolBankProvider().get_rate("RUB/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "RUB rate not found"}


def fetch_mongolbank_usd_rate() -> dict[str, Any]:
    """Fetch the MongolBank USD rate (MNT per 1 USD) using the provider cache."""
    data = MongolBankProvider().get_rate("USD/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "USD rate not found"}


def run_daily_refresh() -> None:
    """Pre-warm the daily Supabase snapshot at startup and every 09:05 UB time."""
    provider = MongolBankProvider()
    while True:
        try:
            results = {
                symbol: provider.get_rate(symbol)
                for symbol in provider.PAIRS
            }
            if all("rate" in data for data in results.values()):
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
