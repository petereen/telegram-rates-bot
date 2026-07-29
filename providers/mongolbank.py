"""MongolBank exchange-rate provider.

Rates are obtained from the official MongolBank endpoint using the parsing
logic from btseee/mongolian-bank-exchange-rate.  This replaces the retired
``monxansh.appspot.com`` proxy and keeps the provider's public name and pair
symbols stable for existing watchlists and cached rates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from lxml import etree

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_API_URL = "https://www.mongolbank.mn/en/currency-rate-movement/data"

# Ulaanbaatar timezone (UTC+8)
_UB_TZ = timezone(timedelta(hours=8))

_ALL_PAIRS: dict[str, str] = {"RUB/MNT": "Рубль ↔ Tögrög"}

_PAIR_TO_CODE: dict[str, str] = {
    "RUB/MNT": "RUB",
}


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

    for row in payload.get("data", []):
        if not isinstance(row, dict) or row.get("RATE_DATE") != rate_date:
            continue
        return {
            code: rate
            for code, value in row.items()
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


def _fetch_rates() -> dict[str, float]:
    """Fetch all official MongolBank rates for the current Ulaanbaatar date."""
    response = requests.post(_API_URL, timeout=15)
    response.raise_for_status()
    rate_date = datetime.now(_UB_TZ).date().isoformat()
    try:
        return _parse_json(response.json(), rate_date)
    except ValueError:
        return _parse_xml(response.text)


@register_provider
class MongolBankProvider(BaseProvider):
    NAME = "MongolBank"
    PAIRS = _ALL_PAIRS

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
