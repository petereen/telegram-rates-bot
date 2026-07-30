import unittest
from unittest.mock import patch

from services.group_calculator import (
    ShortlistCalculationError,
    calculate_shortlist_expression,
    parse_shortlist_expression,
)
from services.rates import RateSnapshot, RateValue


class GroupCalculatorTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_rejects_unrecognised_text(self) -> None:
        with self.assertRaises(ShortlistCalculationError):
            parse_shortlist_expression("CBR:USD/RUB hello 2")

    async def test_resolves_shortlisted_rates_with_shared_precedence(self) -> None:
        def snapshot(provider: str, symbol: str) -> RateSnapshot:
            amounts = {"CBR": "5", "Binance": "10"}
            return RateSnapshot(
                key=f"rate:{provider}:{symbol}",
                kind="subscription",
                source=provider,
                pair=symbol,
                values=[RateValue("value", amounts[provider])],
                fetched_at="2026-01-01T00:00:00Z",
            )

        with patch(
            "services.group_calculator.get_subscriptions",
            return_value=[
                {"provider": "CBR", "symbol": "USD/RUB"},
                {"provider": "Binance", "symbol": "USDT/MNT"},
            ],
        ), patch("services.group_calculator.get_rate_snapshot", side_effect=snapshot):
            result = await calculate_shortlist_expression(
                1, "CBR:USD/RUB + Binance:USDT/MNT * 2"
            )

        self.assertEqual(result.result, "25")
        self.assertIn("Binance · USDT/MNT (ханш) × 2", result.expression)
        self.assertEqual(result.resolved_expression, "5 + 10 × 2")

    async def test_rejects_rate_outside_the_shortlist(self) -> None:
        with patch("services.group_calculator.get_subscriptions", return_value=[]):
            with self.assertRaisesRegex(ShortlistCalculationError, "жагсаалтад"):
                await calculate_shortlist_expression(1, "CBR:USD/RUB + 1")

    async def test_requires_a_field_for_multi_value_rate(self) -> None:
        snapshot = RateSnapshot(
            key="rate:TDBM:USD/MNT",
            kind="subscription",
            source="TDBM",
            pair="USD/MNT",
            values=[RateValue("cash buy", "10"), RateValue("cash sell", "11")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "services.group_calculator.get_subscriptions",
            return_value=[{"provider": "TDBM", "symbol": "USD/MNT"}],
        ), patch("services.group_calculator.get_rate_snapshot", return_value=snapshot):
            with self.assertRaisesRegex(ShortlistCalculationError, "олон утгатай"):
                await calculate_shortlist_expression(1, "TDBM:USD/MNT")

    async def test_field_accepts_provider_style_name(self) -> None:
        snapshot = RateSnapshot(
            key="rate:TDBM:USD/MNT",
            kind="subscription",
            source="TDBM",
            pair="USD/MNT",
            values=[RateValue("non-cash sell", "11")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "services.group_calculator.get_subscriptions",
            return_value=[{"provider": "TDBM", "symbol": "USD/MNT"}],
        ), patch("services.group_calculator.get_rate_snapshot", return_value=snapshot):
            result = await calculate_shortlist_expression(
                1, "TDBM:USD/MNT:noncash_sell * 2"
            )

        self.assertEqual(result.result, "22")
        self.assertEqual(
            result.expression,
            "TDBM · USD/MNT (бэлэн бус зарах) × 2",
        )
        self.assertEqual(result.resolved_expression, "11 × 2")


if __name__ == "__main__":
    unittest.main()
