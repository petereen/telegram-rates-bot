import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from api.auth import AuthUser, current_user


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app.dependency_overrides[current_user] = lambda: AuthUser(
            telegram_id=12345, username="tester", first_name="Test"
        )
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_calculator_endpoint(self) -> None:
        response = self.client.post(
            "/api/calculate", json={"tokens": ["100", "/", "4", "+", "5"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "30")

    def test_subscription_is_idempotently_returned(self) -> None:
        row = {"id": "sub-1", "provider": "CBR", "symbol": "USD/RUB"}
        with patch("api.app.add_subscription", return_value=True), patch(
            "api.app.get_subscriptions", return_value=[row]
        ):
            response = self.client.post(
                "/api/subscriptions",
                json={"provider": "CBR", "symbol": "USD/RUB"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["subscription"]["id"], "sub-1")

    def test_unknown_pair_is_rejected(self) -> None:
        response = self.client.post(
            "/api/subscriptions",
            json={"provider": "CBR", "symbol": "NOPE/RUB"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
