"""
providers.cbr – Central Bank of Russia daily XML feed.

Source: https://www.cbr.ru/scripts/XML_daily.asp
Returns official exchange rates against the Russian ruble.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree

import requests

from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"

# Map our internal symbol keys to CBR currency codes
_CBR_CODE_MAP: dict[str, str] = {
    "USD/RUB": "USD",
    "EUR/RUB": "EUR",
    "CNY/RUB": "CNY",
    "GBP/RUB": "GBP",
    "JPY/RUB": "JPY",
    "TRY/RUB": "TRY",
    "KZT/RUB": "KZT",
}


@register_provider
class CBRProvider(BaseProvider):
    NAME = "CBR"
    PAIRS = {
        "USD/RUB": "US Dollar → Ruble",
        "EUR/RUB": "Euro → Ruble",
        "CNY/RUB": "Yuan → Ruble",
        "GBP/RUB": "Pound → Ruble",
        "JPY/RUB": "Yen → Ruble",
        "TRY/RUB": "Lira → Ruble",
        "KZT/RUB": "Tenge → Ruble",
    }

    # We fetch the entire XML once and parse all currencies.
    # To avoid redundant HTTP calls when the user has several CBR pairs,
    # the cache layer in BaseProvider handles dedup per-symbol.

    def fetch(self, symbol: str) -> dict[str, Any]:
        code = _CBR_CODE_MAP.get(symbol)
        if code is None:
            return {"lines": [f"CBR {symbol}: unsupported"]}

        resp = requests.get(CBR_URL, timeout=15)
        resp.raise_for_status()

        root = ElementTree.fromstring(resp.content)
        for valute in root.iter("Valute"):
            char_code = valute.findtext("CharCode", "")
            if char_code == code:
                nominal = int(valute.findtext("Nominal", "1"))
                value_str = valute.findtext("Value", "0").replace(",", ".")
                value = float(value_str) / nominal
                line = f"CBR {symbol}: {value:.4f}"
                return {"lines": [line], "rate": value}

        return {"lines": [f"CBR {symbol}: not found"]}
