from decimal import Decimal
import unittest

from services.calculator import CalculationError, evaluate_tokens, format_decimal


class CalculatorTests(unittest.TestCase):
    def test_precedence(self) -> None:
        result = evaluate_tokens(["10", "+", "5", "*", "2"])
        self.assertEqual(result["result"], "20")
        self.assertEqual(result["expression"], "10 + 5 × 2")

    def test_percentage_applies_to_subtotal(self) -> None:
        result = evaluate_tokens(["100", "+0.5%"])
        self.assertEqual(result["result"], "100.5")

    def test_division_by_zero(self) -> None:
        with self.assertRaises(CalculationError):
            evaluate_tokens(["10", "/", "0"])

    def test_invalid_adjacent_numbers(self) -> None:
        with self.assertRaises(CalculationError):
            evaluate_tokens(["10", "20"])

    def test_decimal_formatting(self) -> None:
        self.assertEqual(format_decimal(Decimal("20.5000")), "20.5")


if __name__ == "__main__":
    unittest.main()
