"""
providers.xe – XE website scraper.

Scrapes the public XE currency converter page at
https://www.xe.com/currencyconverter/convert/?From=XXX&To=YYY
No API key or billing required.
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
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Referer": "https://www.xe.com/",
    "DNT": "1",
}

XE_CONVERT_URL = "https://www.xe.com/currencyconverter/convert/"


@register_provider
class XEProvider(BaseProvider):
    NAME = "XE"
    PAIRS = {
        "USD/RUB": "US Dollar → Ruble",
        "EUR/RUB": "Euro → Ruble",
        "CNY/RUB": "Yuan → Ruble",
        "GBP/RUB": "Pound → Ruble",
        "CHF/RUB": "Franc → Ruble",
        "TRY/RUB": "Lira → Ruble",
        "KZT/RUB": "Tenge → Ruble",
        "AED/RUB": "Dirham → Ruble",
        "XAU/USD": "Gold oz → USD",
        "GBP/USD": "Pound → USD",
        "EUR/USD": "Euro → USD",
        "USD/CNY": "Dollar → Yuan",
        "USD/JPY": "Dollar → Yen",
        "USD/CHF": "Dollar → Franc",
        "USD/CAD": "Dollar → CAD",
        "USD/TRY": "Dollar → Lira",
        "USD/KZT": "Dollar → Tenge",
        "AUD/USD": "AUD → Dollar",
        "NZD/USD": "NZD → Dollar",
        "EUR/GBP": "Euro → Pound",
        "EUR/CNY": "Euro → Yuan",
        "GBP/CNY": "Pound → Yuan",
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        base, counter = symbol.split("/")

        params = {"From": base, "To": counter, "Amount": "1"}

        try:
            resp = requests.get(
                XE_CONVERT_URL,
                params=params,
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("XE scrape error: %s", exc)
            return {"lines": [f"XE {symbol}: fetch error"]}

        rate = self._parse_rate(resp.text)
        if rate is None:
            return {"lines": [f"XE {symbol}: parse error"]}

        line = f"XE {symbol}: {rate:.4f}"
        return {"lines": [line], "rate": rate}

    # ── HTML parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_rate(html: str) -> float | None:
        """Extract the conversion rate from the XE result page.

        XE renders the result in a <p> tag whose text reads something
        like "1 USD = 103.6178 RUB".  We also check for data attributes
        and embedded JSON/JS variables as fallback strategies.
        """
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1 – look for the prominent result text "1 XXX = NNN.NNN YYY"
        pattern = re.compile(r"1\s+\w{3}\s*=\s*([\d,]+\.?\d*)\s+\w{3}")
        for tag in soup.find_all(["p", "span", "div"]):
            text = tag.get_text(" ", strip=True)
            m = pattern.search(text)
            if m:
                return float(m.group(1).replace(",", ""))

        # Strategy 2 – search the raw HTML for a JS variable / JSON blob
        # XE sometimes embeds data like `"rate":103.6178` in a <script>.
        rate_match = re.search(r'"rate"\s*:\s*([\d.]+)', html)
        if rate_match:
            return float(rate_match.group(1))

        # Strategy 3 – look for data-amount attributes on result elements
        for el in soup.find_all(attrs={"data-amount": True}):
            try:
                return float(el["data-amount"])
            except (ValueError, KeyError):
                continue

        return None
