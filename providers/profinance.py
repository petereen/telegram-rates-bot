"""
providers.profinance – Profinance.ru forex-quotes scraper.

Source: https://www.profinance.ru/quote/show.asp

The page contains two tables we care about:
  1. "Курсы валют к рублю Forex"  → USD/RUB, EUR/RUB, CNY/RUB
  2. "Курсы валют Forex"          → EUR/USD, GBP/USD, USD/CHF, USD/JPY

Each row: <td class="iname"><a>PAIR</a></td> <td>BUY</td> <td>SELL</td> <td>TIME</td>
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_QUOTES_URL = "https://www.profinance.ru/quote/show.asp"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Canonical pair key → text that appears inside the <a> tag on the page
_PAIR_SLUG: dict[str, str] = {
    "USD/RUB": "USD/RUB",
    "EUR/RUB": "EUR/RUB",
    "CNY/RUB": "CNY/RUB",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "USD/CHF": "USD/CHF",
    "USD/JPY": "USD/JPY",
}


def _scrape_all_pairs() -> dict[str, dict[str, Any]]:
    """Fetch the quotes page once and return a dict of pair → {buy, sell, time}."""
    resp = requests.get(_QUOTES_URL, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results: dict[str, dict[str, Any]] = {}

    for tr in soup.find_all("tr", class_="curs"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        # First cell with class "iname" contains <a>PAIR</a>
        name_td = tds[0]
        if "iname" not in (name_td.get("class") or []):
            continue
        pair_text = name_td.get_text(strip=True).upper()
        if pair_text not in _PAIR_SLUG.values():
            continue
        try:
            buy = tds[1].get_text(strip=True)
            sell = tds[2].get_text(strip=True)
            time_ = tds[3].get_text(strip=True) if len(tds) > 3 else ""
            results[pair_text] = {
                "buy": float(buy),
                "sell": float(sell),
                "time": time_,
            }
        except (ValueError, IndexError):
            continue

    return results


@register_provider
class ProfinanceProvider(BaseProvider):
    NAME = "Profinance"
    PAIRS = {
        "USD/RUB": "Dollar / Ruble (Forex)",
        "EUR/RUB": "Euro / Ruble (Forex)",
        "CNY/RUB": "Yuan / Ruble (Forex)",
        "EUR/USD": "Euro / Dollar (Forex)",
        "GBP/USD": "Pound / Dollar (Forex)",
        "USD/CHF": "Dollar / Franc (Forex)",
        "USD/JPY": "Dollar / Yen (Forex)",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        if symbol not in _PAIR_SLUG:
            return {"lines": [f"Profinance {symbol}: unsupported"]}

        try:
            all_pairs = _scrape_all_pairs()
        except requests.RequestException as exc:
            log.error("Profinance fetch error: %s", exc)
            return {"lines": [f"Profinance {symbol}: fetch error"]}

        data = all_pairs.get(symbol)
        if data is None:
            return {"lines": [f"Profinance {symbol}: not found on page"]}

        buy = data["buy"]
        sell = data["sell"]
        lines = [
            f"Profinance {symbol} Buy:  {buy}",
            f"Profinance {symbol} Sell: {sell}",
        ]
        return {"lines": lines, "buy": buy, "sell": sell}
