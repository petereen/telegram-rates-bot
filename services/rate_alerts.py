"""Sudden-change detection and Telegram alert rendering for rate snapshots."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Iterable

_DAILY_PROVIDERS = {
    "MongolBank", "CBR", "BOC", "CapitronBank", "KhanBank", "GolomtBank",
    "XacBank", "ArigBank", "StateBank", "NaimanSharga", "SendMN", "TDBM",
    "BogdBank", "CKBank", "NIBank", "TransBank", "MBank",
}
_MAJOR_CRYPTO = {"BTC", "ETH", "SOL", "XRP", "BNB", "TON", "DOGE"}
_FIELD_LABELS = {
    "rate": "Ханш", "buy": "Авах", "sell": "Зарах",
    "cash_buy": "Бэлэн авах", "cash_sell": "Бэлэн зарах",
    "noncash_buy": "Бэлэн бус авах", "noncash_sell": "Бэлэн бус зарах",
}


def _number(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def canonical_values(payload: dict[str, Any]) -> dict[str, Decimal]:
    """Return numeric fields which are actually displayed to watchlist users."""
    detailed = ("cash_buy", "cash_sell", "noncash_buy", "noncash_sell")
    if any(payload.get(field) is not None for field in detailed):
        fields = detailed
    elif any(payload.get(field) is not None for field in ("buy", "sell")):
        fields = ("buy", "sell")
    else:
        fields = ("rate",)
    return {
        field: value for field in fields
        if (value := _number(payload.get(field))) is not None
    }


def safety_floor_percent(provider: str, symbol: str) -> Decimal:
    """Return the balanced minimum move for one supported shortlist rate."""
    if provider in _DAILY_PROVIDERS:
        return Decimal("0.75")
    if provider in {"XE", "Profinance"}:
        return Decimal("0.50")

    asset = symbol.removeprefix("P2P ").split("/", 1)[0]
    if provider == "Binance" and symbol.startswith("P2P "):
        return Decimal("1.25") if asset == "USDT" or symbol == "P2P CNY" else Decimal("2.50")
    if provider == "Rapira" and symbol == "USDT/RUB":
        return Decimal("1.25")
    return Decimal("2.50") if asset in _MAJOR_CRYPTO else Decimal("4.00")


def change_percent(previous: Decimal, current: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * Decimal("100")


def robust_volatility_percent(values: Iterable[Decimal]) -> Decimal | None:
    """Robust sigma of consecutive percentage returns, using MAD scaling."""
    series = list(values)
    if len(series) < 30:
        return None
    returns = [
        move for before, after in zip(series, series[1:])
        if (move := change_percent(before, after)) is not None
    ]
    if not returns:
        return None
    centre = median(returns)
    mad = median([abs(value - centre) for value in returns])
    return Decimal("1.4826") * mad


def sudden_change(
    provider: str, symbol: str, previous: Decimal, current: Decimal,
    history: Iterable[Decimal],
) -> tuple[Decimal, Decimal] | None:
    """Return signed move and threshold when a refresh is alert-worthy."""
    move = change_percent(previous, current)
    if move is None:
        return None
    threshold = safety_floor_percent(provider, symbol)
    sigma = robust_volatility_percent(history)
    if sigma is not None:
        threshold = max(threshold, Decimal("4") * sigma)
    return (move, threshold) if abs(move) >= threshold else None


def _format(value: Any) -> str:
    number = Decimal(str(value))
    return f"{number:,.8f}".rstrip("0").rstrip(".")


def render_alert_html(alert: dict[str, Any]) -> str:
    move = Decimal(str(alert["change_percent"]))
    direction = "ӨСӨЛТ" if move > 0 else "БУУРАЛТ"
    arrow = "📈" if move > 0 else "📉"
    provider = html.escape(str(alert["provider"]))
    symbol = html.escape(str(alert["symbol"]))
    field = _FIELD_LABELS.get(str(alert["field"]), str(alert["field"]))
    try:
        observed = datetime.fromisoformat(
            str(alert["observed_at"]).replace("Z", "+00:00")
        ).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M UB")
    except ValueError:
        observed = str(alert["observed_at"])
    return (
        f"⚠️ <b>ХАНШИЙН ОГЦОМ ӨӨРЧЛӨЛТ</b> {arrow}\n\n"
        f"<b>{provider} · {symbol}</b>\n"
        f"{html.escape(field)}: <code>{_format(alert['old_value'])}</code> → "
        f"<code>{_format(alert['new_value'])}</code>\n"
        f"<b>{direction}:</b> <code>{move:+.2f}%</code> "
        f"(босго: {Decimal(str(alert['threshold_percent'])):.2f}%)\n"
        f"<i>{html.escape(observed)}</i>\n\n"
    )
