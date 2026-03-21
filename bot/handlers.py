"""
bot.handlers – Telegram command and callback handlers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from telegram import Update, ReplyKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
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
    is_whitelisted,
    add_to_whitelist,
    remove_from_whitelist,
    get_whitelist,
    set_cached_rate,
)
from providers.base import get_provider, all_providers
from providers.mongolbank import fetch_mongolbank_rub_rate
from providers.tdb import fetch_tdb_usd_noncash_sell
from bot.keyboards import providers_keyboard, pairs_keyboard, rate_actions_keyboard, share_menu_keyboard

log = logging.getLogger(__name__)

# Admin user IDs – only these users can manage the whitelist
ADMIN_IDS: set[int] = {1447446407, 1932946217}


async def _check_access(update: Update) -> bool:
    """Return True if the user is whitelisted, otherwise reply and return False."""
    user = update.effective_user
    if user is None:
        return False
    if is_whitelisted(user.id):
        return True
    msg = update.message or (update.callback_query and update.callback_query.message)
    if update.message:
        await update.message.reply_text("⛔ Танд энэ ботыг ашиглах эрх байхгүй байна.")
    return False


# ── Calculator reply keyboard ──────────────────────────────────────────
_CALC_KEYBOARD = ReplyKeyboardMarkup(
    [["+", "-", "*", "/", "=", "Цуцлах"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)


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
    "TDB":        '<tg-emoji emoji-id="6195193078383386584">\U0001f3e6</tg-emoji>',
    "Mongolbank": '<tg-emoji emoji-id="6194814206433303966">\U0001f1f2\U0001f1f3</tg-emoji>',
}


# ── /start ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    if not await _check_access(update):
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
        reply_markup=_CALC_KEYBOARD,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _check_access(update):
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
    if not await _check_access(update):
        return
    ensure_user(update.effective_user.id, update.effective_user.username)  # type: ignore[union-attr]
    await update.message.reply_text(
        "Валютын ханш авах эх сурвалж сонгоно уу:", reply_markup=providers_keyboard()
    )


# ── /remove (reuses same keyboard flow, handler detects del: prefix) ──

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _check_access(update):
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
    if not await _check_access(update):
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
    if not await _check_access(update):
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


async def _build_formula_section() -> list[str]:
    """Calculate and format the three formula-based rates.

    All upstream fetches run in parallel via asyncio.to_thread.

    ДЕЛЬКРАДО:  MongolBank RUB rate + 0.50%
    ТРИКУЭТРА:  (TDB Bank non-cash USD sell / CBR USD/RUB) + 1%
    RUB БЭЛЭН:  Binance P2P USDT/MNT (min) / Rapira USDT/RUB buy
    """
    # Fire all blocking fetches in parallel
    mb_fut = asyncio.to_thread(fetch_mongolbank_rub_rate)
    tdb_fut = asyncio.to_thread(fetch_tdb_usd_noncash_sell)
    cbr_fut = asyncio.to_thread(lambda: get_provider("CBR").get_rate("USD/RUB"))
    binance_fut = asyncio.to_thread(lambda: get_provider("Binance").get_rate("P2P USDT/MNT"))
    rapira_fut = asyncio.to_thread(lambda: get_provider("Rapira").get_rate("USDT/RUB"))

    mb_data, tdb_data, cbr_data, binance_data, rapira_data = await asyncio.gather(
        mb_fut, tdb_fut, cbr_fut, binance_fut, rapira_fut,
        return_exceptions=True,
    )

    lines: list[str] = []

    # ── ДЕЛЬКРАДО ──────────────────────────────────────────────────────
    try:
        if isinstance(mb_data, Exception):
            raise mb_data
        if "error" not in mb_data:
            mb_rub = mb_data["rate"]
            delcrado = mb_rub * 1.005
            lines.append(
                f"<b>ДЕЛЬКРАДО:</b>\n"
                f"  MongolBank RUB: {mb_rub:.2f} + 0.50%\n"
                f"  ▶ <code>{delcrado:.2f}</code>"
            )
        else:
            log.warning("ДЕЛЬКРАДО: MongolBank RUB rate not found")
            lines.append("<b>ДЕЛЬКРАДО:</b> алдаа (MongolBank)")
    except Exception as exc:
        log.error("Formula ДЕЛЬКРАДО error: %s", exc)
        lines.append("<b>ДЕЛЬКРАДО:</b> алдаа (MongolBank)")

    # ── ТРИКУЭТРА ─────────────────────────────────────────────────────
    try:
        if isinstance(tdb_data, Exception):
            raise tdb_data
        if isinstance(cbr_data, Exception):
            raise cbr_data
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
        if isinstance(binance_data, Exception):
            raise binance_data
        if isinstance(rapira_data, Exception):
            raise rapira_data

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
            missing = []
            if min_price is None:
                missing.append("Binance P2P")
            if rapira_buy is None:
                missing.append("Rapira")
            src = ", ".join(missing)
            log.warning("RUB БЭЛЭН: missing data from %s", src)
            lines.append(f"<b>RUB БЭЛЭН:</b> алдаа ({src})")
    except Exception as exc:
        log.error("Formula RUB БЭЛЭН error: %s", exc)
        src = "Binance P2P" if isinstance(binance_data, Exception) else "Rapira"
        lines.append(f"<b>RUB БЭЛЭН:</b> алдаа ({src})")

    return lines


# ── /calc ───────────────────────────────────────────────────────────────

async def cmd_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _check_access(update):
        return

    await update.message.reply_text("Тооцоолж байна, түр хүлээнэ үү…")

    from datetime import timezone, timedelta
    _UB_TZ = timezone(timedelta(hours=8))
    now_ub = datetime.now(_UB_TZ)
    title = (
        '<tg-emoji emoji-id="6134203997319342981">\U0001f4b8</tg-emoji> '
        f'<b>ТООЦООЛСОН ХАНШ</b>  {now_ub:%Y-%m-%d %H:%M}'
    )

    formula_lines = await _build_formula_section()
    text = title + "\n\n" + "\n\n".join(formula_lines) if formula_lines else title + "\n\nТооцоолох боломжгүй."

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _check_access(update):
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

    # ── Collect all (provider_name, symbol, provider) tasks ────────────
    fetch_jobs: list[tuple[str, str]] = []  # (prov_name, sym)
    providers_map: dict[str, Any] = {}
    for prov_name in sorted(grouped):
        try:
            providers_map[prov_name] = get_provider(prov_name)
        except ValueError:
            providers_map[prov_name] = None
        for sym in grouped[prov_name]:
            fetch_jobs.append((prov_name, sym))

    # ── Fetch all rates + formulas in parallel ────────────────────────

    async def _noop() -> None:
        return None

    rate_tasks = []
    for prov_name, sym in fetch_jobs:
        prov = providers_map.get(prov_name)
        if prov is None:
            rate_tasks.append(_noop())
        else:
            rate_tasks.append(asyncio.to_thread(prov.get_rate, sym))

    formula_task = _build_formula_section()

    all_results = await asyncio.gather(
        *rate_tasks, formula_task, return_exceptions=True
    )

    rate_results = all_results[:-1]
    formula_lines = all_results[-1]

    # ── Send each rate as a separate message ──────────────────────────
    for (prov_name, sym), data in zip(fetch_jobs, rate_results):
        emoji_tag = _PROVIDER_EMOJI.get(prov_name, "")
        header = (
            f"{emoji_tag} <b>{_escape_html(prov_name)}</b>"
            if emoji_tag
            else f"<b>{_escape_html(prov_name)}</b>"
        )

        if providers_map.get(prov_name) is None:
            await update.message.reply_text(
                f"{_escape_html(prov_name)}: эх сурвалжаас ханш татах боломжгүй",
                parse_mode=ParseMode.HTML,
            )
            continue

        if isinstance(data, Exception):
            log.error("Error fetching %s/%s: %s", prov_name, sym, data)
            await update.message.reply_text(
                f"{_escape_html(prov_name)} {_escape_html(sym)}: алдаа",
                parse_mode=ParseMode.HTML,
            )
            continue

        raw_lines = data.get("lines", [f"{prov_name} {sym}: –"])
        for line_idx, rl in enumerate(raw_lines):
            html_line = re.sub(
                r"`([^`]+)`",
                lambda m: f"<code>{m.group(1)}</code>",
                rl,
            )
            text = header + "\n" + html_line
            rate_id = f"{prov_name}:{sym}:{line_idx}"
            await update.message.reply_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=rate_actions_keyboard(rate_id),
            )

    # ── Formula-based rates – each formula as its own message ─────────
    if isinstance(formula_lines, list):
        for fi, fl in enumerate(formula_lines):
            rate_id = f"_f:{fi}"
            await update.message.reply_text(
                fl, parse_mode=ParseMode.HTML,
                reply_markup=rate_actions_keyboard(rate_id),
            )


# ── Calculator helpers ─────────────────────────────────────────────────

_OPERATORS = {"+", "-", "*", "/"}


def _extract_code_values(message: Any) -> list[float]:
    """Extract numeric values from a bot rate message.

    Tries ``code`` entities first, then falls back to scanning the raw
    text for backtick-wrapped or standalone numbers that look like rates.
    """
    values: list[float] = []
    if not message or not message.text:
        return values

    # 1. Try <code> / monospace entities (use parse_entity for correct
    #    UTF-16 offset handling when custom emoji are present)
    if message.entities:
        for entity in message.entities:
            if entity.type == "code":
                try:
                    code_text = message.parse_entity(entity)
                    values.append(float(code_text.replace(",", "")))
                except (ValueError, AttributeError):
                    pass
    if values:
        return values

    # 2. Fallback: find numbers in the message text (colon-separated values,
    #    backtick-wrapped, or large decimals that look like rates)
    for m in re.finditer(r"`([^`]+)`", message.text):
        try:
            values.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    if values:
        return values

    # 3. Last resort: any decimal number ≥ 1
    for m in re.finditer(r"(\d[\d,]*\.?\d*)", message.text):
        try:
            v = float(m.group(1).replace(",", ""))
            if v >= 1:
                values.append(v)
        except ValueError:
            pass
    return values


def _tokenize_input(text: str) -> list:
    """Parse user text into a list of floats, operator strings, ``=``,
    and percentage tuples ``("pct", multiplier, label)``.

    Percentage syntax: ``+0.5%`` becomes ``("pct", 1.005, "+0.5%")``.
    Percentages are applied to the running total, not via standard order
    of operations.
    """
    tokens: list = []
    pattern = r"([+-]\d+(?:[.,]\d+)?%|\d+(?:[.,]\d+)?%|\d+(?:[.,]\d+)?|[+\-*/=])"
    for match in re.finditer(pattern, text):
        tok = match.group(1)
        if tok.endswith("%"):
            pct_val = float(tok[:-1].replace(",", "."))
            multiplier = 1 + (pct_val / 100)
            tokens.append(("pct", multiplier, tok))
        elif tok in "+-*/=":
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
        if isinstance(t, tuple) and t[0] == "pct":
            parts.append(t[2])  # original label like "+0.5%"
        elif isinstance(t, float):
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
    """Reply-based calculator.

    Flow:
      1. User replies to a bot rate message (e.g. showing 5000) with an
         operator like ``/``  →  bot stores ``5000 /`` and waits.
      2. User replies to another rate message (e.g. 5) with ``=``
         →  bot evaluates ``5000 / 5 = 1000``.
      -  Or the user replies with another operator to keep chaining.
      -  Or the user types a number directly (not replying) while active.
    """
    if update.message is None or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return
    if not await _check_access(update):
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
            await update.message.reply_text(
                "❌ Тооцоолол цуцлагдлаа.",
            )
        return

    input_tokens = _tokenize_input(text)

    # ── When replying to a bot rate message, extract the rate value
    #    from the replied message and weave it into input_tokens. ─────
    if is_rate_reply:
        code_values = _extract_code_values(replied)
        # Check if the user explicitly typed a leading number.
        # Percentage syntax like "+0.5%" produces a pct tuple, not a
        # user-typed number, so we only check for plain floats.
        starts_with_number = bool(input_tokens) and isinstance(input_tokens[0], float)

        if code_values and not starts_with_number:
            if len(code_values) == 1:
                rate_val = code_values[0]
            else:
                # Multiple values (e.g. Buy & Sell in one message – shouldn't
                # happen now that each line is its own message, but just in case)
                vals = ", ".join(_format_number(v) for v in code_values)
                await update.message.reply_text(
                    f"Олон утга байна: {vals}\n"
                    f"Аль утгыг ашиглахаа тоогоор бичнэ үү (жишээ: 95.50 /)",
                )
                user_data["calc_active"] = True
                user_data["calc_tokens"] = tokens
                return

            # Decide where to place the extracted rate value:
            # • If expression needs a number next (empty or ends with op),
            #   insert the rate before the operator/equals the user typed.
            # • Otherwise check for compound operators (+=, -=, *=, /=)
            #   and insert rate_val between operator and "=".
            needs_number = (not tokens) or (
                tokens and not isinstance(tokens[-1], float)
            )
            if needs_number:
                input_tokens.insert(0, rate_val)
            else:
                # Compound operator support: e.g. user types "+=" replying
                # to a rate → insert that rate between the op and "=".
                for i in range(len(input_tokens) - 1):
                    if input_tokens[i] in _OPERATORS and input_tokens[i + 1] == "=":
                        input_tokens.insert(i + 1, rate_val)
                        break

        elif not code_values and not starts_with_number and not active:
            # Replied to a bot message with no extractable rate and no number
            await update.message.reply_text(
                "Энэ мессежнээс ханш олдсонгүй. "
                "Ханш агуулсан мессежэд хариулна уу."
            )
            return

    if not input_tokens:
        if active:
            await update.message.reply_text(
                "Зөв тоо, оператор тэмдэг (+, -, *, /) эсвэл '=' тэмдэг оруулна уу."
            )
        return

    # ── Process each token ──────────────────────────────────────────
    step_display = ""  # human-readable description built during pct steps

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

            result_str = _format_number(result)
            if len(tokens) > 1:
                formula = _format_expression(tokens)
                display = f"{formula} = <code>{result_str}</code>"
            elif step_display:
                display = f"{step_display}\n\nХариу: <code>{result_str}</code>"
            else:
                display = f"Хариу: <code>{result_str}</code>"

            await update.message.reply_text(
                f"📐 <b>Тооцоолол</b>\n\n{display}",
                parse_mode=ParseMode.HTML,
                reply_markup=share_menu_keyboard(display),
            )
            user_data["calc_tokens"] = []
            user_data["calc_active"] = False
            return

        elif isinstance(tok, tuple) and tok[0] == "pct":
            # Percentage: evaluate everything so far, apply multiplier
            _, multiplier, label = tok
            if not tokens or not isinstance(tokens[-1], float):
                await update.message.reply_text("Оператор тэмдэгийн өмнө тоо оруулна уу.")
                return
            try:
                subtotal = _evaluate_tokens(tokens)
            except Exception:
                await update.message.reply_text("❌ Тооцоолоход алдаа гарлаа.")
                user_data["calc_tokens"] = []
                user_data["calc_active"] = False
                return
            result = subtotal * multiplier

            # Build a readable description of this step
            if len(tokens) > 1:
                step_display = (
                    f"{_format_expression(tokens)} = {_format_number(subtotal)}"
                    f" {label} = {_format_number(result)}"
                )
            else:
                step_display = (
                    f"{_format_number(subtotal)} {label} = {_format_number(result)}"
                )

            # Replace all tokens with the new result
            tokens = [result]

        elif isinstance(tok, float):
            if tokens and isinstance(tokens[-1], float):
                await update.message.reply_text(
                    "Хоёр тооны хооронд оператор тэмдэг(+, -, *, /) оруулна уу."
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

    if step_display:
        # We just processed a percentage — show the full process
        if tokens and isinstance(tokens[-1], float):
            await update.message.reply_text(
                f"✅ {step_display}\n"
                f"Оператор тэмдэг (+, -, *, /) эсвэл '=' тэмдэг оруулна уу.",
                reply_markup=_CALC_KEYBOARD,
            )
        else:
            last_op = tokens[-1] if tokens else ""
            op_char = {"*": "×", "/": "÷"}.get(last_op, last_op)
            await update.message.reply_text(
                f"✅ {step_display} {op_char} ...\n"
                f"Дараагийн ханш/тоо оруулна уу эсвэл '=' тэмдэг илгээж тооцоолно уу.",
                reply_markup=_CALC_KEYBOARD,
            )
    else:
        formula = _format_expression(tokens)
        if tokens and isinstance(tokens[-1], float):
            await update.message.reply_text(
                f"✅ {formula}\n"
                f"Оператор тэмдэг (+, -, *, /) эсвэл '=' тэмдэг оруулна уу.",
                reply_markup=_CALC_KEYBOARD,
            )
        else:
            await update.message.reply_text(
                f"✅ {formula} ...\n"
                f"Дараагийн ханш/тоо оруулна уу эсвэл '=' тэмдэг илгээж тооцоолно уу.",
                reply_markup=_CALC_KEYBOARD,
            )


# ── Callback-query router (inline keyboard taps) ──────────────────────

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    if not await _check_access(update):
        await query.answer("⛔ Эрх байхгүй", show_alert=True)
        return

    data = query.data or ""

    # Defer query.answer() for update button so we can show result after fetch
    if not data.startswith("upd:"):
        await query.answer()
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

    elif data.startswith("upd:"):
        rate_id = data[4:]
        _UB_TZ = timezone(timedelta(hours=8))
        now_ub = datetime.now(_UB_TZ)
        ts_line = f"\n<i>🔄 {now_ub:%H:%M:%S}</i>"

        if rate_id.startswith("_f:"):
            # Formula rate update
            idx = int(rate_id.split(":")[1])
            try:
                formula_lines = await _build_formula_section()
                if idx < len(formula_lines):
                    text = formula_lines[idx] + ts_line
                else:
                    text = "Алдаа: тооцоолох боломжгүй."
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=rate_actions_keyboard(rate_id),
                )
                await query.answer("✅ Шинэчлэгдлээ")
            except Exception as exc:
                log.error("Formula update error %s: %s", rate_id, exc)
                await query.answer("Шинэчлэхэд алдаа гарлаа", show_alert=True)
        else:
            # Provider rate update – fetch fresh data (bypass cache)
            parts = rate_id.split(":")
            prov_name = parts[0]
            sym = parts[1]
            line_idx = int(parts[2]) if len(parts) > 2 else 0
            try:
                prov = get_provider(prov_name)
                data_result = await asyncio.to_thread(prov.fetch, sym)
                # Update the cache with fresh data
                try:
                    set_cached_rate(prov_name, sym, data_result)
                except Exception:
                    pass
                emoji_tag = _PROVIDER_EMOJI.get(prov_name, "")
                header = (
                    f"{emoji_tag} <b>{_escape_html(prov_name)}</b>"
                    if emoji_tag
                    else f"<b>{_escape_html(prov_name)}</b>"
                )
                raw_lines = data_result.get("lines", [f"{prov_name} {sym}: –"])
                rl = raw_lines[line_idx] if line_idx < len(raw_lines) else raw_lines[0]
                html_line = re.sub(
                    r"`([^`]+)`",
                    lambda m: f"<code>{m.group(1)}</code>",
                    rl,
                )
                text = header + "\n" + html_line + ts_line
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=rate_actions_keyboard(rate_id),
                )
                await query.answer("✅ Шинэчлэгдлээ")
            except Exception as exc:
                log.error("Rate update error %s: %s", rate_id, exc)
                await query.answer("Шинэчлэхэд алдаа гарлаа", show_alert=True)

    elif data.startswith("shr:"):
        pass  # share is handled via switch_inline_query + inline_query_handler

    elif data == "menu":
        await query.message.reply_text(
            "/add  – валютын хослол нэмэх\n"
            "/list – хадгалсан валютын жагсаалт\n"
            "/rates – ханшийн жагсаалт авах\n"
            "/calc – тооцоолсон ханш\n"
            "/remove – валютын хослол хасах\n"
            "/clear – валютын жагсаалт устгах\n"
            "/help – тусламж",
        )


# ── Hidden admin commands: /wl_add, /wl_remove, /wl_list ──────────────

async def cmd_wl_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user = update.effective_user
    if user is None or user.id not in ADMIN_IDS:
        return  # silently ignore for non-admins
    args = ctx.args
    if not args:
        await update.message.reply_text("Хэрэглэгчийн ID оруулна уу: /wl_add <user_id>")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("ID тоо байх ёстой.")
        return
    if add_to_whitelist(target_id):
        await update.message.reply_text(f"✅ {target_id} whitelist-д нэмэгдлээ.")
    else:
        await update.message.reply_text(f"{target_id} аль хэдийн whitelist-д байна.")


async def cmd_wl_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user = update.effective_user
    if user is None or user.id not in ADMIN_IDS:
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Хэрэглэгчийн ID оруулна уу: /wl_remove <user_id>")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("ID тоо байх ёстой.")
        return
    if remove_from_whitelist(target_id):
        await update.message.reply_text(f"❌ {target_id} whitelist-ээс хасагдлаа.")
    else:
        await update.message.reply_text(f"{target_id} whitelist-д байхгүй байна.")


async def cmd_wl_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    user = update.effective_user
    if user is None or user.id not in ADMIN_IDS:
        return
    ids = get_whitelist()
    if not ids:
        await update.message.reply_text("Whitelist хоосон байна.")
        return
    lines = [str(uid) for uid in ids]
    await update.message.reply_text("Whitelist:\n" + "\n".join(lines))


# ── Inline query handler (share via @botname) ─────────────────────

async def inline_query_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries triggered by the Share button.

    The query string is the rate_id. We fetch the rate, build a formatted
    InlineQueryResultArticle so the user taps it and it sends the rate
    to the chosen chat with 'via @botname' attribution.
    """
    iq = update.inline_query
    if iq is None:
        return

    rate_id = (iq.query or "").strip()
    if not rate_id:
        await iq.answer([], cache_time=0)
        return

    try:
        if rate_id.startswith("_t:"):
            # Direct text share (e.g. calc results)
            html_text = f"📐 <b>Тооцоолол</b>\n\n{rate_id[3:]}"
        elif rate_id.startswith("_f:"):
            idx = int(rate_id.split(":")[1])
            formula_lines = await _build_formula_section()
            if idx < len(formula_lines):
                html_text = formula_lines[idx]
            else:
                html_text = "Ханш олдсонгүй."
        else:
            parts = rate_id.split(":")
            prov_name = parts[0]
            sym = parts[1]
            line_idx = int(parts[2]) if len(parts) > 2 else 0
            prov = get_provider(prov_name)
            rate_data = await asyncio.to_thread(prov.get_rate, sym)
            emoji_tag = _PROVIDER_EMOJI.get(prov_name, "")
            header = (
                f"{emoji_tag} <b>{_escape_html(prov_name)}</b>"
                if emoji_tag
                else f"<b>{_escape_html(prov_name)}</b>"
            )
            raw_lines = rate_data.get("lines", [f"{prov_name} {sym}: \u2013"])
            rl = raw_lines[line_idx] if line_idx < len(raw_lines) else raw_lines[0]
            html_line = re.sub(
                r"`([^`]+)`",
                lambda m: f"<code>{m.group(1)}</code>",
                rl,
            )
            html_text = header + "\n" + html_line
    except Exception as exc:
        log.error("Inline query error for %s: %s", rate_id, exc)
        html_text = "Ханш татахад алдаа гарлаа."

    # Strip <tg-emoji> tags (custom emoji won't render in inline results)
    clean_html = re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', html_text)

    # Plain text for the result card title / description
    plain = re.sub(r"<[^>]+>", "", clean_html)
    plain_lines = plain.split("\n")
    title = plain_lines[0][:80]
    description = "\n".join(plain_lines[1:])[:120] or "Ханш хуваалцах"

    results = [
        InlineQueryResultArticle(
            id=rate_id[:64],
            title=title,
            description=description,
            input_message_content=InputTextMessageContent(
                message_text=clean_html,
                parse_mode=ParseMode.HTML,
            ),
        )
    ]
    await iq.answer(results, cache_time=0)


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
    app.add_handler(CommandHandler("wl_add", cmd_wl_add))
    app.add_handler(CommandHandler("wl_remove", cmd_wl_remove))
    app.add_handler(CommandHandler("wl_list", cmd_wl_list))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
