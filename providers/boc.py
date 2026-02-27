"""
providers.boc – Bank of China exchange rate scraper.

Source: https://www.bankofchina.com/sourcedb/whpj/enindex_1619.html
BOC publishes a table of foreign-exchange prices updated daily.
We extract the Buying Rate / Selling Rate columns for requested currencies.

Table columns:
  Currency Name | Buying Rate | Cash Buying | Selling Rate | Cash Selling | Middle Rate | Pub Time

Rates in the table are per 100 units of foreign currency in CNY.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

BOC_URL = "https://www.bankofchina.com/sourcedb/whpj/enindex_1619.html"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Map our symbol keys to the text that appears in the first column of the
# BOC table.  BOC uses English currency names or ISO codes.
_CURRENCY_MATCH: dict[str, list[str]] = {
    "USD": ["USD", "US DOLLAR"],
    "EUR": ["EUR", "EURO"],
    "GBP": ["GBP", "POUND", "STERLING"],
    "HKD": ["HKD", "HONG KONG"],
    "JPY": ["JPY", "YEN", "JAPANESE"],
    "CAD": ["CAD", "CANADIAN"],
    "AUD": ["AUD", "AUSTRALIAN"],
    "CHF": ["CHF", "SWISS"],
    "SGD": ["SGD", "SINGAPORE"],
    "KRW": ["KRW", "KOREAN"],
    "THB": ["THB", "THAI"],
    "NZD": ["NZD", "NEW ZEALAND"],
    "RUB": ["RUB", "RUSSIAN", "RUBLE"],
    "TRY": ["TRY", "TURKISH", "LIRA"],
    "MYR": ["MYR", "MALAYSIAN", "RINGGIT"],
    "SEK": ["SEK", "SWEDISH"],
    "NOK": ["NOK", "NORWEGIAN"],
    "DKK": ["DKK", "DANISH"],
    "INR": ["INR", "INDIAN", "RUPEE"],
    "AED": ["AED", "UAE", "DIRHAM"],
}


def _matches_currency(cell_text: str, symbol: str) -> bool:
    """Return True if the table cell text matches the given currency symbol."""
    upper = cell_text.upper()
    for keyword in _CURRENCY_MATCH.get(symbol, [symbol]):
        if keyword in upper:
            return True
    return False


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
        if symbol not in _CURRENCY_MATCH:
            return {"lines": [f"BOC {symbol}: unsupported"]}

        try:
            resp = requests.get(BOC_URL, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("BOC fetch error: %s", exc)
            return {"lines": [f"BOC {symbol}: fetch error"]}

        soup = BeautifulSoup(resp.text, "lxml")

        # BOC table rows:
        #   [0] Currency | [1] Buying Rate | [2] Cash Buying |
        #   [3] Selling Rate | [4] Cash Selling | [5] Middle Rate | [6] Pub Time
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            cell_text = tds[0].get_text(strip=True)
            if not _matches_currency(cell_text, symbol):
                continue
            try:
                buy_raw = tds[1].get_text(strip=True)
                sell_raw = tds[3].get_text(strip=True)
                if not buy_raw or not sell_raw:
                    continue
                # Rates are per 100 units → divide by 100
                buy_rate = float(buy_raw) / 100
                sell_rate = float(sell_raw) / 100
            except (ValueError, IndexError):
                continue

            lines = [
                f"BOC {symbol}/CNY Buy:  {buy_rate:.4f}",
                f"BOC {symbol}/CNY Sell: {sell_rate:.4f}",
            ]
            return {"lines": lines, "buy": buy_rate, "sell": sell_rate}

        return {"lines": [f"BOC {symbol}: not found in table"]}
