"""
bot.handlers – Telegram command and callback handlers.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Application,
    filters,
)

from db.supabase_client import (
    ensure_user,
    add_subscription,
    remove_subscription,
    get_subscriptions,
    clear_subscriptions,
)
from providers.base import get_provider, all_providers
from providers.mongolbank import fetch_mongolbank_rub_rate
from providers.tdb import fetch_tdb_usd_noncash_sell
from bot.keyboards import providers_keyboard, pairs_keyboard

log = logging.getLogger(__name__)


# ── Custom emoji mapping (pack: oyunsratesemoji_by_TgEmodziBot) ────────
# Each value is a tg-emoji placeholder that Telegram renders as the custom
# emoji when sent with parse_mode=HTML.
_PROVIDER_EMOJI: dict[str, str] = {
    "Rapira":     '<tg-emoji emoji-id="6134317058038439469">\U0001f4b5</tg-emoji>',
    "XE":         '<tg-emoji emoji-id="6133907906568921277">\U0001f4b8</tg-emoji>',
    "Binance":    '<tg-emoji emoji-id="6134390931475930256">\U0001f4b0</tg-emoji>',
    "BOC":        '<tg-emoji emoji-id="6134257491137010663">\U0001f1e8\U0001f1f3</tg-emoji>',
    "CBR":        '<tg-emoji emoji-id="6136465649788001541">\U0001f1f7\U0001f1fa</tg-emoji>',
    "Profinance": '<tg-emoji emoji-id="6134027577242689559">\U0001f4ca</tg-emoji>',
    "GRX":        '<tg-emoji emoji-id="6134203997319342981">\U0001f4b8</tg-emoji>',
}


# ── /start ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    ensure_user(user.id, user.username)
    await update.message.reply_text(
        "Дараах коммандуудыг ашиглан бот ашиглана уу\n\n"
        "/add  – валютын хослол нэмэх\n"
        "/list – хадгалсан валютын жагсаалт\n"
        "/rates – ханшийн жагсаалт авах\n"
        "/oyuns – ханшийн жагсаалт авах\n"
        "/calc – тооцоолсон ханш\n"
        "/remove – валютын хослол хасах\n"
        "/clear – валютын жагсаалт устгах\n"
        "/help – тусламж",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "/add  – валютын хослол нэмэх\n"
        "/list – хадгалсан валютын жагсаалт\n"
        "/rates – ханшийн жагсаалт авах\n"
        "/oyuns – ханшийн жагсаалт авах\n"
        "/calc – тооцоолсон ханш\n"
        "/remove – валютын хослол хасах\n"
        "/clear – валютын жагсаалт устгах\n"
        "/help – тусламж",

    )


# ── /add ───────────────────────────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    ensure_user(update.effective_user.id, update.effective_user.username)  # type: ignore[union-attr]
    await update.message.reply_text(
        "Валютын ханш авах эх сурвалж сонгоно уу:", reply_markup=providers_keyboard()
    )


# ── /remove (reuses same keyboard flow, handler detects del: prefix) ──

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user_id = update.effective_user.id  # type: ignore[union-attr]
    subs = get_subscriptions(user_id)
    if not subs:
        await update.message.reply_text("Жагсаалт хоосон байна.")
        return
    await update.message.reply_text(
        "Хасах валютын ханшийн эх сурвалж сонгоно уу:", reply_markup=providers_keyboard()
    )


# ── /list ──────────────────────────────────────────────────────────────

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user_id = update.effective_user.id  # type: ignore[union-attr]
    subs = get_subscriptions(user_id)
    if not subs:
        await update.message.reply_text("Жагсаалт хоосон байна. /add ашиглан нэмнэ үү.")
        return

    grouped: dict[str, list[str]] = defaultdict(list)
    for s in subs:
        grouped[s["provider"]].append(s["symbol"])

    lines: list[str] = []
    for prov_name in sorted(grouped):
        symbols = ", ".join(grouped[prov_name])
        lines.append(f"{prov_name}: {symbols}")

    await update.message.reply_text("\n".join(lines))


# ── /clear ─────────────────────────────────────────────────────────────

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user_id = update.effective_user.id  # type: ignore[union-attr]
    count = clear_subscriptions(user_id)
    await update.message.reply_text(
        f"{count} хослол жагсаалтаас хасагдлаа."
    )


# ── /rates  (alias: /oyuns) ─────────────────────────────────────────────

def _escape_html(text: str) -> str:
    """Escape HTML special chars in text (but not our tags)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_formula_section() -> list[str]:
    """Calculate and format the three formula-based rates.

    ДЕЛЬКРАДО:  MongolBank RUB rate + 0.50%
    ТРИКУЭТРА:  (TDB Bank non-cash USD sell / CBR USD/RUB) + 1%
    RUB БЭЛЭН:  Binance P2P USDT/MNT (min) / Rapira USDT/RUB buy
    """
    lines: list[str] = []

    # ── ДЕЛЬКРАДО ──────────────────────────────────────────────────────
    try:
        mb_data = fetch_mongolbank_rub_rate()
        if "error" not in mb_data:
            mb_rub = mb_data["rate"]
            delcrado = mb_rub * 1.005
            lines.append(
                f"<b>ДЕЛЬКРАДО:</b>\n"
                f"  MongolBank RUB: {mb_rub:.2f} + 0.50%\n"
                f"  ▶ <code>{delcrado:.2f}</code>"
            )
        else:
            lines.append("<b>ДЕЛЬКРАДО:</b> алдаа")
    except Exception as exc:
        log.error("Formula ДЕЛЬКРАДО error: %s", exc)
        lines.append("<b>ДЕЛЬКРАДО:</b> алдаа")

    # ── ТРИКУЭТРА ─────────────────────────────────────────────────────
    try:
        tdb_data = fetch_tdb_usd_noncash_sell()
        cbr_provider = get_provider("CBR")
        cbr_data = cbr_provider.get_rate("USD/RUB")

        if "error" not in tdb_data and cbr_data.get("rate"):
            tdb_usd = tdb_data["rate"]
            cbr_usd_rub = cbr_data["rate"]
            triquetra = (tdb_usd / cbr_usd_rub) * 1.01
            lines.append(
                f"<b>ТРИКУЭТРА:</b>\n"
                f"  TDB USD sell: {tdb_usd:.2f} / CBR USD/RUB: {cbr_usd_rub:.4f} + 1%\n"
                f"  ▶ <code>{triquetra:.2f}</code>"
            )
        else:
            lines.append("<b>ТРИКУЭТРА:</b> алдаа")
    except Exception as exc:
        log.error("Formula ТРИКУЭТРА error: %s", exc)
        lines.append("<b>ТРИКУЭТРА:</b> алдаа")

    # ── RUB БЭЛЭН ─────────────────────────────────────────────────────
    try:
        binance_provider = get_provider("Binance")
        binance_data = binance_provider.get_rate("P2P USDT/MNT")
        rapira_provider = get_provider("Rapira")
        rapira_data = rapira_provider.get_rate("USDT/RUB")

        min_price = binance_data.get("min_price")
        rapira_buy = rapira_data.get("buy") or rapira_data.get("bid")

        if min_price is not None and rapira_buy is not None:
            min_price_f = float(min_price)
            rapira_buy_f = float(rapira_buy)
            rub_belen = min_price_f / rapira_buy_f
            lines.append(
                f"<b>RUB БЭЛЭН:</b>\n"
                f"  Binance USDT/MNT: {min_price_f:.2f} / Rapira Buy: {rapira_buy_f:.2f}\n"
                f"  ▶ <code>{rub_belen:.2f}</code>"
            )
        else:
            lines.append("<b>RUB БЭЛЭН:</b> алдаа")
    except Exception as exc:
        log.error("Formula RUB БЭЛЭН error: %s", exc)
        lines.append("<b>RUB БЭЛЭН:</b> алдаа")

    return lines


