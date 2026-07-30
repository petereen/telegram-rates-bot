"""TDB Bank (Худалдаа Хөгжлийн Банк) exchange-rate provider.

The former community API is no longer deployed.  Rates are now parsed from
TDB's live exchange-rates page using the static-table logic from
btseee/mongolian-bank-exchange-rate.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from lxml import html

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_TDB_URL = "https://www.tdbm.mn/en/exchange-rates"

_ALL_PAIRS: dict[str, str] = {
    "USD/MNT": "US Dollar ↔ Tögrög",
    "EUR/MNT": "Euro ↔ Tögrög",
    "RUB/MNT": "Рубль ↔ Tögrög",
    "CNY/MNT": "Yuan ↔ Tögrög",
    "GBP/MNT": "Pound ↔ Tögrög",
    "JPY/MNT": "Yen ↔ Tögrög",
}

_PAIR_TO_KEY = {
    "USD/MNT": "usd",
    "EUR/MNT": "eur",
    "RUB/MNT": "rub",
    "CNY/MNT": "cny",
    "GBP/MNT": "gbp",
    "JPY/MNT": "jpy",
}


def _parse_rate(value: str) -> float | None:
    try:
        rate = float(value.strip().replace(",", "").replace("\xa0", ""))
    except (AttributeError, ValueError):
        return None
    return rate if rate else None


def _parse_html_table(page: str) -> dict[str, dict[str, float | None]]:
    """Extract TDB's non-cash buy/sell columns from its current rate table."""
    root = html.fromstring(page)
    rows = root.xpath("//table[contains(@class, 'table-hover')]//tbody/tr")
    rates: dict[str, dict[str, float | None]] = {}
    for row in rows:
        cells = [cell.text_content().strip() for cell in row.xpath("./td")]
        if len(cells) < 8:
            continue
        code = cells[1].lower()
        if len(code) != 3 or not code.isalpha():
            continue
        rates[code] = {"buy": _parse_rate(cells[4]), "sell": _parse_rate(cells[5])}
    return rates


def _fetch_all_rates() -> dict[str, dict[str, float | None]]:
    response = requests.get(_TDB_URL, timeout=15)
    response.raise_for_status()
    return _parse_html_table(response.text)


@register_provider
class TDBProvider(BaseProvider):
    NAME = "TDB"
    CACHE_DAILY = True
    # Kept as a hidden legacy provider so existing formulas and subscriptions
    # continue to resolve. New watchlists use the upstream API's TDBM code.
    VISIBLE = False
    PAIRS = _ALL_PAIRS
    FORMULA_FIELDS = {symbol: ("buy", "sell", "rate") for symbol in PAIRS}

    def fetch(self, symbol: str) -> dict[str, Any]:
        code = _PAIR_TO_KEY.get(symbol)
        if code is None:
            return {"lines": [f"TDB {symbol}: unsupported"]}

        try:
            rate = _fetch_all_rates().get(code, {})
        except (requests.RequestException, ValueError) as exc:
            log.error("TDB Bank fetch error: %s", exc)
            return {"lines": [f"TDB {symbol}: fetch error"]}

        buy = rate.get("buy")
        sell = rate.get("sell")
        if buy is None and sell is None:
            return {"lines": [f"TDB {symbol}: not found"]}

        lines: list[str] = []
        if buy is not None:
            lines.append(f"TDB {symbol} Buy:  `{buy:.2f}`")
        if sell is not None:
            lines.append(f"TDB {symbol} Sell: `{sell:.2f}`")

        result: dict[str, Any] = {"lines": lines}
        if buy is not None:
            result["buy"] = buy
        if sell is not None:
            result["sell"] = sell
            result["rate"] = sell
        return result


def fetch_tdb_usd_noncash_sell() -> dict[str, Any]:
    """Fetch TDB's non-cash USD selling rate (MNT per 1 USD)."""
    data = TDBProvider().get_rate("USD/MNT")
    if "rate" in data:
        return {"rate": data["rate"]}
    return {"error": "USD noncash sell rate not found"}
