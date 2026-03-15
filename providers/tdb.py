"""
providers.tdb – TDB Bank (Худалдаа Хөгжлийн Банк) exchange rate provider.

Uses the community API at:
  https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com/rates/bank/TDBM

Registered as a subscribable provider AND exposes
``fetch_tdb_usd_noncash_sell()`` for formula calculations.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, register_provider
from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = (
    "https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com"
    "/rates/bank/TDBM"
)

_ALL_PAIRS: dict[str, str] = {
    "USD/MNT": "US Dollar ↔ Tögrög",
    "EUR/MNT": "Euro ↔ Tögrög",
    "RUB/MNT": "Рубль ↔ Tögrög",
    "CNY/MNT": "Yuan ↔ Tögrög",
    "GBP/MNT": "Pound ↔ Tögrög",
    "JPY/MNT": "Yen ↔ Tögrög",
}

# Map our pair names to the key used in the API response ("rates" object)
_PAIR_TO_KEY: dict[str, str] = {
    "USD/MNT": "usd",
    "EUR/MNT": "eur",
    "RUB/MNT": "rub",
    "CNY/MNT": "cny",
    "GBP/MNT": "gbp",
    "JPY/MNT": "jpy",
}


def _fetch_all_rates() -> dict[str, Any]:
    """Fetch the full TDB rates payload (latest entry)."""
    resp = requests.get(_API_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list):
        return {}
    return data[0]


@register_provider
class TDBProvider(BaseProvider):
    NAME = "TDB"
    PAIRS = _ALL_PAIRS

    def fetch(self, symbol: str) -> dict[str, Any]:
        key = _PAIR_TO_KEY.get(symbol)
        if key is None:
            return {"lines": [f"TDB {symbol}: unsupported"]}

        try:
            latest = _fetch_all_rates()
        except (requests.RequestException, ValueError) as exc:
            log.error("TDB Bank fetch error: %s", exc)
            return {"lines": [f"TDB {symbol}: fetch error"]}

        rates = latest.get("rates", {})
        ccy = rates.get(key, {})

        noncash = ccy.get("noncash", {})
        cash = ccy.get("cash", {})

        nc_buy = noncash.get("buy")
        nc_sell = noncash.get("sell")
        c_buy = cash.get("buy")
        c_sell = cash.get("sell")

        lines: list[str] = []
        if nc_buy is not None and nc_sell is not None:
            lines.append(f"TDB {symbol} Бэлэн бус Buy:  `{float(nc_buy):.2f}`")
            lines.append(f"TDB {symbol} Бэлэн бус Sell: `{float(nc_sell):.2f}`")
        if c_buy is not None and c_sell is not None:
            lines.append(f"TDB {symbol} Бэлэн Buy:  `{float(c_buy):.2f}`")
            lines.append(f"TDB {symbol} Бэлэн Sell: `{float(c_sell):.2f}`")

        if not lines:
            return {"lines": [f"TDB {symbol}: not found"]}

        result: dict[str, Any] = {"lines": lines}
        if nc_sell is not None:
            result["rate"] = float(nc_sell)
        return result


# ── Legacy helper used by formula calculations ──────────────────────────

def fetch_tdb_usd_noncash_sell() -> dict[str, Any]:
    """Fetch the TDB Bank non-cash USD selling rate (MNT per 1 USD).

    Returns dict with 'rate' key on success, or 'error' key on failure.
    Uses the provider cache.
    """
    provider = TDBProvider()
    data = provider.get_rate("USD/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "USD noncash sell rate not found"}
