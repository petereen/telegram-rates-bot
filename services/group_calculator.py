"""Calculator expressions whose operands are a user's saved rates."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from db.supabase_client import get_subscriptions
from services.calculator import CalculationError, evaluate_tokens
from services.rates import RateSnapshot, get_rate_snapshot


class ShortlistCalculationError(ValueError):
    """Raised when a group calculator expression cannot be resolved."""


@dataclass(frozen=True)
class RateReference:
    provider: str
    symbol: str
    field: str | None = None


@dataclass(frozen=True)
class ShortlistCalculation:
    expression: str
    result: str
    resolved_expression: str


# A reference is deliberately explicit. A symbol may be a conventional pair,
# a single currency (BOC:USD), or contain a provider prefix
# (Binance:P2P USDT/MNT).
_SYMBOL_PART = r"[A-Za-z0-9._-]+"
_SYMBOL = rf"{_SYMBOL_PART}(?: {_SYMBOL_PART})*(?:/{_SYMBOL_PART})?"
_REFERENCE = rf"([A-Za-z0-9_-]+):({_SYMBOL})(?::([A-Za-z0-9_-]+))?"
_TOKEN = re.compile(
    rf"\s*(?:{_REFERENCE}|([+-]\d+(?:[.,]\d+)?%)|(\d+(?:[.,]\d+)?|[+*/-]))"
)


def parse_shortlist_expression(text: str) -> list[str | RateReference]:
    """Parse a compact calculator expression without accepting stray text."""
    source = text.strip()
    if not source:
        raise ShortlistCalculationError("Илэрхийлэл хоосон байна")
    if len(source) > 256:
        raise ShortlistCalculationError("Илэрхийлэл хэт урт байна")

    tokens: list[str | RateReference] = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            raise ShortlistCalculationError(
                "Илэрхийлэл буруу байна. Жишээ: CBR:USD/RUB / 2"
            )
        provider, symbol, field, percent, simple = match.groups()
        if provider is not None:
            tokens.append(RateReference(provider, symbol, field))
        else:
            tokens.append(percent or simple)
        position = match.end()

    if len(tokens) > 25:
        raise ShortlistCalculationError("Илэрхийлэл хэт олон үйлдэлтэй байна")
    return tokens


def _match_subscription(reference: RateReference, rows: list[dict[str, Any]]) -> dict[str, Any]:
    match = next(
        (
            row
            for row in rows
            if str(row["provider"]).casefold() == reference.provider.casefold()
            and str(row["symbol"]).casefold() == reference.symbol.casefold()
        ),
        None,
    )
    if match is None:
        raise ShortlistCalculationError(
            f"{reference.provider}:{reference.symbol} таны жагсаалтад байхгүй байна"
        )
    return match


def _select_value(reference: RateReference, snapshot: RateSnapshot) -> tuple[str, str]:
    if snapshot.status == "error" or not snapshot.values:
        raise ShortlistCalculationError(
            f"{reference.provider}:{reference.symbol} ханш авах боломжгүй байна"
        )

    if reference.field is None:
        if len(snapshot.values) != 1:
            fields = ", ".join(
                value.label.replace(" ", "_").replace("-", "_")
                for value in snapshot.values
            )
            raise ShortlistCalculationError(
                f"{reference.provider}:{reference.symbol} олон утгатай. "
                f"Талбараа заана уу: {fields}"
            )
        value = snapshot.values[0]
    else:
        def normalize_field(field: str) -> str:
            return re.sub(r"[\s_-]+", "", field.casefold())

        target = normalize_field(reference.field)
        value = next(
            (
                item
                for item in snapshot.values
                if normalize_field(item.label) == target
            ),
            None,
        )
        if value is None:
            raise ShortlistCalculationError(
                f"{reference.provider}:{reference.symbol}:{reference.field} талбар олдсонгүй"
            )

    label = f"{reference.provider}:{reference.symbol}:{value.label.replace(' ', '_').replace('-', '_')}"
    return value.amount, label


def _display_reference(reference: str) -> str:
    provider, symbol, field = reference.split(":", 2)
    field_label = {
        "value": "ханш",
        "buy": "авах",
        "sell": "зарах",
        "cash_buy": "бэлэн авах",
        "cash_sell": "бэлэн зарах",
        "non_cash_buy": "бэлэн бус авах",
        "non_cash_sell": "бэлэн бус зарах",
    }.get(field, field.replace("_", " "))
    return f"{provider} · {symbol} ({field_label})"


async def calculate_shortlist_expression(
    telegram_id: int, text: str
) -> ShortlistCalculation:
    """Resolve saved-rate references and evaluate them with the shared calculator."""
    parsed = parse_shortlist_expression(text)
    references = [token for token in parsed if isinstance(token, RateReference)]
    rows = await asyncio.to_thread(get_subscriptions, telegram_id)

    selected: dict[RateReference, dict[str, Any]] = {}
    for reference in references:
        selected.setdefault(reference, _match_subscription(reference, rows))

    snapshots = await asyncio.gather(
        *(
            asyncio.to_thread(
                get_rate_snapshot, row["provider"], row["symbol"]
            )
            for row in selected.values()
        )
    )
    resolved = {
        reference: _select_value(reference, snapshot)
        for reference, snapshot in zip(selected, snapshots)
    }

    calculator_tokens: list[str] = []
    display_tokens: list[str] = []
    resolved_tokens: list[str] = []
    for token in parsed:
        if isinstance(token, RateReference):
            amount, label = resolved[token]
            calculator_tokens.append(amount)
            display_tokens.append(_display_reference(label))
            resolved_tokens.append(amount)
        else:
            calculator_tokens.append(token)
            displayed_token = {"*": "×", "/": "÷"}.get(token, token)
            display_tokens.append(displayed_token)
            resolved_tokens.append(displayed_token)

    try:
        calculation = evaluate_tokens(calculator_tokens)
    except CalculationError as exc:
        raise ShortlistCalculationError(str(exc)) from exc
    return ShortlistCalculation(
        expression=" ".join(display_tokens),
        result=calculation["result"],
        resolved_expression=" ".join(resolved_tokens),
    )
