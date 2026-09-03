import unittest
from unittest.mock import patch

from services.group_calculator import (
    RateReference,
    ShortlistCalculationError,
    calculate_shortlist_expression,
    parse_shortlist_expression,
)
from services.rates import RateSnapshot, RateValue


class GroupCalculatorTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_rejects_unrecognised_text(self) -> None:
        with self.assertRaises(ShortlistCalculationError):
            parse_shortlist_expression("CBR:USD/RUB hello 2")

    def test_parser_accepts_single_currency_and_spaced_symbols(self) -> None:
        single_currency = parse_shortlist_expression("BOC:USD:buy * 10")
        spaced_symbol = parse_shortlist_expression(
            "Binance:P2P USDT/MNT:min_price / 2"
        )

        self.assertEqual(
            single_currency[0],
            RateReference("BOC", "USD", "buy"),
        )
        self.assertEqual(
            spaced_symbol[0],
            RateReference("Binance", "P2P USDT/MNT", "min_price"),
        )

    async def test_calculates_boc_single_currency_reference(self) -> None:
        snapshot = RateSnapshot(
            key="rate:BOC:USD",
            kind="subscription",
            source="BOC",
            pair="USD",
            values=[RateValue("buy", "7.25"), RateValue("sell", "7.3")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "services.group_calculator.get_subscriptions",
            return_value=[{"provider": "BOC", "symbol": "USD"}],
        ), patch(
            "services.group_calculator.get_rate_snapshot",
            return_value=snapshot,
        ):
            result = await calculate_shortlist_expression(
                1, "BOC:USD:buy * 10"
            )

        self.assertEqual(result.expression, "BOC · USD (авах) × 10")
        self.assertEqual(result.resolved_expression, "7.25 × 10")
        self.assertEqual(result.result, "72.5")
        self.assertEqual(
            result.tape_entries,
            [
                {"operator": "+", "value": "7.25"},
                {"operator": "*", "value": "10"},
            ],
        )

    async def test_single_rate_preserves_source_pair_and_amount(self) -> None:
        snapshot = RateSnapshot(
            key="rate:XE:USD/JPY",
            kind="subscription",
            source="XE",
            pair="USD/JPY",
            values=[RateValue("value", "156.20")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "services.group_calculator.get_subscriptions",
            return_value=[{"provider": "XE", "symbol": "USD/JPY"}],
        ), patch(
            "services.group_calculator.get_rate_snapshot",
            return_value=snapshot,
        ) as get_snapshot:
            result = await calculate_shortlist_expression(
                1, "XE:USD/JPY", force=True
            )

        self.assertEqual(result.single_rate, ("XE", "USD/JPY", "156.20"))
        get_snapshot.assert_called_once_with("XE", "USD/JPY", True)

    async def test_calculated_formula_can_be_used_as_operand(self) -> None:
        formula = RateSnapshot(
            key="formula:delcrado",
            kind="calculated",
            source="Тооцоолсон",
            pair="ДЕЛЬКРАДО",
            values=[RateValue("value", "50.25")],
            fetched_at="2026-01-01T00:00:00Z",
        )
        with patch(
            "services.group_calculator.get_subscriptions", return_value=[]
        ), patch(
            "services.group_calculator.get_formula_snapshots",
            return_value=[formula],
        ):
            result = await calculate_shortlist_expression(
                1, "formula:delcrado * 2"
            )

        self.assertEqual(result.expression, "Тооцоолсон · ДЕЛЬКРАДО (ханш) × 2")
        self.assertEqual(result.resolved_expression, "50.25 × 2")
        self.assertEqual(result.result, "100.5")

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
