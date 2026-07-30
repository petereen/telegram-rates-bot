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
    get_cached_rate_entry,
    get_subscriptions,
    set_cached_rate,
)
from providers.base import get_provider

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
    return any(data.get(key) is not None for key in ("rate", "buy", "sell"))


def snapshot_from_provider_data(
    provider: str,
    symbol: str,
    data: dict[str, Any],
    *,
    fetched_at: Optional[datetime] = None,
    status: str = "fresh",
) -> RateSnapshot:
    values: list[RateValue] = []
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


async def get_formula_snapshots(force: bool = False) -> list[RateSnapshot]:
    """Calculate the three default rates with concurrent upstream requests."""

    async def fetch(provider: str, symbol: str) -> tuple[RateSnapshot, dict[str, Any]]:
        instance = get_provider(provider)
        data = await asyncio.to_thread(
            instance.fetch if force else instance.get_rate, symbol
        )
        if force and _is_success(data):
            await asyncio.to_thread(set_cached_rate, provider, symbol, data)
        return snapshot_from_provider_data(provider, symbol, data), data

    results = await asyncio.gather(
        fetch("MongolBank", "RUB/MNT"),
        fetch("TDB", "USD/MNT"),
        fetch("CBR", "USD/RUB"),
        fetch("Binance", "P2P USDT/MNT"),
        fetch("Rapira", "USDT/RUB"),
        return_exceptions=True,
    )

    def unpack(index: int) -> tuple[Optional[RateSnapshot], dict[str, Any]]:
        result = results[index]
        if isinstance(result, Exception):
            return None, {}
        return result

    mb_snapshot, mb = unpack(0)
    tdb_snapshot, tdb = unpack(1)
    cbr_snapshot, cbr = unpack(2)
    binance_snapshot, binance = unpack(3)
    rapira_snapshot, rapira = unpack(4)
    now = datetime.now(timezone.utc).isoformat()
    formulas: list[RateSnapshot] = []

    try:
        base = Decimal(str(mb["rate"]))
        result = base * Decimal("1.005")
        formulas.append(
            RateSnapshot(
                key="formula:delcrado",
                kind="calculated",
                source="Тооцоолсон",
                pair="ДЕЛЬКРАДО",
                values=[RateValue("value", _amount(result, 2))],
                fetched_at=mb_snapshot.fetched_at if mb_snapshot else now,
                formula="MongolBank RUB/MNT × 1.005",
                details=[f"MongolBank RUB: {_amount(base, 2)}", "+0.50%"],
            )
        )
    except (KeyError, TypeError, ValueError):
        formulas.append(_formula_error("delcrado", "ДЕЛЬКРАДО", "MongolBank ханш олдсонгүй"))

    try:
        tdb_sell = Decimal(str(tdb["sell"]))
        cbr_rate = Decimal(str(cbr["rate"]))
        result = (tdb_sell / cbr_rate) * Decimal("1.01")
        formulas.append(
            RateSnapshot(
                key="formula:triquetra",
                kind="calculated",
                source="Тооцоолсон",
                pair="ТРИКУЭТРА",
                values=[RateValue("value", _amount(result, 2))],
                fetched_at=max(
                    tdb_snapshot.fetched_at if tdb_snapshot else now,
                    cbr_snapshot.fetched_at if cbr_snapshot else now,
                ),
                formula="TDB USD/MNT sell ÷ CBR USD/RUB × 1.01",
                details=[
                    f"TDB USD sell: {_amount(tdb_sell, 2)}",
                    f"CBR USD/RUB: {_amount(cbr_rate, 4)}",
                    "+1%",
                ],
            )
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        formulas.append(_formula_error("triquetra", "ТРИКУЭТРА", "TDB эсвэл CBR ханш олдсонгүй"))

    try:
        mnt = Decimal(str(binance["min_price"]))
        rub = Decimal(str(rapira.get("buy") or rapira["bid"]))
        result = mnt / rub
        formulas.append(
            RateSnapshot(
                key="formula:rub-cash",
                kind="calculated",
                source="Тооцоолсон",
                pair="RUB БЭЛЭН",
                values=[RateValue("value", _amount(result, 2))],
                fetched_at=max(
                    binance_snapshot.fetched_at if binance_snapshot else now,
                    rapira_snapshot.fetched_at if rapira_snapshot else now,
                ),
                formula="Binance min USDT/MNT ÷ Rapira buy USDT/RUB",
                details=[
                    f"Binance USDT/MNT: {_amount(mnt, 2)}",
                    f"Rapira buy: {_amount(rub, 2)}",
                ],
            )
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        formulas.append(_formula_error("rub-cash", "RUB БЭЛЭН", "Binance эсвэл Rapira ханш олдсонгүй"))

    return formulas


async def allowed_rate_keys(telegram_id: int) -> set[str]:
    rows = await asyncio.to_thread(get_subscriptions, telegram_id)
    keys = {rate_key(row["provider"], row["symbol"]) for row in rows}
    keys.update({"formula:delcrado", "formula:triquetra", "formula:rub-cash"})
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
        lines.extend(
            [
                "",
                "<b>Тооцоолол</b>",
                f"{html.escape(calculation['expression'])} = "
                f"<code>{html.escape(calculation['result'])}</code>",
            ]
        )
    return "\n".join(lines)
