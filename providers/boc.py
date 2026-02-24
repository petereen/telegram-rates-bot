"""
providers.boc – Bank of China exchange rate scraper.

Source: https://www.boc.cn/sourcedb/whpj/enindex.html
BOC publishes a table of foreign-exchange prices updated daily.
We extract the Buy / Sell columns for requested currencies.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

BOC_URL = "https://www.boc.cn/sourcedb/whpj/enindex.html"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.boc.cn/",
}

# BOC table has currencies by name; map our keys to the English name
# used in the first column of the table.
_CURRENCY_MAP: dict[str, str] = {
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "HKD": "HKD",
    "JPY": "JPY",
    "CAD": "CAD",
    "AUD": "AUD",
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
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol not in _CURRENCY_MAP:
            return {"lines": [f"BOC {symbol}: unsupported"]}

        try:
            resp = requests.get(BOC_URL, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("BOC fetch error: %s", exc)
            return {"lines": [f"BOC {symbol}: fetch error"]}

        soup = BeautifulSoup(resp.text, "lxml")
        target = _CURRENCY_MAP[symbol]

        # BOC table rows:  Currency | Buying Rate | Cash Buying | Selling | Cash Selling | …
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            currency_cell = tds[0].get_text(strip=True).upper()
            if target in currency_cell:
                try:
                    buy_rate = float(tds[1].get_text(strip=True)) / 100
                    sell_rate = float(tds[3].get_text(strip=True)) / 100
                except (ValueError, IndexError):
                    continue
                lines = [
                    f"BOC {symbol} Buy: {buy_rate:.4f}",
                    f"BOC {symbol} Sell: {sell_rate:.4f}",
                ]
                return {"lines": lines, "buy": buy_rate, "sell": sell_rate}

        return {"lines": [f"BOC {symbol}: not found in table"]}
