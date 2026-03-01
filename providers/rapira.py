"""
providers.rapira – Rapira.net exchange rate provider.

Rapira is a crypto exchange with a public REST API at api.rapira.net.
We use the unified rates endpoint:
  - /open/market/rates  → bid / ask / close for every traded pair
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_RATES_URL = "https://api.rapira.net/open/market/rates"

# Pairs shown as bid/ask (fiat gateway).
_BIDASK_PAIRS = {"USDT/RUB"}

_ALL_PAIRS: dict[str, str] = {
    "USDT/RUB": "Tether ↔ Рубль",
    "BTC/USDT":  "Bitcoin ↔ Tether",
    "ETH/USDT":  "Ethereum ↔ Tether",
    "SOL/USDT":  "Solana ↔ Tether",
    "XRP/USDT":  "Ripple ↔ Tether",
    "TON/USDT":  "Ton ↔ Tether",
    "BNB/USDT":  "BNB ↔ Tether",
    "DOGE/USDT": "Dogecoin ↔ Tether",
}


@register_provider
class RapiraProvider(BaseProvider):
    NAME = "Rapira"
    PAIRS = _ALL_PAIRS

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol not in _ALL_PAIRS:
            return {"lines": [f"Rapira {symbol}: unsupported"]}

        try:
            resp = requests.get(_RATES_URL, timeout=15)
            resp.raise_for_status()
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Rapira rates error: %s", exc)
            return {"lines": [f"Rapira {symbol}: fetch error"]}

        items = body.get("data", [])
        for item in items:
            if item.get("symbol") == symbol:
                return self._format_item(symbol, item)

        return {"lines": [f"Rapira {symbol}: not found"]}

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _format_item(symbol: str, item: dict) -> dict[str, Any]:
        bid = item.get("bidPrice", 0)
        ask = item.get("askPrice", 0)
        close = item.get("close", 0)
        scale = item.get("baseCoinScale", 2)

        if symbol in _BIDASK_PAIRS:
            lines = [
                f"Rapira {symbol} Buy:  `{bid:.{scale}f}`",
                f"Rapira {symbol} Sell: `{ask:.{scale}f}`",
            ]
            return {"lines": lines, "buy": bid, "sell": ask}

        lines = [f"Rapira {symbol}: `{close:.{scale}f}`"]
        return {"lines": lines, "rate": close, "bid": bid, "ask": ask}
