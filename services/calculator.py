"""Safe calculator shared by the bot-facing API and the web application."""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP
from typing import Any

OPERATORS = {"+", "-", "*", "/"}


class CalculationError(ValueError):
    """Raised when a calculator expression is invalid."""


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CalculationError("Boolean values are not valid numbers")
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise CalculationError("Invalid number") from exc


def _evaluate_simple(tokens: list[Decimal | str]) -> Decimal:
    if not tokens or not isinstance(tokens[0], Decimal):
        raise CalculationError("Expression must start with a number")
    if len(tokens) % 2 == 0 or not isinstance(tokens[-1], Decimal):
        raise CalculationError("Expression is incomplete")

    work = list(tokens)
    index = 1
    while index < len(work):
        operator = work[index]
        if operator in ("*", "/"):
            left = work[index - 1]
            right = work[index + 1]
            assert isinstance(left, Decimal) and isinstance(right, Decimal)
            try:
                result = left * right if operator == "*" else left / right
            except (DivisionByZero, ZeroDivisionError) as exc:
                raise CalculationError("Тэгд хуваах боломжгүй") from exc
            work[index - 1 : index + 2] = [result]
        else:
            index += 2

    while len(work) > 1:
        left, operator, right = work[0:3]
        assert isinstance(left, Decimal) and isinstance(right, Decimal)
        result = left + right if operator == "+" else left - right
        work[0:3] = [result]
    result = work[0]
    assert isinstance(result, Decimal)
    return result


def format_decimal(value: Decimal) -> str:
    """Format a decimal without scientific notation or redundant zeroes."""
    if value == value.to_integral():
        return format(value.quantize(Decimal("1")), "f")
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def format_hundredths(value: Decimal | str) -> str:
    """Round half-up and retain exactly two fractional digits."""
    number = value if isinstance(value, Decimal) else _decimal(value)
    return format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def evaluate_tokens(raw_tokens: list[Any]) -> dict[str, str]:
    """Evaluate structured number/operator/percentage tokens.

    Percentage strings such as ``+0.5%`` apply to the running subtotal,
    matching the existing Telegram calculator.
    """
    if not raw_tokens:
        raise CalculationError("Илэрхийлэл хоосон байна")

    tokens: list[Decimal | str] = []
    display: list[str] = []

    for raw in raw_tokens:
        if isinstance(raw, str) and raw.endswith("%"):
            if not tokens or not isinstance(tokens[-1], Decimal):
                raise CalculationError("Хувийн өмнө тоо оруулна уу")
            try:
                percent = _decimal(raw[:-1])
            except CalculationError as exc:
                raise CalculationError("Буруу хувь") from exc
            subtotal = _evaluate_simple(tokens)
            subtotal *= Decimal("1") + percent / Decimal("100")
            tokens = [subtotal]
            display.append(raw)
            continue

        if isinstance(raw, str) and raw in OPERATORS:
            if not tokens or not isinstance(tokens[-1], Decimal):
                raise CalculationError("Операторын өмнө тоо оруулна уу")
            tokens.append(raw)
            display.append("×" if raw == "*" else "÷" if raw == "/" else raw)
            continue

        number = _decimal(raw)
        if tokens and isinstance(tokens[-1], Decimal):
            raise CalculationError("Хоёр тооны хооронд оператор оруулна уу")
        tokens.append(number)
        display.append(format_decimal(number))

    result = _evaluate_simple(tokens)
    return {
        "expression": " ".join(display),
        "result": format_decimal(result),
    }
