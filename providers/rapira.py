"""
providers.rapira – Rapira.net exchange rate provider.

Rapira is a crypto exchange with a public REST API at api.rapira.net.
We use two endpoints:
  - /market/exchange-plate-mini?symbol=USDT/RUB  → orderbook (buy/sell)
  - /market/symbol-thumb                         → ticker summary for all pairs
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_API_BASE = "https://api.rapira.net"
_ORDERBOOK_URL = f"{_API_BASE}/market/exchange-plate-mini"
_TICKER_URL = f"{_API_BASE}/market/symbol-thumb"

# Pairs that have an orderbook (RUB pairs) use bid/ask.
# Other spot pairs use the ticker summary (close price).
_ORDERBOOK_PAIRS = {"USDT/RUB"}

_ALL_PAIRS: dict[str, str] = {
    "USDT/RUB": "Tether ↔ Ruble (buy/sell)",
}


@register_provider
class RapiraProvider(BaseProvider):
    NAME = "Rapira"
    PAIRS = _ALL_PAIRS

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol not in _ALL_PAIRS:
            return {"lines": [f"Rapira {symbol}: unsupported"]}

        if symbol in _ORDERBOOK_PAIRS:
            return self._fetch_orderbook(symbol)
        return self._fetch_ticker(symbol)

    # ── Orderbook (buy / sell) ─────────────────────────────────────────

    def _fetch_orderbook(self, symbol: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                _ORDERBOOK_URL,
                params={"symbol": symbol},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Rapira orderbook error: %s", exc)
            return {"lines": [f"Rapira {symbol}: fetch error"]}

        bid_items = data.get("bid", {}).get("items", [])
        ask_items = data.get("ask", {}).get("items", [])

        if not bid_items or not ask_items:
            return {"lines": [f"Rapira {symbol}: no orderbook data"]}

        best_bid = bid_items[0]["price"]   # buy price
        best_ask = ask_items[0]["price"]   # sell price

        lines = [
            f"Rapira {symbol} Buy:  {best_bid:.2f}",
            f"Rapira {symbol} Sell: {best_ask:.2f}",
        ]
        return {
            "lines": lines,
            "buy": best_bid,
            "sell": best_ask,
        }

    # ── Ticker (last price) ───────────────────────────────────────────

    def _fetch_ticker(self, symbol: str) -> dict[str, Any]:
        try:
            resp = requests.get(_TICKER_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Rapira ticker error: %s", exc)
            return {"lines": [f"Rapira {symbol}: fetch error"]}

        for item in data:
            if item.get("symbol") == symbol:
                close = item["close"]
                line = f"Rapira {symbol}: {close:.4f}"
                return {"lines": [line], "rate": close}

        return {"lines": [f"Rapira {symbol}: not found"]}
