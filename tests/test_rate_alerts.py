import unittest
from decimal import Decimal

from services.rate_alerts import (
    canonical_values,
    render_alert_html,
    robust_volatility_percent,
    safety_floor_percent,
    sudden_change,
)


class RateAlertTests(unittest.TestCase):
    def test_safety_floor_categories(self):
        self.assertEqual(safety_floor_percent("MongolBank", "USD/MNT"), Decimal("0.75"))
        self.assertEqual(safety_floor_percent("TDBM", "USD/MNT"), Decimal("0.75"))
        self.assertEqual(safety_floor_percent("XE", "USD/RUB"), Decimal("0.50"))
        self.assertEqual(safety_floor_percent("Binance", "P2P USDT/MNT"), Decimal("1.25"))
        self.assertEqual(safety_floor_percent("Binance", "P2P CNY"), Decimal("1.25"))
        self.assertEqual(safety_floor_percent("Rapira", "USDT/RUB"), Decimal("1.25"))
        self.assertEqual(safety_floor_percent("Binance", "BTC/USDT"), Decimal("2.50"))
        self.assertEqual(safety_floor_percent("Binance", "PEPE/USDT"), Decimal("4.00"))

    def test_visible_fields_exclude_aliases_and_formula_only_values(self):
        self.assertEqual(canonical_values({"buy": 99, "sell": 101, "rate": 101}), {
            "buy": Decimal("99"), "sell": Decimal("101"),
        })
        self.assertEqual(canonical_values({"rate": 3500, "min_price": 3400}), {
            "rate": Decimal("3500"),
        })
        self.assertEqual(canonical_values({
            "cash_buy": 1, "cash_sell": 2, "noncash_buy": 3,
            "noncash_sell": 4, "buy": 3, "sell": 4,
        }), {
            "cash_buy": Decimal("1"), "cash_sell": Decimal("2"),
            "noncash_buy": Decimal("3"), "noncash_sell": Decimal("4"),
        })

    def test_warmup_uses_safety_floor_and_first_value_is_not_an_alert(self):
        history = [Decimal("100")] * 29
        self.assertIsNone(sudden_change("XE", "USD/RUB", Decimal("100"), Decimal("100.4"), history))
        detected = sudden_change("XE", "USD/RUB", Decimal("100"), Decimal("100.5"), history)
        self.assertEqual(detected, (Decimal("0.500"), Decimal("0.50")))

    def test_adaptive_threshold_overrides_floor_after_thirty_observations(self):
        # Varied 1–3% moves produce a robust threshold above the FX floor.
        history = [Decimal("100")]
        for move in ("1", "-2", "3", "-1", "2", "-3") * 5:
            history.append(history[-1] * (Decimal("1") + Decimal(move) / Decimal("100")))
        history = history[:30]
        sigma = robust_volatility_percent(history)
        self.assertIsNotNone(sigma)
        self.assertGreater(Decimal("4") * sigma, Decimal("0.50"))
        self.assertIsNone(sudden_change("XE", "USD/RUB", Decimal("100"), Decimal("101"), history))

    def test_alert_message_has_direction_and_disclaimer(self):
        html = render_alert_html({
            "provider": "XE", "symbol": "USD/RUB", "field": "rate",
            "old_value": "100", "new_value": "101", "change_percent": "1",
            "threshold_percent": "0.5", "observed_at": "2026-01-01T00:00:00+00:00",
        })
        self.assertIn("ӨСӨЛТ", html)
        self.assertIn("хөрөнгө оруулалтын зөвлөгөө биш", html)


if __name__ == "__main__":
    unittest.main()
