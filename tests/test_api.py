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

    def test_formula_create_validates_and_returns_definition(self) -> None:
        row = {
            "id": "formula-1",
            "title": "TEST",
            "left_operand": {
                "kind": "rate",
                "provider": "CBR",
                "symbol": "USD/RUB",
                "field": "rate",
            },
            "operator": "*",
            "right_operand": {"kind": "constant", "value": "1.01"},
            "adjustment_percent": None,
            "precision": 2,
            "enabled": True,
            "sort_order": 3,
            "updated_at": "2026-07-30T00:00:00Z",
        }
        with patch("api.app.create_formula_definition", return_value=row):
            response = self.client.post(
                "/api/formulas",
                json={
                    "title": "TEST",
                    "left": row["left_operand"],
                    "operator": "*",
                    "right": row["right_operand"],
                    "adjustmentPercent": None,
                    "precision": 2,
                    "enabled": True,
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["formula"]["id"], "formula-1")

    def test_formula_rejects_unsupported_field(self) -> None:
        response = self.client.post(
            "/api/formulas",
            json={
                "title": "BAD",
                "left": {
                    "kind": "rate",
                    "provider": "CBR",
                    "symbol": "USD/RUB",
                    "field": "min_price",
                },
                "operator": "*",
                "right": {"kind": "constant", "value": "1"},
                "precision": 2,
                "enabled": True,
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
