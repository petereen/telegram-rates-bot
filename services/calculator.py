"""Safe calculator shared by the bot-facing API and the web application."""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP
import html
import re
from typing import Any

OPERATORS = {"+", "-", "*", "/"}


class CalculationError(ValueError):
    """Raised when a calculator expression is invalid."""


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CalculationError("Boolean values are not valid numbers")
    try:
        text = str(value).strip()
        # Accept both decimal commas and conventional thousands separators.
        # A comma next to a decimal point (or in repeated 3-digit groups) is a
        # thousands separator; a single other comma is treated as a decimal.
        if "." in text:
            text = text.replace(",", "")
        elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        return Decimal(text)
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


def _evaluate_parenthesized(tokens: list[Decimal | str]) -> Decimal:
    """Evaluate tokens with normal precedence and nested parentheses."""
    position = 0

    def factor() -> Decimal:
        nonlocal position
        if position >= len(tokens):
            raise CalculationError("Expression is incomplete")
        token = tokens[position]
        if isinstance(token, Decimal):
            position += 1
            return token
        if token == "(":
            position += 1
            result = expression()
            if position >= len(tokens) or tokens[position] != ")":
                raise CalculationError("Хаалт дутуу байна")
            position += 1
            return result
        raise CalculationError("Expression is invalid")

    def term() -> Decimal:
        nonlocal position
        result = factor()
        while position < len(tokens) and tokens[position] in ("*", "/"):
            operator = tokens[position]
            position += 1
            right = factor()
            try:
                result = result * right if operator == "*" else result / right
            except (DivisionByZero, ZeroDivisionError) as exc:
                raise CalculationError("Тэгд хуваах боломжгүй") from exc
        return result

    def expression() -> Decimal:
        nonlocal position
        result = term()
        while position < len(tokens) and tokens[position] in ("+", "-"):
            operator = tokens[position]
            position += 1
            right = term()
            result = result + right if operator == "+" else result - right
        return result

    result = expression()
    if position != len(tokens):
        raise CalculationError("Expression is invalid")
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


def format_grouped_hundredths(value: Decimal | str) -> str:
    """Round half-up and format a number with thousands separators."""
    number = value if isinstance(value, Decimal) else _decimal(value)
    return format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ",.2f")


_NUMERIC_EXPRESSION_TOKEN = re.compile(
    r"\s*(?:(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?|[+-]\d+(?:[.,]\d+)?%)|([+*/-])|([()]))"
)


def parse_numeric_expression(text: str) -> list[str]:
    """Parse a plain arithmetic expression without accepting other text."""
    source = text.strip()
    if not source:
        raise CalculationError("Илэрхийлэл хоосон байна")

    tokens: list[str] = []
    position = 0
    while position < len(source):
        match = _NUMERIC_EXPRESSION_TOKEN.match(source, position)
        if match is None:
            raise CalculationError("Илэрхийлэл буруу байна")
        tokens.append(match.group(1) or match.group(2) or match.group(3))
        position = match.end()
    return tokens


def render_normal_calculation(raw_tokens: list[Any]) -> str:
    """Render normal calculator input as a left-to-right running ledger."""
    calculation = evaluate_running_tokens(raw_tokens)
    steps = calculation["steps"]
    lines = [f"+ {format_grouped_hundredths(steps[0]['operand'])}"]
    for step in steps[1:]:
        lines.extend(
            [
                f"{step['operator']} {step['operand'] if step.get('percentage') else format_grouped_hundredths(step['operand'])}",
                "---------------",
                f"+ {format_grouped_hundredths(step['subtotal'])}",
            ]
        )
    return "<pre>" + "\n".join(lines) + "</pre>"


def tape_entries_to_tokens(entries: list[dict[str, Any]]) -> list[str]:
    """Convert validated tape rows to calculator tokens."""
    if not entries:
        raise CalculationError("Илэрхийлэл хоосон байна")
    tokens = [str(entries[0].get("value", ""))]
    for entry in entries[1:]:
        operator = str(entry.get("operator", "+"))
        value = str(entry.get("value", ""))
        if entry.get("percentage"):
            tokens.append(("-" if operator == "-" else "+") + value.lstrip("+-"))
        else:
            tokens.extend([operator, value])
    return tokens