# ── /calc ───────────────────────────────────────────────────────────────

async def cmd_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text("Тооцоолж байна, түр хүлээнэ үү…")

    from datetime import timezone, timedelta
    _UB_TZ = timezone(timedelta(hours=8))
    now_ub = datetime.now(_UB_TZ)
    title = (
        '<tg-emoji emoji-id="6134203997319342981">\U0001f4b8</tg-emoji> '
        f'<b>ТООЦООЛСОН ХАНШ</b>  {now_ub:%Y-%m-%d %H:%M}'
    )

    formula_lines = _build_formula_section()
    text = title + "\n\n" + "\n\n".join(formula_lines) if formula_lines else title + "\n\nТооцоолох боломжгүй."

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user_id = update.effective_user.id  # type: ignore[union-attr]
    subs = get_subscriptions(user_id)
    if not subs:
        await update.message.reply_text(
            "Жагсаалт хоосон байна. Эхлээд /add ашиглана уу."
        )
        return

    await update.message.reply_text("Ханш татаж байна, түр хүлээнэ үү…")

    # Group subscriptions by provider
    grouped: dict[str, list[str]] = defaultdict(list)
    for s in subs:
        grouped[s["provider"]].append(s["symbol"])

    # Send each rate as a separate message
    for prov_name in sorted(grouped):
        emoji_tag = _PROVIDER_EMOJI.get(prov_name, "")
        header = (
            f"{emoji_tag} <b>{_escape_html(prov_name)}</b>"
            if emoji_tag
            else f"<b>{_escape_html(prov_name)}</b>"
        )

        try:
            provider = get_provider(prov_name)
        except ValueError:
            await update.message.reply_text(
                f"{_escape_html(prov_name)}: эх сурвалжаас ханш татах боломжгүй",
                parse_mode=ParseMode.HTML,
            )
            continue

        for sym in grouped[prov_name]:
            try:
                data = provider.get_rate(sym)
                raw_lines = data.get("lines", [f"{prov_name} {sym}: –"])
                html_lines: list[str] = []
                for rl in raw_lines:
                    html_line = re.sub(
                        r"`([^`]+)`",
                        lambda m: f"<code>{m.group(1)}</code>",
                        rl,
                    )
                    html_lines.append(html_line)
                text = header + "\n" + "\n".join(html_lines)
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            except Exception as exc:
                log.error("Error fetching %s/%s: %s", prov_name, sym, exc)
                await update.message.reply_text(
                    f"{_escape_html(prov_name)} {_escape_html(sym)}: алдаа",
                    parse_mode=ParseMode.HTML,
                )

    # Formula-based rates – each formula as its own message
    formula_lines = _build_formula_section()
    for fl in formula_lines:
        await update.message.reply_text(fl, parse_mode=ParseMode.HTML)


