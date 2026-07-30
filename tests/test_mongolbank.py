import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from providers.mongolbank import _API_URL, _UB_TZ, _fetch_official_rates


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


if __name__ == "__main__":
    unittest.main()
