import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers import (
    _handle_mentioned_calculation,
    inline_query_handler,
    _shortlist_calculation_html,
    cmd_calc,
)


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