# ── Calculator helpers ─────────────────────────────────────────────────

_OPERATORS = {"+", "-", "*", "/"}


def _extract_code_values(message: Any) -> list[float]:
    """Extract numeric values from ``code`` entities in a Telegram message."""
    values: list[float] = []
    if not message or not message.text or not message.entities:
        return values
    for entity in message.entities:
        if entity.type == "code":
            code_text = message.text[entity.offset : entity.offset + entity.length]
            try:
                values.append(float(code_text.replace(",", "")))
            except ValueError:
                pass
    return values


def _tokenize_input(text: str) -> list:
    """Parse user text into a list of floats, operator strings, and ``=``."""
    tokens: list = []
    for match in re.finditer(r"(\d+(?:[.,]\d+)?|[+\-*/=])", text):
        tok = match.group(1)
        if tok in "+-*/=":
            tokens.append(tok)
        else:
            tokens.append(float(tok.replace(",", ".")))
    return tokens


def _format_number(val: float) -> str:
    """Format a float for display – drop unnecessary trailing zeros."""
    if val == int(val) and abs(val) < 1e15:
        return str(int(val))
    return f"{val:.4f}".rstrip("0").rstrip(".")


def _format_expression(tokens: list) -> str:
    """Render a token list as a readable math expression."""
    parts: list[str] = []
    for t in tokens:
        if isinstance(t, float):
            parts.append(_format_number(t))
        elif t == "*":
            parts.append("×")
        elif t == "/":
            parts.append("÷")
        else:
            parts.append(str(t))
    return " ".join(parts)


def _evaluate_tokens(tokens: list) -> float:
    """Evaluate ``[num, op, num, …]`` with standard order of operations."""
    work = list(tokens)
    # Pass 1: * and /
    i = 1
    while i < len(work):
        if work[i] in ("*", "/"):
            left, right = work[i - 1], work[i + 1]
            if work[i] == "*":
                val = left * right
            else:
                if right == 0:
                    raise ZeroDivisionError
                val = left / right
            work[i - 1 : i + 2] = [val]
        else:
            i += 2
    # Pass 2: + and -
    while len(work) > 1:
        left, op, right = work[0], work[1], work[2]
        val = left + right if op == "+" else left - right
        work[0:3] = [val]
    return work[0]


