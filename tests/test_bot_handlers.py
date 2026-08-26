import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers import cmd_calc


class _Message:
    def __init__(self) -> None:
        self.replies: list[tuple[tuple, dict]] = []

    async def reply_text(self, *args, **kwargs) -> None:
        self.replies.append((args, kwargs))


class _Update:
    def __init__(self) -> None:
        self.message = _Message()


class _Context:
    def __init__(self) -> None:
        self.user_data: dict = {}


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


if __name__ == "__main__":
    unittest.main()
