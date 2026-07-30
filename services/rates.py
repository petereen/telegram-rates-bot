"""Structured rate and formula services shared by Telegram and FastAPI."""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from db.supabase_client import (
    get_formula_definitions,
    get_cached_rate_entry,
    get_subscriptions,
    set_cached_rate,
)
from providers.base import all_providers, get_provider

log = logging.getLogger(__name__)
UB_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RateValue:
    label: str
    amount: str


@dataclass
class RateSnapshot:
    key: str
    kind: str
    source: str
    pair: str
    values: list[RateValue]
    fetched_at: str
    status: str = "fresh"
    formula: Optional[str] = None
    details: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fetchedAt"] = data.pop("fetched_at")
        return data


def rate_key(provider: str, symbol: str) -> str:
    return f"rate:{provider}:{symbol}"


def _amount(value: Any, digits: int = 8) -> str:
    number = Decimal(str(value))
    rendered = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _is_success(data: dict[str, Any]) -> bool:
    return any(
        data.get(key) is not None
        for key in (
            "rate",
            "buy",
            "sell",
            "cash_buy",
            "cash_sell",
            "noncash_buy",
            "noncash_sell",
        )
    )


def snapshot_from_provider_data(
    provider: str,
    symbol: str,
    data: dict[str, Any],
    *,
    fetched_at: Optional[datetime] = None,
    status: str = "fresh",
) -> RateSnapshot:
    values: list[RateValue] = []
    detailed_fields = (
        ("cash_buy", "cash buy"),
        ("cash_sell", "cash sell"),
        ("noncash_buy", "non-cash buy"),
        ("noncash_sell", "non-cash sell"),
    )
    for key, label in detailed_fields:
        if data.get(key) is not None:
            values.append(RateValue(label, _amount(data[key])))
    if not values:
        if data.get("buy") is not None:
            values.append(RateValue("buy", _amount(data["buy"])))
        if data.get("sell") is not None:
            values.append(RateValue("sell", _amount(data["sell"])))
    if not values and data.get("rate") is not None:
        values.append(RateValue("value", _amount(data["rate"])))

    error = None
    if not values:
        status = "error"
        lines = data.get("lines") or []
        error = str(lines[0]) if lines else "Ханш авах боломжгүй"

    timestamp = fetched_at or datetime.now(timezone.utc)
    return RateSnapshot(
        key=rate_key(provider, symbol),
        kind="subscription",
        source=provider,
        pair=symbol,
        values=values,
        fetched_at=timestamp.isoformat(),
        status=status,
        error=error,
    )


def get_rate_snapshot(provider: str, symbol: str, force: bool = False) -> RateSnapshot:
    """Get a structured rate, preserving stale data when a forced refresh fails."""
    rate_provider = get_provider(provider)
    if not force:
        data = rate_provider.get_rate(symbol)
        cached = get_cached_rate_entry(provider, symbol, include_stale=True)
        fetched_at = cached[1] if cached else datetime.now(timezone.utc)
        return snapshot_from_provider_data(provider, symbol, data, fetched_at=fetched_at)

    stale = get_cached_rate_entry(provider, symbol, include_stale=True)
    try:
        data = rate_provider.fetch(symbol)
    except Exception as exc:
        log.warning("Forced refresh failed for %s/%s: %s", provider, symbol, exc)
        data = {"lines": [f"{provider} {symbol}: fetch error"]}

    if _is_success(data):
        set_cached_rate(provider, symbol, data)
        return snapshot_from_provider_data(provider, symbol, data)
    if stale and _is_success(stale[0]):
        snapshot = snapshot_from_provider_data(
            provider, symbol, stale[0], fetched_at=stale[1], status="stale"
        )
        snapshot.error = "Шинэчлэхэд алдаа гарлаа"
        return snapshot
    return snapshot_from_provider_data(provider, symbol, data)


def _formula_error(key: str, title: str, message: str) -> RateSnapshot:
    return RateSnapshot(
        key=f"formula:{key}",
        kind="calculated",
        source="Тооцоолсон",
        pair=title,
        values=[],
        fetched_at=datetime.now(timezone.utc).isoformat(),
        status="error",
        error=message,
    )


FIELD_LABELS = {
    "rate": "ханш",
    "buy": "авах",
    "sell": "зарах",
    "min_price": "хамгийн бага",
    "bid": "bid",
    "ask": "ask",
    "cash_buy": "бэлэн авах",
    "cash_sell": "бэлэн зарах",
    "noncash_buy": "бэлэн бус авах",
    "noncash_sell": "бэлэн бус зарах",
}


def formula_definition_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "left": row["left_operand"],
        "operator": row["operator"],
        "right": row["right_operand"],
        "adjustmentPercent": (
            str(row["adjustment_percent"])
            if row.get("adjustment_percent") is not None
            else None
        ),
        "precision": int(row["precision"]),
        "enabled": bool(row["enabled"]),
        "sortOrder": int(row["sort_order"]),
        "updatedAt": row.get("updated_at"),
    }


