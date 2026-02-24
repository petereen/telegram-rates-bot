"""
providers.binance – Binance public REST API (Spot + P2P).

Spot:  GET https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT
P2P:   POST https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search
       (public, no auth required)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

SPOT_URL = "https://api.binance.com/api/v3/ticker/price"

P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

_SPOT_SYMBOLS: dict[str, str] = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "BNB/USDT": "BNBUSDT",
    "SOL/USDT": "SOLUSDT",
    "XRP/USDT": "XRPUSDT",
}

# P2P pairs: key = our symbol, value = (asset, fiat)
_P2P_PAIRS: dict[str, tuple[str, str]] = {
    "P2P USDT/RUB": ("USDT", "RUB"),
    "P2P USDT/CNY": ("USDT", "CNY"),
    "P2P BTC/RUB":  ("BTC",  "RUB"),
    "P2P CNY":      ("USDT", "CNY"),
}


@register_provider
class BinanceProvider(BaseProvider):
    NAME = "Binance"
    PAIRS = {
        **{k: f"Spot {k}" for k in _SPOT_SYMBOLS},
        "P2P USDT/RUB": "P2P USDT → RUB (median)",
        "P2P USDT/CNY": "P2P USDT → CNY (median)",
        "P2P BTC/RUB":  "P2P BTC → RUB (median)",
        "P2P CNY":      "P2P USDT → CNY (short)",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol in _SPOT_SYMBOLS:
            return self._fetch_spot(symbol)
        if symbol in _P2P_PAIRS:
            return self._fetch_p2p(symbol)
        return {"lines": [f"Binance {symbol}: unsupported"]}

    # ── Spot ───────────────────────────────────────────────────────────

    def _fetch_spot(self, symbol: str) -> dict[str, Any]:
        binance_sym = _SPOT_SYMBOLS[symbol]
        try:
            resp = requests.get(
                SPOT_URL, params={"symbol": binance_sym}, timeout=10
            )
            resp.raise_for_status()
            price = float(resp.json()["price"])
        except (requests.RequestException, KeyError, ValueError) as exc:
            log.error("Binance spot error: %s", exc)
            return {"lines": [f"Binance Spot {symbol}: fetch error"]}

        line = f"Binance Spot {symbol}: {price:.4f}"
        return {"lines": [line], "rate": price}

    # ── P2P ────────────────────────────────────────────────────────────

    def _fetch_p2p(self, symbol: str) -> dict[str, Any]:
        asset, fiat = _P2P_PAIRS[symbol]

        # The P2P endpoint accepts a POST JSON body.
        payload = {
            "fiat": fiat,
            "page": 1,
            "rows": 10,
            "tradeType": "BUY",
            "asset": asset,
            "countries": [],
            "proMerchantAds": False,
            "shieldMerchantAds": False,
            "publisherType": None,
            "payTypes": [],
            "classifies": ["mass", "profession", "fiat_trade"],
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        try:
            resp = requests.post(
                P2P_URL, json=payload, headers=headers, timeout=15
            )
            resp.raise_for_status()
            ads = resp.json().get("data", [])
        except (requests.RequestException, ValueError) as exc:
            log.error("Binance P2P error: %s", exc)
            return {"lines": [f"Binance P2P {asset}/{fiat}: fetch error"]}

        if not ads:
            return {"lines": [f"Binance P2P {asset}/{fiat}: no ads"]}

        prices = [float(ad["adv"]["price"]) for ad in ads]
        median = sorted(prices)[len(prices) // 2]

        label = symbol.replace("P2P ", "")
        line = f"Binance P2P {label}: {median:.4f}"
        return {"lines": [line], "rate": median}
