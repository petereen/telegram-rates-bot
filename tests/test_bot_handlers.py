import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers import (
    _handle_mentioned_calculation,
    inline_query_handler,
    _shortlist_calculation_html,
    cmd_calc,
)
from services.group_calculator import ShortlistCalculation


class _Message:
    def __init__(self) -> None:
        self.replies: list[tuple[tuple, dict]] = []

    async def reply_text(self, *args, **kwargs) -> None:
        self.replies.append((args, kwargs))


class _Update:
    def __init__(self) -> None:
        self.message = _Message()
        self.effective_user = type("User", (), {"id": 1})()


class _Context:
    def __init__(self) -> None:
        self.user_data: dict = {}
        self.bot = type("Bot", (), {"username": "rates_bot"})()


class _InlineQuery:
    def __init__(self) -> None:
        self.query = ""
        self.from_user = type("User", (), {"id": 1})()
        self.answers: list[tuple[tuple, dict]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answers.append((args, kwargs))


class _InlineUpdate:
    def __init__(self) -> None:
        self.inline_query = _InlineQuery()


class BotHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_calc_starts_numeric_mode_without_fetching_rates(self) -> None:
        update = _Update()
        context = _Context()

        with patch(
            "bot.handlers._check_access", new=AsyncMock(return_value=True)
        ), patch(
            "bot.handlers._build_formula_items",
            new=AsyncMock(side_effect=AssertionError("/calc fetched rates")),
        ):
            await cmd_calc(update, context)

        self.assertEqual(context.user_data, {"calc_tokens": [], "calc_active": True})
        self.assertEqual(len(update.message.replies), 1)
        args, kwargs = update.message.replies[0]
        self.assertIn("Тоогоо оруулна уу", args[0])
        self.assertNotIn("ханш", args[0].lower())
        self.assertIsNotNone(kwargs["reply_markup"])

    async def test_empty_mention_does_not_list_rates_or_formulas(self) -> None:
        update = _Update()
        context = _Context()

        with patch(
            "bot.handlers.get_subscriptions",
            side_effect=AssertionError("mention listed rates"),
        ):
            await _handle_mentioned_calculation(update, context, "")

        args, _ = update.message.replies[0]
        self.assertIn("100 + 20", args[0])
        self.assertNotIn("ханш", args[0].lower())
        self.assertNotIn("томьёо", args[0].lower())

    def test_mentioned_calculation_renders_only_the_result(self) -> None:
        rendered = _shortlist_calculation_html("40")

        self.assertEqual(rendered, "🧮 <b>Хариу:</b> <code>40</code>")

    async def test_inline_bank_calculation_uses_calctape_format(self) -> None:
        update = _InlineUpdate()
        update.inline_query.query = "BOC:USD:buy * 10"
        calculation = ShortlistCalculation(
            expression="BOC · USD (авах) × 10",
            result="72.5",
            resolved_expression="7.25 × 10",
            tape_entries=[
                {"operator": "+", "value": "7.25", "label": "BOC · USD (авах)"},
                {"operator": "*", "value": "10"},
            ],
        )

        with patch("bot.handlers.is_whitelisted", return_value=True), patch(
            "bot.handlers.calculate_shortlist_expression",
            new=AsyncMock(return_value=calculation),
        ) as calculate_expression:
            await inline_query_handler(update, None)

        result = update.inline_query.answers[0][0][0][0]
        message_text = result.input_message_content.message_text
        self.assertEqual(result.title, "= 72.50")
        self.assertEqual(
            message_text,
            "<pre>+ 7.25\n"
            "* 10.00\n"
            "---------------\n"
            "+ 72.50</pre>",
        )
        self.assertNotIn("BOC", message_text)
        self.assertNotIn("Хариу", message_text)

    async def test_inline_single_rate_uses_copyable_source_format(self) -> None:
        update = _InlineUpdate()
        update.inline_query.query = "XE:USD/JPY"
        calculation = ShortlistCalculation(
            expression="XE · USD/JPY (ханш)",
            result="156.2",
            resolved_expression="156.20",
            tape_entries=[{"operator": "+", "value": "156.20"}],
            single_rate=("XE", "USD/JPY", "156.2"),
        )

        with patch("bot.handlers.is_whitelisted", return_value=True), patch(
            "bot.handlers.calculate_shortlist_expression",
            new=AsyncMock(return_value=calculation),
        ) as calculate_expression:
            await inline_query_handler(update, None)

        calculate_expression.assert_awaited_once_with(1, "XE:USD/JPY", force=True)

        result = update.inline_query.answers[0][0][0][0]
        self.assertEqual(result.title, "= 156.20")
        self.assertEqual(
            result.input_message_content.message_text,
            '<a href="https://www.xe.com/currencyconverter/convert/?Amount=1&amp;From=USD&amp;To=JPY">'
            "XE курс</a>: <code>156.20</code> <b>USD/JPY</b>",
        )
        self.assertTrue(result.input_message_content.link_preview_options.is_disabled)

    async def test_empty_inline_mention_does_not_list_rates_or_formulas(self) -> None:
        update = _InlineUpdate()

        with patch(
            "bot.handlers._inline_shortlist_results",
            side_effect=AssertionError("inline mention listed rates"),
        ):
            await inline_query_handler(update, None)

        self.assertEqual(update.inline_query.answers[0][0][0], [])


if __name__ == "__main__":
    unittest.main()
