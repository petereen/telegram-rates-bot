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
        ), patch("bot.handlers.get_rate_snapshot", return_value=snapshot), patch(
            "bot.handlers.get_formula_snapshots", return_value=[]
        ):
            results = await _inline_shortlist_results(1)

        self.assertEqual(len(results), 2)
        self.assertIn("TDBM:USD/MNT:cash_buy", results[0].description)
        self.assertIn(
            "<b>Бэлэн авах:</b> <code>3500</code>",
            results[0].input_message_content.message_text,
        )
        button = results[1].reply_markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "↩ Томьёонд оруулах")
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
        ), patch("bot.handlers.get_rate_snapshot", return_value=snapshot), patch(
            "bot.handlers.get_formula_snapshots", return_value=[]
        ):
            matching = await _inline_shortlist_results(1, "usd/rub")
            missing = await _inline_shortlist_results(1, "eur")

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].title, "CBR · USD/RUB · Ханш")
        self.assertEqual(missing, [])

    async def test_operand_search_after_operator_shows_all_rate_choices(self) -> None:
        snapshot = RateSnapshot(
            key="rate:BOC:USD",
            kind="subscription",
            source="BOC",
            pair="USD",
            values=[RateValue("buy", "7.25"), RateValue("sell", "7.3")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "bot.handlers.get_subscriptions",
            return_value=[{"provider": "BOC", "symbol": "USD"}],
        ), patch("bot.handlers.get_rate_snapshot", return_value=snapshot), patch(
            "bot.handlers.get_formula_snapshots", return_value=[]
        ):
            results = await _inline_shortlist_results("1", "BOC:USD:buy *")

        self.assertEqual(len(results), 2)

    async def test_shortlist_includes_calculated_rates(self) -> None:
        formula = RateSnapshot(
            key="formula:delcrado",
            kind="calculated",
            source="Тооцоолсон",
            pair="ДЕЛЬКРАДО",
            values=[RateValue("value", "50.25")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch("bot.handlers.get_subscriptions", return_value=[]), patch(
            "bot.handlers.get_formula_snapshots", return_value=[formula]
        ):
            results = await _inline_shortlist_results("1", "BOC:USD:buy *")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Тооцоолсон · ДЕЛЬКРАДО · Ханш")
        self.assertEqual(
            results[0].reply_markup.inline_keyboard[0][0]
            .switch_inline_query_current_chat,
            "formula:delcrado ",
        )


if __name__ == "__main__":
    unittest.main()
