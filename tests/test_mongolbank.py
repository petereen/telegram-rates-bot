import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from providers.mongolbank import (
    _API_URL,
    _UB_TZ,
    MongolBankProvider,
    _fetch_official_rates,
)


class MongolBankTests(unittest.TestCase):
    @patch("providers.mongolbank.requests.post")
    def test_official_request_sends_json_date_range(self, request_post: Mock) -> None:
        rate_date = datetime.now(_UB_TZ).date().isoformat()
        response = Mock()
        response.json.return_value = {
            "data": [{"RATE_DATE": rate_date, "RUB": "45.98"}]
        }
        response.raise_for_status.return_value = None
        request_post.return_value = response

        self.assertEqual(_fetch_official_rates(), {"RUB": 45.98})
        request_post.assert_called_once_with(
            _API_URL,
            json={"startDate": "2001-01-01", "endDate": rate_date},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=(5, 10),
        )

    @patch(
        "providers.mongolbank._fetch_rates",
        return_value={"USD": 3462.15, "CNY": 481.2, "JPY": 23.1},
    )
    def test_common_mnt_pairs_are_supported(self, fetch_rates: Mock) -> None:
        provider = MongolBankProvider()

        for pair, expected in (
            ("USD/MNT", 3462.15),
            ("CNY/MNT", 481.2),
            ("JPY/MNT", 23.1),
        ):
            with self.subTest(pair=pair):
                data = provider.fetch(pair)
                self.assertEqual(data["rate"], expected)
                self.assertIn(pair, data["lines"][0])

        self.assertEqual(fetch_rates.call_count, 3)


if __name__ == "__main__":
    unittest.main()
