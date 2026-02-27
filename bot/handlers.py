"""
bot.handlers – Telegram command and callback handlers.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    Application,
)

from db.supabase_client import (
    ensure_user,
    add_subscription,
    remove_subscription,
    get_subscriptions,
    clear_subscriptions,
)
from providers.base import get_provider, all_providers
from bot.keyboards import providers_keyboard, pairs_keyboard

log = logging.getLogger(__name__)


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


# ── /rates ─────────────────────────────────────────────────────────────

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

    # Group subscriptions by provider to output with blank-line separation
    grouped: dict[str, list[str]] = defaultdict(list)
    for s in subs:
        grouped[s["provider"]].append(s["symbol"])

    output_blocks: list[str] = []
    for prov_name in sorted(grouped):
        block_lines: list[str] = []
        try:
            provider = get_provider(prov_name)
        except ValueError:
            block_lines.append(f"{prov_name}: эх сурвалжаас ханш татах боломжгүй")
            output_blocks.append("\n".join(block_lines))
            continue

        for sym in grouped[prov_name]:
            try:
                data = provider.get_rate(sym)
                block_lines.extend(data.get("lines", [f"{prov_name} {sym}: –"]))
            except Exception as exc:
                log.error("Error fetching %s/%s: %s", prov_name, sym, exc)
                block_lines.append(f"{prov_name} {sym}: алдаа")

        output_blocks.append("\n".join(block_lines))

    # Join blocks with blank lines between different providers
    await update.message.reply_text("\n\n".join(output_blocks))


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
    app.add_handler(CallbackQueryHandler(callback_router))