# ── Calculator message handler (state machine) ────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Process text messages for the reply-based calculator."""
    if update.message is None or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    user_data = ctx.user_data
    tokens: list = user_data.get("calc_tokens", [])
    active: bool = user_data.get("calc_active", False)
    replied = update.message.reply_to_message

    is_rate_reply = (
        replied is not None
        and replied.from_user is not None
        and replied.from_user.id == ctx.bot.id
    )

    # Not in calc mode and not replying to a bot message → ignore
    if not active and not is_rate_reply:
        return

    # Cancel keywords
    if text.lower() in ("c", "cancel", "х", "цуцлах"):
        if active:
            user_data["calc_tokens"] = []
            user_data["calc_active"] = False
            await update.message.reply_text("❌ Тооцоолол цуцлагдлаа.")
        return

    input_tokens = _tokenize_input(text)

    # ── Reply to a rate message: prepend the rate value when the user
    #    sent only an operator (no explicit number). ──────────────────
    if is_rate_reply and input_tokens:
        code_values = _extract_code_values(replied)
        has_number = any(isinstance(t, float) for t in input_tokens)

        if not has_number and code_values:
            if len(code_values) == 1:
                input_tokens.insert(0, code_values[0])
            else:
                vals = ", ".join(_format_number(v) for v in code_values)
                await update.message.reply_text(
                    f"Олон утга байна: {vals}\n"
                    f"Аль утгыг ашиглахаа тоогоор бичнэ үү (жишээ: 95.50 *)",
                )
                user_data["calc_active"] = True
                user_data["calc_tokens"] = tokens
                return

    if not input_tokens:
        if active:
            await update.message.reply_text(
                "Зөв тоо, оператор (+, -, *, /) эсвэл = оруулна уу."
            )
        return

    # ── Process each token ──────────────────────────────────────────
    for tok in input_tokens:
        if tok == "=":
            if not tokens or not isinstance(tokens[-1], float):
                await update.message.reply_text(
                    "Илэрхийлэл дутуу байна. Тоо оруулна уу."
                )
                return
            try:
                result = _evaluate_tokens(tokens)
            except ZeroDivisionError:
                await update.message.reply_text("❌ Тэгд хуваах боломжгүй.")
                user_data["calc_tokens"] = []
                user_data["calc_active"] = False
                return
            except Exception as exc:
                log.error("Calc error: %s", exc)
                await update.message.reply_text("❌ Тооцоолоход алдаа гарлаа.")
                user_data["calc_tokens"] = []
                user_data["calc_active"] = False
                return

            formula = _format_expression(tokens)
            result_str = _format_number(result)
            await update.message.reply_text(
                f"📐 <b>Тооцоолол</b>\n\n"
                f"Томьёо: {formula}\n"
                f"Хариу: <code>{result_str}</code>",
                parse_mode=ParseMode.HTML,
            )
            user_data["calc_tokens"] = []
            user_data["calc_active"] = False
            return

        elif isinstance(tok, float):
            if tokens and isinstance(tokens[-1], float):
                await update.message.reply_text(
                    "Хоёр тооны хооронд оператор (+, -, *, /) оруулна уу."
                )
                return
            tokens.append(tok)

        elif tok in _OPERATORS:
            if not tokens or not isinstance(tokens[-1], float):
                await update.message.reply_text("Операторын өмнө тоо оруулна уу.")
                return
            tokens.append(tok)

    # ── Save state & acknowledge ────────────────────────────────────
    user_data["calc_tokens"] = tokens
    user_data["calc_active"] = True

    formula = _format_expression(tokens)
    if tokens and isinstance(tokens[-1], float):
        await update.message.reply_text(
            f"✅ {formula}\n"
            f"Оператор (+, -, *, /) эсвэл = оруулна уу.",
        )
    else:
        await update.message.reply_text(
            f"✅ {formula} ...\n"
            f"Дараагийн ханш/тоо оруулна уу эсвэл = дарж тооцоолно.",
        )


# ── Callback-query router (inline keyboard taps) ──────────────────────

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = query.data or ""
    user_id = update.effective_user.id  # type: ignore[union-attr]

    if data.startswith("prov:"):
        # Show pairs for chosen provider
        provider_name = data.split(":", 1)[1]
        subs = get_subscriptions(user_id)
        subscribed = {
            s["symbol"] for s in subs if s["provider"] == provider_name
        }
        await query.edit_message_text(
            f"{provider_name} валютын хослол сонгоно уу:",
            reply_markup=pairs_keyboard(provider_name, subscribed),
        )

    elif data.startswith("add:"):
        _, provider_name, sym = data.split(":", 2)
        added = add_subscription(user_id, provider_name, sym)
        status = "✅ Нэмэгдлээ" if added else "Аль хэдийн нэмэгдсэн байна"

        subs = get_subscriptions(user_id)
        subscribed = {
            s["symbol"] for s in subs if s["provider"] == provider_name
        }
        await query.edit_message_text(
            f"{status}: {provider_name} {sym}\n\nЦааш сонгох эсвэл буцах:",
            reply_markup=pairs_keyboard(provider_name, subscribed),
        )

    elif data.startswith("del:"):
        _, provider_name, sym = data.split(":", 2)
        removed = remove_subscription(user_id, provider_name, sym)
        status = "❌ Хасагдлаа" if removed else "Жагсаалтад байхгүй"

        subs = get_subscriptions(user_id)
        subscribed = {
            s["symbol"] for s in subs if s["provider"] == provider_name
        }
        await query.edit_message_text(
            f"{status}: {provider_name} {sym}\n\nЦааш сонгох эсвэл буцах:",
            reply_markup=pairs_keyboard(provider_name, subscribed),
        )

    elif data == "back:providers":
        await query.edit_message_text(
            "Эх сурвалж сонгоно уу:", reply_markup=providers_keyboard()
        )


# ── Register everything on the Application ─────────────────────────────

def register_handlers(app: Application) -> None:  # type: ignore[type-arg]
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("rates", cmd_rates))
    app.add_handler(CommandHandler("oyuns", cmd_rates))
    app.add_handler(CommandHandler("calc", cmd_calc))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
