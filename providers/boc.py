"""
providers.boc – Bank of China CNY exchange rates.

Uses the free Open Exchange-Rate API (open.er-api.com) as a proxy for
BOC-style CNY rates — the original boc.cn website is unreachable outside
mainland China.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

# Free API — no key required, updates daily.
_API_URL = "https://open.er-api.com/v6/latest/CNY"

_SUPPORTED = {
    "USD", "EUR", "GBP", "HKD", "JPY", "CAD", "AUD",
    "CHF", "SGD", "KRW", "THB", "NZD", "RUB", "TRY", "MYR",
    "SEK", "NOK", "DKK", "INR", "AED",
}


@register_provider
class BOCProvider(BaseProvider):
    NAME = "BOC"
    PAIRS = {
        "USD": "US Dollar (CNY rate)",
        "EUR": "Euro (CNY rate)",
        "GBP": "British Pound (CNY rate)",
        "HKD": "Hong Kong Dollar (CNY rate)",
        "JPY": "Japanese Yen (CNY rate)",
        "CAD": "Canadian Dollar (CNY rate)",
        "AUD": "Australian Dollar (CNY rate)",
        "CHF": "Swiss Franc (CNY rate)",
        "SGD": "Singapore Dollar (CNY rate)",
        "KRW": "South Korean Won (CNY rate)",
        "THB": "Thai Baht (CNY rate)",
        "NZD": "New Zealand Dollar (CNY rate)",
        "RUB": "Russian Ruble (CNY rate)",
        "TRY": "Turkish Lira (CNY rate)",
        "MYR": "Malaysian Ringgit (CNY rate)",
        "SEK": "Swedish Krona (CNY rate)",
        "NOK": "Norwegian Krone (CNY rate)",
        "DKK": "Danish Krone (CNY rate)",
        "INR": "Indian Rupee (CNY rate)",
        "AED": "UAE Dirham (CNY rate)",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol not in _SUPPORTED:
            return {"lines": [f"BOC {symbol}: unsupported"]}

        try:
            resp = requests.get(_API_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("BOC fetch error: %s", exc)
            return {"lines": [f"BOC {symbol}: fetch error"]}

        rates = data.get("rates", {})
        rate = rates.get(symbol)
        if rate is None:
            return {"lines": [f"BOC {symbol}: rate not available"]}

        # rate = how much 1 CNY buys in <symbol>
        # Invert to get "how many CNY per 1 <symbol>"
        cny_per_unit = 1.0 / rate

        lines = [
            f"BOC {symbol}/CNY: {cny_per_unit:.4f}",
        ]
        return {"lines": lines, "rate": cny_per_unit}
