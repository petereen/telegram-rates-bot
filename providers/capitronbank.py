"""CapitronBank non-cash exchange-rate provider.

Uses the CapitronBank API and the response mapping from
btseee/mongolian-bank-exchange-rate.  Only the requested MNT pairs are
exposed: USD, EUR, and Chinese yuan (RMB).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_API_URL = "https://www.capitronbank.mn/admin/en/wp-json/bank/rates/capitronbank"

_PAIR_TO_CODE = {
    "USD/MNT": "usd",
    "EUR/MNT": "eur",
    "RMB/MNT": "cny",
}


def _parse_rate(value: object) -> float | None:
    """Parse an API rate that may be a number or a formatted string."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _fetch_rates() -> dict[str, dict[str, float | None]]:
    """Return the API's non-cash buy and sell rates indexed by currency code."""
    response = requests.get(_API_URL, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return {}

    rates: dict[str, dict[str, float | None]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = str(item.get("currencyCode") or item.get("curcode") or "").lower()
        if not code:
            continue
        cash_buy = item.get("cashBuyRate") or item.get("buyrate")
        cash_sell = item.get("cashSellRate") or item.get("salerate")
        rates[code] = {
            "buy": _parse_rate(item.get("transferBuyRate") or cash_buy),
            "sell": _parse_rate(item.get("transferSellRate") or cash_sell),
        }
    return rates


@register_provider
class CapitronBankProvider(BaseProvider):
    NAME = "CapitronBank"
    PAIRS = {
        "USD/MNT": "US Dollar ↔ Tögrög",
        "EUR/MNT": "Euro ↔ Tögrög",
        "RMB/MNT": "Chinese Yuan (RMB) ↔ Tögrög",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        code = _PAIR_TO_CODE.get(symbol)
        if code is None:
            return {"lines": [f"CapitronBank {symbol}: unsupported"]}

        try:
            rate = _fetch_rates().get(code, {})
        except (requests.RequestException, ValueError) as exc:
            log.error("CapitronBank fetch error: %s", exc)
            return {"lines": [f"CapitronBank {symbol}: fetch error"]}

        buy = rate.get("buy")
        sell = rate.get("sell")
        if buy is None and sell is None:
            return {"lines": [f"CapitronBank {symbol}: not found"]}

        lines: list[str] = []
        if buy is not None:
            lines.append(f"CapitronBank {symbol} Non-cash Buy:  `{buy:.2f}`")
        if sell is not None:
            lines.append(f"CapitronBank {symbol} Non-cash Sell: `{sell:.2f}`")

        result: dict[str, Any] = {"lines": lines}
        if buy is not None:
            result["buy"] = buy
        if sell is not None:
            result["sell"] = sell
            result["rate"] = sell
        return result