def normalize_formula_definition(data: dict[str, Any]) -> dict[str, Any]:
    """Validate API formula data and return the database representation."""
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 80:
        raise ValueError("Томьёоны нэр 1–80 тэмдэгт байна")
    operator = str(data.get("operator") or "")
    if operator not in {"+", "-", "*", "/"}:
        raise ValueError("Томьёоны үйлдэл буруу")

    providers = all_providers()

    def operand(raw: Any, *, allow_constant: bool) -> dict[str, str]:
        if not isinstance(raw, dict):
            raise ValueError("Томьёоны утга буруу")
        kind = raw.get("kind")
        if allow_constant and kind == "constant":
            try:
                value = Decimal(str(raw.get("value")))
            except Exception as exc:
                raise ValueError("Тогтмол утга буруу") from exc
            if not value.is_finite():
                raise ValueError("Тогтмол утга буруу")
            return {"kind": "constant", "value": str(value)}
        if kind != "rate":
            raise ValueError("Ханшийн утга сонгоно уу")
        provider_name = str(raw.get("provider") or "")
        symbol = str(raw.get("symbol") or "")
        field_name = str(raw.get("field") or "")
        provider = providers.get(provider_name)
        if provider is None or symbol not in provider.PAIRS:
            raise ValueError("Томьёоны эх сурвалж олдсонгүй")
        if field_name not in provider.formula_fields(symbol):
            raise ValueError("Сонгосон ханшийн талбар дэмжигдэхгүй")
        return {
            "kind": "rate",
            "provider": provider_name,
            "symbol": symbol,
            "field": field_name,
        }

    adjustment = data.get("adjustmentPercent")
    if adjustment in ("", None):
        normalized_adjustment = None
    else:
        try:
            percent = Decimal(str(adjustment))
        except Exception as exc:
            raise ValueError("Хувийн тохируулга буруу") from exc
        if not percent.is_finite() or percent <= Decimal("-100"):
            raise ValueError("Хувийн тохируулга -100%-аас их байна")
        normalized_adjustment = str(percent)

    try:
        precision = int(data.get("precision", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("Нарийвчлал буруу") from exc
    if precision < 0 or precision > 8:
        raise ValueError("Нарийвчлал 0–8 байна")

    return {
        "title": title,
        "left_operand": operand(data.get("left"), allow_constant=False),
        "operator": operator,
        "right_operand": operand(data.get("right"), allow_constant=True),
        "adjustment_percent": normalized_adjustment,
        "precision": precision,
        "enabled": bool(data.get("enabled", True)),
    }


def _operand_label(operand: dict[str, Any]) -> str:
    if operand["kind"] == "constant":
        return str(operand["value"])
    field = FIELD_LABELS.get(operand["field"], operand["field"])
    return f"{operand['provider']} {operand['symbol']} {field}"


def _formula_label(definition: dict[str, Any]) -> str:
    operator = {"*": "×", "/": "÷"}.get(
        definition["operator"], definition["operator"]
    )
    label = (
        f"{_operand_label(definition['left_operand'])} {operator} "
        f"{_operand_label(definition['right_operand'])}"
    )
    adjustment = definition.get("adjustment_percent")
    if adjustment is not None and Decimal(str(adjustment)):
        sign = "+" if Decimal(str(adjustment)) > 0 else ""
        label += f" {sign}{adjustment}%"
    return label


async def get_formula_snapshots(
    force: bool = False,
    definitions: Optional[list[dict[str, Any]]] = None,
) -> list[RateSnapshot]:
    """Evaluate globally configured formulas with de-duplicated rate fetches."""
    if definitions is None:
        definitions = await asyncio.to_thread(
            get_formula_definitions, include_disabled=False
        )

    dependencies: set[tuple[str, str]] = set()
    for definition in definitions:
        for operand in (
            definition.get("left_operand", {}),
            definition.get("right_operand", {}),
        ):
            if operand.get("kind") == "rate":
                dependencies.add((operand["provider"], operand["symbol"]))

    async def fetch(provider: str, symbol: str) -> tuple[dict[str, Any], str]:
        instance = get_provider(provider)
        data = await asyncio.to_thread(
            instance.fetch if force else instance.get_rate, symbol
        )
        if force and _is_success(data):
            await asyncio.to_thread(set_cached_rate, provider, symbol, data)
        cached = await asyncio.to_thread(
            get_cached_rate_entry, provider, symbol, include_stale=True
        )
        fetched_at = cached[1] if cached else datetime.now(timezone.utc)
        return data, fetched_at.isoformat()

    dependency_list = sorted(dependencies)
    fetched = await asyncio.gather(
        *(fetch(provider, symbol) for provider, symbol in dependency_list),
        return_exceptions=True,
    )
    values = dict(zip(dependency_list, fetched))
    snapshots: list[RateSnapshot] = []

    for definition in definitions:
        formula_id = str(definition["id"])
        title = str(definition["title"])
        try:
            timestamps: list[str] = []

            def resolve(operand: dict[str, Any]) -> Decimal:
                if operand["kind"] == "constant":
                    return Decimal(str(operand["value"]))
                dependency = values[(operand["provider"], operand["symbol"])]
                if isinstance(dependency, Exception):
                    raise ValueError("upstream error")
                payload, fetched_at = dependency
                timestamps.append(fetched_at)
                return Decimal(str(payload[operand["field"]]))

            left = resolve(definition["left_operand"])
            right = resolve(definition["right_operand"])
            operator = definition["operator"]
            if operator == "+":
                result = left + right
            elif operator == "-":
                result = left - right
            elif operator == "*":
                result = left * right
            else:
                result = left / right
            adjustment = definition.get("adjustment_percent")
            if adjustment is not None:
                result *= Decimal("1") + Decimal(str(adjustment)) / Decimal("100")
            precision = int(definition["precision"])
            snapshots.append(
                RateSnapshot(
                    key=f"formula:{formula_id}",
                    kind="calculated",
                    source="Тооцоолсон",
                    pair=title,
                    values=[RateValue("value", _amount(result, precision))],
                    fetched_at=max(timestamps) if timestamps else datetime.now(timezone.utc).isoformat(),
                    formula=_formula_label(definition),
                    details=[
                        f"{_operand_label(definition['left_operand'])}: {_amount(left)}",
                        f"{_operand_label(definition['right_operand'])}: {_amount(right)}",
                    ],
                )
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            snapshots.append(
                _formula_error(formula_id, title, "Томьёоны ханш авах боломжгүй")
            )
    return snapshots


async def allowed_rate_keys(telegram_id: int) -> set[str]:
    rows = await asyncio.to_thread(get_subscriptions, telegram_id)
    keys = {rate_key(row["provider"], row["symbol"]) for row in rows}
    definitions = await asyncio.to_thread(
        get_formula_definitions, include_disabled=False
    )
    keys.update(f"formula:{row['id']}" for row in definitions)
    return keys


async def resolve_user_rate_keys(
    telegram_id: int,
    keys: list[str],
    *,
    force: bool = False,
) -> list[RateSnapshot]:
    """Resolve only keys the user is entitled to access."""
    allowed = await allowed_rate_keys(telegram_id)
    if not keys or any(key not in allowed for key in keys):
        raise ValueError("Ханшийн сонголт буруу")

    formulas: dict[str, RateSnapshot] = {}
    if any(key.startswith("formula:") for key in keys):
        formulas = {
            snapshot.key: snapshot
            for snapshot in await get_formula_snapshots(force=force)
        }

    async def resolve(key: str) -> RateSnapshot:
        if key.startswith("formula:"):
            return formulas[key]
        _, provider, symbol = key.split(":", 2)
        return await asyncio.to_thread(get_rate_snapshot, provider, symbol, force)

    return list(await asyncio.gather(*(resolve(key) for key in keys)))


def render_formula_html(snapshot: RateSnapshot) -> str:
    title = html.escape(snapshot.pair)
    if snapshot.status == "error" or not snapshot.values:
        return f"<b>{title}:</b> {html.escape(snapshot.error or 'алдаа')}"
    details = " / ".join(html.escape(item) for item in snapshot.details)
    value = html.escape(snapshot.values[0].amount)
    detail_line = f"\n  {details}" if details else ""
    return f"<b>{title}:</b>{detail_line}\n  ▶ <code>{value}</code>"


def render_share_html(
    snapshots: list[RateSnapshot],
    calculation: Optional[dict[str, str]] = None,
    calculation_result: Optional[str] = None,
) -> str:
    now = datetime.now(UB_TZ)
    lines = [
        "💱 <b>ХАНШИЙН МЭДЭЭЛЭЛ</b>",
        f"<i>{now:%Y-%m-%d · %H:%M} (УБ)</i>",
    ]
    for snapshot in snapshots:
        lines.append("")
        lines.append(f"<b>{html.escape(snapshot.pair)}</b>")
        if snapshot.kind == "subscription":
            lines.append(html.escape(snapshot.source))
        if snapshot.status == "error" or not snapshot.values:
            lines.append(html.escape(snapshot.error or "Ханш олдсонгүй"))
            continue
        for value in snapshot.values:
            label = {"buy": "Авах", "sell": "Зарах", "value": "Ханш"}.get(
                value.label, value.label
            )
            lines.append(f"{label}: <code>{html.escape(value.amount)}</code>")
        if snapshot.formula:
            lines.append(f"<i>{html.escape(snapshot.formula)}</i>")
    if calculation:
        result = calculation_result or calculation["result"]
        lines.extend(
            [
                "",
                "<b>Тооцоолол</b>",
                f"{html.escape(calculation['expression'])} = "
                f"<code>{html.escape(result)}</code>",
            ]
        )
    return "\n".join(lines)
