"""Mongolian bank providers backed by the normalized community REST API.

The upstream service stores every bank's rates in this shape::

    {"rates": {"usd": {
        "cash": {"buy": 3420.5, "sell": 3450},
        "noncash": {"buy": 3415, "sell": 3455}
    }}}

One provider class is registered for each upstream bank code. Fetching a
watchlist pair requests only that bank's latest stored snapshot.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from config import MONGOLIAN_BANK_API_URL
from providers.base import BaseProvider, register_provider

log = logging.getLogger(__name__)

_PAIR_LABELS: dict[str, str] = {
    "USD/MNT": "US Dollar ↔ Tögrög",
    "EUR/MNT": "Euro ↔ Tögrög",
    "CNY/MNT": "Chinese Yuan ↔ Tögrög",
    "RUB/MNT": "Russian Ruble ↔ Tögrög",
    "JPY/MNT": "Japanese Yen ↔ Tögrög",
    "GBP/MNT": "British Pound ↔ Tögrög",
    "KRW/MNT": "Korean Won ↔ Tögrög",
}

_BANKS: tuple[tuple[str, str], ...] = (
    ("KhanBank", "Хаан Банк"),
    ("GolomtBank", "Голомт Банк"),
    ("XacBank", "Хас Банк"),
    ("ArigBank", "Ариг Банк"),
    ("StateBank", "Төрийн Банк"),
    ("MongolBank", "Монгол Банк"),
    ("CapitronBank", "Капитрон Банк"),
    ("NaimanSharga", "Найман Шарга"),
    ("SendMN", "SendMN"),
    ("TDBM", "ХХБ"),
    ("BogdBank", "Богд Банк"),
    ("CKBank", "Чингис Хаан Банк"),
    ("NIBank", "ҮХОБ"),
    ("TransBank", "Транс Банк"),
    ("MBank", "М Банк"),
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _latest_bank_payload(bank_code: str) -> dict[str, Any]:
    response = requests.get(
        f"{MONGOLIAN_BANK_API_URL}/rates/bank/{bank_code}",
        params={"skip": 0, "limit": 1},
        timeout=(5, 20),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError("empty bank response")
    return payload[0]


class MongolianBankProvider(BaseProvider):
    """Shared implementation; concrete subclasses only supply bank metadata."""

    PAIRS = _PAIR_LABELS
    FORMULA_FIELDS = {
        symbol: (
            "cash_buy",
            "cash_sell",
            "noncash_buy",
            "noncash_sell",
            "buy",
            "sell",
            "rate",
        )
        for symbol in PAIRS
    }

    def fetch(self, symbol: str) -> dict[str, Any]:
        source_code = symbol.split("/", 1)[0].lower()
        if symbol not in self.PAIRS:
            return {"lines": [f"{self.NAME} {symbol}: unsupported"]}

        try:
            payload = _latest_bank_payload(self.NAME)
            rates = payload.get("rates")
            detail = rates.get(source_code) if isinstance(rates, dict) else None
            if not isinstance(detail, dict):
                return {"lines": [f"{self.NAME} {symbol}: not found"]}
        except (requests.RequestException, ValueError) as exc:
            log.error("%s API fetch error: %s", self.NAME, exc)
            return {"lines": [f"{self.NAME} {symbol}: fetch error"]}

        cash = detail.get("cash") if isinstance(detail.get("cash"), dict) else {}
        noncash = (
            detail.get("noncash") if isinstance(detail.get("noncash"), dict) else {}
        )
        values = {
            "cash_buy": _number(cash.get("buy")),
            "cash_sell": _number(cash.get("sell")),
            "noncash_buy": _number(noncash.get("buy")),
            "noncash_sell": _number(noncash.get("sell")),
        }
        if all(value is None for value in values.values()):
            return {"lines": [f"{self.NAME} {symbol}: not found"]}

        labels = {
            "cash_buy": "Cash Buy",
            "cash_sell": "Cash Sell",
            "noncash_buy": "Non-cash Buy",
            "noncash_sell": "Non-cash Sell",
        }
        lines = [
            f"{self.NAME} {symbol} {labels[key]}: `{value:.2f}`"
            for key, value in values.items()
            if value is not None
        ]
        result: dict[str, Any] = {
            "lines": lines,
            **{key: value for key, value in values.items() if value is not None},
        }

        # Preserve the existing provider contract for calculations and callers
        # that only understand a single buy/sell pair. Prefer non-cash rates.
        buy = (
            values["noncash_buy"]
            if values["noncash_buy"] is not None
            else values["cash_buy"]
        )
        sell = (
            values["noncash_sell"]
            if values["noncash_sell"] is not None
            else values["cash_sell"]
        )
        if buy is not None:
            result["buy"] = buy
        if sell is not None:
            result["sell"] = sell
            result["rate"] = sell
        return result


for _bank_code, _display_name in _BANKS:
    _provider_class = type(
        f"{_bank_code}Provider",
        (MongolianBankProvider,),
        {
            "NAME": _bank_code,
            "DISPLAY_NAME": _display_name,
            "__module__": __name__,
        },
    )
    register_provider(_provider_class)

del _bank_code, _display_name, _provider_class
