import unittest
from unittest.mock import Mock, patch

from providers.base import all_providers, get_provider
from providers.registry import register_all_providers
from services.rates import snapshot_from_provider_data


EXPECTED_BANKS = {
    "KhanBank",
    "GolomtBank",
    "XacBank",
    "ArigBank",
    "StateBank",
    "MongolBank",
    "CapitronBank",
    "NaimanSharga",
    "SendMN",
    "TDBM",
    "BogdBank",
    "CKBank",
    "NIBank",
    "TransBank",
    "MBank",
}


class MongolianBankProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_all_providers()

    def test_all_upstream_banks_are_visible_and_legacy_tdb_is_hidden(self) -> None:
        visible = set(all_providers())
        self.assertTrue(EXPECTED_BANKS <= visible)
        self.assertNotIn("TDB", visible)
        self.assertEqual(get_provider("TDB").NAME, "TDB")

    def test_mongolbank_uses_official_provider(self) -> None:
        provider = get_provider("MongolBank")
        self.assertEqual(provider.__class__.__module__, "providers.mongolbank")
        self.assertEqual(provider.PAIRS, {"RUB/MNT": "Рубль ↔ Tögrög"})

    @patch("providers.mongolian_banks.requests.get")
    def test_normalizes_cash_and_noncash_rates(self, request_get: Mock) -> None:
        response = Mock()
        response.json.return_value = [
            {
                "bank_name": "KhanBank",
                "rates": {
                    "usd": {
                        "cash": {"buy": 3420.5, "sell": "3,450"},
                        "noncash": {"buy": 3415, "sell": 3455},
                    }
                },
            }
        ]
        response.raise_for_status.return_value = None
        request_get.return_value = response

        data = get_provider("KhanBank").fetch("USD/MNT")

        request_get.assert_called_once()
        self.assertEqual(data["cash_buy"], 3420.5)
        self.assertEqual(data["cash_sell"], 3450.0)
        self.assertEqual(data["noncash_buy"], 3415.0)
        self.assertEqual(data["noncash_sell"], 3455.0)
        self.assertEqual(data["buy"], 3415.0)
        self.assertEqual(data["sell"], 3455.0)
        self.assertEqual(data["rate"], 3455.0)

    def test_snapshot_exposes_all_four_bank_values(self) -> None:
        snapshot = snapshot_from_provider_data(
            "KhanBank",
            "USD/MNT",
            {
                "cash_buy": 3420,
                "cash_sell": 3450,
                "noncash_buy": 3415,
                "noncash_sell": 3455,
                "buy": 3415,
                "sell": 3455,
            },
        )
        self.assertEqual(
            [value.label for value in snapshot.values],
            ["cash buy", "cash sell", "non-cash buy", "non-cash sell"],
        )

    @patch("providers.mongolian_banks.requests.get")
    def test_missing_currency_returns_displayable_error(self, request_get: Mock) -> None:
        response = Mock()
        response.json.return_value = [{"bank_name": "SendMN", "rates": {}}]
        response.raise_for_status.return_value = None
        request_get.return_value = response

        data = get_provider("SendMN").fetch("GBP/MNT")

        self.assertEqual(data, {"lines": ["SendMN GBP/MNT: not found"]})


if __name__ == "__main__":
    unittest.main()
