import unittest
from unittest.mock import patch

from services.rates import (
    get_formula_snapshots,
    render_share_html,
    snapshot_from_provider_data,
)


class RateSnapshotTests(unittest.TestCase):
    def test_buy_sell_normalization(self) -> None:
        snapshot = snapshot_from_provider_data(
            "TDB", "USD/MNT", {"buy": 3500.0, "sell": 3550.5}
        )
        self.assertEqual([value.label for value in snapshot.values], ["buy", "sell"])
        self.assertEqual(snapshot.values[1].amount, "3550.5")

    def test_error_normalization(self) -> None:
        snapshot = snapshot_from_provider_data(
            "XE", "USD/RUB", {"lines": ["XE USD/RUB: fetch error"]}
        )
        self.assertEqual(snapshot.status, "error")
        self.assertFalse(snapshot.values)

    def test_share_escapes_provider_content(self) -> None:
        snapshot = snapshot_from_provider_data(
            "A&B", "USD/<RUB>", {"rate": 12.5}
        )
        rendered = render_share_html([snapshot])
        self.assertIn("A&amp;B", rendered)
        self.assertIn("USD/&lt;RUB&gt;", rendered)


class FormulaTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_formula_results(self) -> None:
        payloads = {
            ("MongolBank", "RUB/MNT"): {"rate": 50, "lines": []},
            ("TDB", "USD/MNT"): {"sell": 3500, "lines": []},
            ("CBR", "USD/RUB"): {"rate": 100, "lines": []},
            ("Binance", "P2P USDT/MNT"): {
                "rate": 3510,
                "min_price": 3500,
                "lines": [],
            },
            ("Rapira", "USDT/RUB"): {"buy": 100, "sell": 101, "lines": []},
        }

        class FakeProvider:
            def __init__(self, name: str) -> None:
                self.name = name

            def get_rate(self, symbol: str):
                return payloads[(self.name, symbol)]

        definitions = [
            {
                "id": "delcrado",
                "title": "ДЕЛЬКРАДО",
                "left_operand": {
                    "kind": "rate",
                    "provider": "MongolBank",
                    "symbol": "RUB/MNT",
                    "field": "rate",
                },
                "operator": "*",
                "right_operand": {"kind": "constant", "value": "1.005"},
                "adjustment_percent": None,
                "precision": 2,
            },
            {
                "id": "triquetra",
                "title": "ТРИКУЭТРА",
                "left_operand": {
                    "kind": "rate",
                    "provider": "TDB",
                    "symbol": "USD/MNT",
                    "field": "sell",
                },
                "operator": "/",
                "right_operand": {
                    "kind": "rate",
                    "provider": "CBR",
                    "symbol": "USD/RUB",
                    "field": "rate",
                },
                "adjustment_percent": "1",
                "precision": 2,
            },
            {
                "id": "rub-cash",
                "title": "RUB БЭЛЭН",
                "left_operand": {
                    "kind": "rate",
                    "provider": "Binance",
                    "symbol": "P2P USDT/MNT",
                    "field": "min_price",
                },
                "operator": "/",
                "right_operand": {
                    "kind": "rate",
                    "provider": "Rapira",
                    "symbol": "USDT/RUB",
                    "field": "buy",
                },
                "adjustment_percent": None,
                "precision": 2,
            },
        ]
        with patch(
            "services.rates.get_provider",
            side_effect=lambda name: FakeProvider(name),
        ), patch("services.rates.get_cached_rate_entry", return_value=None):
            snapshots = await get_formula_snapshots(definitions=definitions)

        self.assertEqual([item.values[0].amount for item in snapshots], [
            "50.25",
            "35.35",
            "35",
        ])

    async def test_formula_operators_and_division_by_zero(self) -> None:
        class FakeProvider:
            def get_rate(self, symbol: str):
                return {"rate": 10, "lines": []}

        definitions = [
            {
                "id": operator,
                "title": operator,
                "left_operand": {
                    "kind": "rate",
                    "provider": "Fake",
                    "symbol": "A/B",
                    "field": "rate",
                },
                "operator": operator,
                "right_operand": {
                    "kind": "constant",
                    "value": "0" if operator == "/" else "3",
                },
                "adjustment_percent": None,
                "precision": 2,
            }
            for operator in ("+", "-", "*", "/")
        ]
        with patch("services.rates.get_provider", return_value=FakeProvider()), patch(
            "services.rates.get_cached_rate_entry", return_value=None
        ):
            snapshots = await get_formula_snapshots(definitions=definitions)

        self.assertEqual(
            [snapshot.values[0].amount for snapshot in snapshots[:3]],
            ["13", "7", "30"],
        )
        self.assertEqual(snapshots[3].status, "error")


if __name__ == "__main__":
    unittest.main()
