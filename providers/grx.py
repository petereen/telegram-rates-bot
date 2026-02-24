"""
providers.grx – Garantex (GRX) exchange scraper.

GRX provides a public REST API for USDT/RUB and BTC/RUB trading pairs.
API endpoint: https://garantex.org/api/v2/depth?market=usdtrub
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

GRX_API = "https://garantex.org/api/v2/depth"

_MARKET_MAP: dict[str, str] = {
    "USDT/RUB": "usdtrub",
    "BTC/RUB":  "btcrub",
    "ETH/RUB":  "ethrub",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


@register_provider
class GRXProvider(BaseProvider):
    NAME = "GRX"
    PAIRS = {
        "USDT/RUB": "Tether → Ruble",
        "BTC/RUB":  "Bitcoin → Ruble",
        "ETH/RUB":  "Ethereum → Ruble",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        market = _MARKET_MAP.get(symbol)
        if market is None:
            return {"lines": [f"GRX {symbol}: unsupported"]}

        try:
            resp = requests.get(
                GRX_API,
                params={"market": market},
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("GRX fetch error: %s", exc)
            return {"lines": [f"GRX {symbol}: fetch error"]}

        # depth response: {"asks": [{"price": "...", ...}], "bids": [...]}
        asks = data.get("asks", [])
        bids = data.get("bids", [])

        if asks and bids:
            best_ask = float(asks[0]["price"])
            best_bid = float(bids[0]["price"])
            mid = (best_ask + best_bid) / 2
            line = f"GRX {symbol}: {mid:.4f}"
            return {"lines": [line], "rate": mid, "bid": best_bid, "ask": best_ask}

        return {"lines": [f"GRX {symbol}: no depth data"]}
