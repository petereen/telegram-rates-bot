"""
providers.grx – GRX crypto-to-RUB rate provider.

Fetches USDT/RUB, BTC/RUB and ETH/RUB rates from the CoinGecko free API.
The original Garantex exchange endpoints are no longer reachable.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

# CoinGecko free API — no key required.
_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

_COIN_MAP: dict[str, str] = {
    "USDT/RUB": "tether",
    "BTC/RUB":  "bitcoin",
    "ETH/RUB":  "ethereum",
    "SOL/RUB":  "solana",
    "XRP/RUB":  "ripple",
    "BNB/RUB":  "binancecoin",
    "DOGE/RUB": "dogecoin",
    "TON/RUB":  "the-open-network",
    "LTC/RUB":  "litecoin",
    "ADA/RUB":  "cardano",
    "DOT/RUB":  "polkadot",
    "AVAX/RUB": "avalanche-2",
    "TRX/RUB":  "tron",
    "LINK/RUB": "chainlink",
    "NOT/RUB":  "notcoin",
}


@register_provider
class GRXProvider(BaseProvider):
    NAME = "GRX"
    PAIRS = {
        "USDT/RUB": "Tether → Ruble",
        "BTC/RUB":  "Bitcoin → Ruble",
        "ETH/RUB":  "Ethereum → Ruble",
        "SOL/RUB":  "Solana → Ruble",
        "XRP/RUB":  "Ripple → Ruble",
        "BNB/RUB":  "BNB → Ruble",
        "DOGE/RUB": "Dogecoin → Ruble",
        "TON/RUB":  "Toncoin → Ruble",
        "LTC/RUB":  "Litecoin → Ruble",
        "ADA/RUB":  "Cardano → Ruble",
        "DOT/RUB":  "Polkadot → Ruble",
        "AVAX/RUB": "Avalanche → Ruble",
        "TRX/RUB":  "Tron → Ruble",
        "LINK/RUB": "Chainlink → Ruble",
        "NOT/RUB":  "Notcoin → Ruble",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        coin_id = _COIN_MAP.get(symbol)
        if coin_id is None:
            return {"lines": [f"GRX {symbol}: unsupported"]}

        try:
            resp = requests.get(
                _COINGECKO_URL,
                params={"ids": coin_id, "vs_currencies": "rub,usd"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("GRX fetch error: %s", exc)
            return {"lines": [f"GRX {symbol}: fetch error"]}

        coin_data = data.get(coin_id, {})
        rub_rate = coin_data.get("rub")
        usd_rate = coin_data.get("usd")

        if rub_rate is not None:
            lines = [f"GRX {symbol}: {rub_rate:,.2f}"]
            result: dict[str, Any] = {"lines": lines, "rate": rub_rate}
            if usd_rate is not None:
                result["usd"] = usd_rate
            return result

        return {"lines": [f"GRX {symbol}: no data"]}
