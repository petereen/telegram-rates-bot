import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from fastapi import HTTPException

from api.auth import (
    TELEGRAM_BOT_TOKEN,
    AuthUser,
    current_user,
    issue_access_token,
    validate_api_key,
    validate_mini_app_data,
)


def signed_init_data(user_id: int, auth_date: int) -> str:
    payload = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test", "username": "tester"},
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret = hmac.new(
        b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    payload["hash"] = hmac.new(
        secret, data_check.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(payload)


class MiniAppAuthTests(unittest.TestCase):
    def test_valid_signature(self) -> None:
        user = validate_mini_app_data(
            signed_init_data(12345, int(time.time())), max_age=60
        )
        self.assertEqual(user.telegram_id, 12345)
        self.assertEqual(user.username, "tester")

    def test_tampered_user_is_rejected(self) -> None:
        data = signed_init_data(12345, int(time.time())).replace("12345", "99999")
        with self.assertRaises(HTTPException):
            validate_mini_app_data(data, max_age=60)

    def test_expired_data_is_rejected(self) -> None:
        data = signed_init_data(12345, int(time.time()) - 120)
        with self.assertRaises(HTTPException):
            validate_mini_app_data(data, max_age=60)

    @patch("api.auth.APP_API_KEY", "test-api-key")
    def test_api_key_is_required(self) -> None:
        validate_api_key("test-api-key")
        with self.assertRaises(HTTPException):
            validate_api_key("wrong-key")

    def test_mini_app_access_token_authenticates_requests(self) -> None:
        token = issue_access_token(AuthUser(12345, "tester", "Test"))
        user = current_user(None, f"Bearer {token}")
        self.assertEqual(user.telegram_id, 12345)
        self.assertEqual(user.username, "tester")


if __name__ == "__main__":
    unittest.main()