def render_tape_html(title: str, entries: list[dict[str, Any]]) -> str:
    """Render an annotated calculation tape for Telegram HTML messages."""
    calculation = evaluate_running_tokens(tape_entries_to_tokens(entries))
    lines = [f"🧾 <b>{html.escape(title.strip() or 'Тооцоолол')}</b>"]
    for index, (entry, step) in enumerate(zip(entries, calculation["steps"])):
        operand = (
            step["operand"]
            if step.get("percentage")
            else format_grouped_hundredths(step["operand"])
        )
        lines.append(f"<code>{step['operator']} {operand}</code>")
        label = str(entry.get("label") or "").strip()
        if label:
            lines.append(f"<i>{html.escape(label[:160])}</i>")
        if index:
            lines.extend([
                "<code>---------------</code>",
                f"<code>+ {format_grouped_hundredths(step['subtotal'])}</code>",
            ])
    return "\n".join(lines)


def evaluate_running_tokens(raw_tokens: list[Any]) -> dict[str, Any]:
    """Evaluate ordinary calculator input left-to-right, retaining subtotals."""
    if not raw_tokens:
        raise CalculationError("Илэрхийлэл хоосон байна")
    if any(token in ("(", ")") for token in raw_tokens):
        raise CalculationError("Энгийн тооцоололд хаалт ашиглах шаардлагагүй")

    first, *remaining = raw_tokens
    if isinstance(first, str) and (first in OPERATORS or first.endswith("%")):
        raise CalculationError("Expression must start with a number")
    subtotal = _decimal(first)
    steps: list[dict[str, Any]] = [{
        "operator": "+",
        "operand": format_decimal(subtotal),
        "subtotal": format_decimal(subtotal),
        "percentage": False,
    }]
    display = [format_decimal(subtotal)]

    position = 0
    while position < len(remaining):
        candidate = remaining[position]
        if isinstance(candidate, str) and candidate.endswith("%"):
            try:
                percent = _decimal(candidate[:-1])
            except CalculationError as exc:
                raise CalculationError("Буруу хувь") from exc
            subtotal *= Decimal("1") + percent / Decimal("100")
            operator = "+" if percent >= 0 else "-"
            steps.append({
                "operator": operator,
                "operand": f"{format_decimal(abs(percent))}%",
                "subtotal": format_decimal(subtotal),
                "percentage": True,
            })
            display.append(candidate)
            position += 1
            continue
        if position + 1 >= len(remaining):
            raise CalculationError("Expression is incomplete")
        operator = candidate
        raw_operand = remaining[position + 1]
        if operator not in OPERATORS:
            raise CalculationError("Expression is invalid")
        operand = _decimal(raw_operand)
        try:
            if operator == "+":
                subtotal += operand
            elif operator == "-":
                subtotal -= operand
            elif operator == "*":
                subtotal *= operand
            else:
                subtotal /= operand
        except (DivisionByZero, ZeroDivisionError) as exc:
            raise CalculationError("Тэгд хуваах боломжгүй") from exc
        steps.append({
            "operator": operator,
            "operand": format_decimal(operand),
            "subtotal": format_decimal(subtotal),
            "percentage": False,
        })
        display.extend(["×" if operator == "*" else "÷" if operator == "/" else operator, format_decimal(operand)])
        position += 2

    return {
        "expression": " ".join(display),
        "result": format_decimal(subtotal),
        "steps": steps,
    }


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
        if raw in ("(", ")"):
            tokens.append(raw)
            display.append(raw)
            continue
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
            if not tokens or (not isinstance(tokens[-1], Decimal) and tokens[-1] != ")"):
                raise CalculationError("Операторын өмнө тоо оруулна уу")
            tokens.append(raw)
            display.append("×" if raw == "*" else "÷" if raw == "/" else raw)
            continue

        number = _decimal(raw)
        if tokens and (isinstance(tokens[-1], Decimal) or tokens[-1] == ")"):
            raise CalculationError("Хоёр тооны хооронд оператор оруулна уу")
        tokens.append(number)
        display.append(format_decimal(number))

    result = (
        _evaluate_parenthesized(tokens)
        if "(" in tokens or ")" in tokens
        else _evaluate_simple(tokens)
    )
    return {
        "expression": " ".join(display),
        "result": format_decimal(result),
    }
