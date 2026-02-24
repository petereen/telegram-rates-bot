"""
providers.profinance – Profinance.ru scraper.

Profinance publishes near-real-time Forex quotes on currency pages.
We scrape the buy/sell spread from the HTML table.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Maps our symbol to the profinance page slug and regex for buy/sell extraction
_PAIR_CONFIG: dict[str, dict[str, str]] = {
    "USD/RUB": {
        "url": "https://www.profinance.ru/currency_usd.asp",
        "label": "USD/RUB",
    },
    "EUR/RUB": {
        "url": "https://www.profinance.ru/currency_eur.asp",
        "label": "EUR/RUB",
    },
    "CNY/RUB": {
        "url": "https://www.profinance.ru/currency_cny.asp",
        "label": "CNY/RUB",
    },
}


@register_provider
class ProfinanceProvider(BaseProvider):
    NAME = "Profinance"
    PAIRS = {
        "USD/RUB": "Dollar / Ruble bid-ask",
        "EUR/RUB": "Euro / Ruble bid-ask",
        "CNY/RUB": "Yuan / Ruble bid-ask",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        cfg = _PAIR_CONFIG.get(symbol)
        if cfg is None:
            return {"lines": [f"Profinance {symbol}: unsupported"]}

        try:
            resp = requests.get(cfg["url"], headers=_HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("Profinance fetch error: %s", exc)
            return {"lines": [f"Profinance {symbol}: fetch error"]}

        soup = BeautifulSoup(resp.text, "lxml")

        buy: str | None = None
        sell: str | None = None

        # Strategy 1: look for table cells with bid/ask pattern
        # Profinance pages typically show a table with Bid and Ask values
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            # Match decimal values in table cells near bid/ask labels
            if re.match(r"^\d+\.\d{2,6}$", text):
                if buy is None:
                    buy = text
                elif sell is None:
                    sell = text
                    break

        # Strategy 2: try extracting from script/JSON embedded on page
        if buy is None or sell is None:
            all_text = soup.get_text()
            numbers = re.findall(r"\d+\.\d{4}", all_text)
            if len(numbers) >= 2:
                buy, sell = numbers[0], numbers[1]

        if buy and sell:
            lines = [
                f"Profinance {cfg['label']} Buy: {buy}",
                f"Profinance {cfg['label']} Sell: {sell}",
            ]
            return {
                "lines": lines,
                "buy": float(buy),
                "sell": float(sell),
            }

        return {"lines": [f"Profinance {symbol}: parse error"]}
