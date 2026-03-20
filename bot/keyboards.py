"""
bot.keyboards – Inline-keyboard builders for provider / pair selection.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, SwitchInlineQueryChosenChat

from providers.base import all_providers, get_provider


# ── Callback data prefixes ─────────────────────────────────────────────
# prov:<name>           – user selected a provider
# add:<provider>:<sym>  – add pair to watchlist
# del:<provider>:<sym>  – remove pair from watchlist
# back:providers        – go back to provider list
# noop                  – placeholder, do nothing


def providers_keyboard() -> InlineKeyboardMarkup:
    """Top-level keyboard listing every registered provider."""
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"prov:{name}")]
        for name in sorted(all_providers())
    ]
    return InlineKeyboardMarkup(buttons)


def pairs_keyboard(provider_name: str, subscribed: set[str] | None = None) -> InlineKeyboardMarkup:
    """Second-level keyboard showing available pairs for a provider.

    Pairs already in the user's watchlist are marked with ✅ and their
    callback switches to ``del:`` so a tap removes them.
    """
    subscribed = subscribed or set()
    prov = get_provider(provider_name)
    buttons: list[list[InlineKeyboardButton]] = []

    row: list[InlineKeyboardButton] = []
    for sym, label in prov.PAIRS.items():
        if sym in subscribed:
            text = f"✅ {sym}"
            cb = f"del:{provider_name}:{sym}"
        else:
            text = f"  {sym}"
            cb = f"add:{provider_name}:{sym}"
        row.append(InlineKeyboardButton(text, callback_data=cb))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append(
        [InlineKeyboardButton("⬅️ Буцах", callback_data="back:providers")]
    )
    return InlineKeyboardMarkup(buttons)


def rate_actions_keyboard(rate_id: str) -> InlineKeyboardMarkup:
    """Inline keyboard with Update, Share, and Menu buttons for rate messages."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Шинэчлэх", callback_data=f"upd:{rate_id}"),
        InlineKeyboardButton(
            "↗️ Хуваалцах",
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=rate_id,
                allow_user_chats=True,
                allow_group_chats=True,
                allow_channel_chats=True,
                allow_bot_chats=False,
            ),
        ),
        InlineKeyboardButton("📋 Меню", callback_data="menu"),
    ]])
