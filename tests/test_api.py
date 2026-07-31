import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.app import app
from api.auth import AuthUser, current_user
from services.branding import BrandingStorageError
from services.rates import RateSnapshot, RateValue


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

    def test_agent_rate_requires_bearer_key(self) -> None:
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"):
            response = self.client.post(
                "/api/agent/rate",
                json={"provider": "CBR", "pair": "USD/RUB"},
            )
        self.assertEqual(response.status_code, 401)

    def test_agent_rate_returns_snapshot(self) -> None:
        snapshot = RateSnapshot(
            key="rate:CBR:USD/RUB",
            kind="subscription",
            source="CBR",
            pair="USD/RUB",
            values=[RateValue("value", "92.5")],
            fetched_at="2026-07-31T00:00:00+00:00",
        )
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"), patch(
            "api.app.get_rate_snapshot", return_value=snapshot
        ):
            response = self.client.post(
                "/api/agent/rate",
                headers={"Authorization": "Bearer agent-secret"},
                json={"provider": "CBR", "pair": "USD/RUB"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "CBR")
        self.assertEqual(response.json()["values"][0]["amount"], "92.5")

    def test_agent_rate_rejects_unknown_pair(self) -> None:
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"):
            response = self.client.post(
                "/api/agent/rate",
                headers={"Authorization": "Bearer agent-secret"},
                json={"provider": "CBR", "pair": "NOPE/RUB"},
            )
        self.assertEqual(response.status_code, 404)

    def test_agent_rates_returns_every_provider_pair(self) -> None:
        snapshot = RateSnapshot(
            key="rate:MongolBank:USD/MNT",
            kind="subscription",
            source="MongolBank",
            pair="USD/MNT",
            values=[RateValue("value", "3462.15")],
            fetched_at="2026-07-31T00:00:00+00:00",
        )
        provider = type(
            "Provider",
            (),
            {"PAIRS": {
                "USD/MNT": "US Dollar ↔ Tögrög",
                "CNY/MNT": "Chinese Yuan ↔ Tögrög",
                "JPY/MNT": "Japanese Yen ↔ Tögrög",
            }},
        )()
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"), patch(
            "api.app.all_providers", return_value={"MongolBank": provider}
        ), patch("api.app.get_rate_snapshot", return_value=snapshot) as get_snapshot, patch(
            "api.app.get_formula_snapshots", new_callable=AsyncMock, return_value=[]
        ):
            response = self.client.get(
                "/api/agent/rates",
                headers={"Authorization": "Bearer agent-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["rates"]), 3)
        self.assertEqual(get_snapshot.call_count, 3)
        get_snapshot.assert_any_call("MongolBank", "USD/MNT", False)
        get_snapshot.assert_any_call("MongolBank", "CNY/MNT", False)
        get_snapshot.assert_any_call("MongolBank", "JPY/MNT", False)

    def test_agent_rates_includes_formula_snapshots(self) -> None:
        formula = RateSnapshot(
            key="formula:delcrado",
            kind="calculated",
            source="Тооцоолсон",
            pair="ДЕЛЬКРАДО",
            values=[RateValue("value", "45.19")],
            fetched_at="2026-07-31T00:00:00+00:00",
            formula="MongolBank RUB/MNT × 1.005",
        )
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"), patch(
            "api.app.all_providers", return_value={}
        ), patch(
            "api.app.get_formula_snapshots",
            new_callable=AsyncMock,
            return_value=[formula],
        ):
            response = self.client.get(
                "/api/agent/rates",
                headers={"Authorization": "Bearer agent-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rates"][0]["kind"], "calculated")
        self.assertEqual(response.json()["rates"][0]["pair"], "ДЕЛЬКРАДО")

    def test_agent_rates_returns_partial_response_when_provider_fails(self) -> None:
        provider = type("Provider", (), {"PAIRS": {"USD/ERR": "Broken"}})()
        with patch("api.app.AGENT_RATES_API_KEY", "agent-secret"), patch(
            "api.app.all_providers", return_value={"Broken": provider}
        ), patch(
            "api.app.get_rate_snapshot", side_effect=RuntimeError("upstream failed")
        ), patch(
            "api.app.get_formula_snapshots", new_callable=AsyncMock, return_value=[]
        ):
            response = self.client.get(
                "/api/agent/rates",
                headers={"Authorization": "Bearer agent-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["partial"])
        self.assertEqual(response.json()["rates"][0]["status"], "error")

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

    def test_rate_search_matches_all_provider_metadata(self) -> None:
        snapshots = [
            RateSnapshot(
                key="rate:TDBM:USD/MNT",
                kind="subscription",
                source="TDBM",
                pair="USD/MNT",
                values=[RateValue("sell", "3560")],
                fetched_at="2026-07-30T00:00:00+00:00",
            )
        ]
        with patch("api.app.all_providers") as providers, patch(
            "api.app.get_rate_snapshot", return_value=snapshots[0]
        ) as get_snapshot:
            provider = type("Provider", (), {
                "DISPLAY_NAME": "Худалдаа Хөгжлийн Банк",
                "PAIRS": {"USD/MNT": "US Dollar ↔ Tögrög"},
            })()
            providers.return_value = {"TDBM": provider}
            response = self.client.get("/api/rates/search?q=usd/mnt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rates"][0]["pair"], "USD/MNT")
        get_snapshot.assert_called_once_with("TDBM", "USD/MNT")

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

    def test_branding_storage_failure_is_not_returned_as_an_opaque_500(self) -> None:
        with patch(
            "api.app.replace_logo",
            side_effect=BrandingStorageError("storage unavailable"),
        ):
            response = self.client.put(
                "/api/branding/app-logo",
                files={"file": ("logo.png", b"not decoded here", "image/png")},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "storage unavailable")


if __name__ == "__main__":
    unittest.main()
