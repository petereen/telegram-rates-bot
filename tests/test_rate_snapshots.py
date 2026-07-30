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

        with patch(
            "services.rates.get_provider",
            side_effect=lambda name: FakeProvider(name),
        ):
            snapshots = await get_formula_snapshots()

        self.assertEqual([item.values[0].amount for item in snapshots], [
            "50.25",
            "35.35",
            "35",
        ])


if __name__ == "__main__":
    unittest.main()
