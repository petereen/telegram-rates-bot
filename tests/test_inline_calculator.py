import unittest
from unittest.mock import patch

from bot.handlers import _inline_shortlist_results
from services.rates import RateSnapshot, RateValue


class InlineCalculatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_shortlist_exposes_field_aliases_and_clean_messages(self) -> None:
        snapshot = RateSnapshot(
            key="rate:TDBM:USD/MNT",
            kind="subscription",
            source="TDBM",
            pair="USD/MNT",
            values=[
                RateValue("cash buy", "3500"),
                RateValue("non-cash sell", "3560"),
            ],
            fetched_at="2026-07-30T00:00:00Z",
        )
        with patch(
            "bot.handlers.get_subscriptions",
            return_value=[{"provider": "TDBM", "symbol": "USD/MNT"}],
        ), patch("bot.handlers.get_rate_snapshot", return_value=snapshot):
            results = await _inline_shortlist_results(1)

        self.assertEqual(len(results), 2)
        self.assertIn("TDBM:USD/MNT:cash_buy", results[0].description)
        self.assertIn(
            "<b>Бэлэн авах:</b> <code>3500</code>",
            results[0].input_message_content.message_text,
        )
        button = results[1].reply_markup.inline_keyboard[0][0]
        self.assertEqual(
            button.switch_inline_query_current_chat,
            "TDBM:USD/MNT:noncash_sell ",
        )

    async def test_shortlist_search_suggests_matching_rate(self) -> None:
        snapshot = RateSnapshot(
            key="rate:CBR:USD/RUB",
            kind="subscription",
            source="CBR",
            pair="USD/RUB",
            values=[RateValue("value", "80")],
            fetched_at="2026-07-30T00:00:00Z",
        )
        with patch(
            "bot.handlers.get_subscriptions",
            return_value=[{"provider": "CBR", "symbol": "USD/RUB"}],
        ), patch("bot.handlers.get_rate_snapshot", return_value=snapshot):
            matching = await _inline_shortlist_results(1, "usd/rub")
            missing = await _inline_shortlist_results(1, "eur")

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].title, "CBR · USD/RUB · Ханш")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
