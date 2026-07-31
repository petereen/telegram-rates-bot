from decimal import Decimal
import unittest

from services.calculator import (
    CalculationError,
    evaluate_tokens,
    format_decimal,
    format_grouped_hundredths,
    format_hundredths,
    parse_numeric_expression,
    render_normal_calculation,
)


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

    def test_hundredths_uses_half_up_and_keeps_zeroes(self) -> None:
        self.assertEqual(format_hundredths("2.345"), "2.35")
        self.assertEqual(format_hundredths("10"), "10.00")

    def test_normal_calculation_uses_numbered_grouped_ledger_format(self) -> None:
        tokens = parse_numeric_expression("844,800.00 + 1,000,000 + 8,187,978.38")
        self.assertEqual(format_grouped_hundredths("1000"), "1,000.00")
        self.assertEqual(
            render_normal_calculation(tokens),
            "<pre>+ 844,800.00  №1\n"
            "+ 1,000,000.00  №2\n"
            "+ 8,187,978.38  №3\n"
            "---------------\n"
            "+ 10,032,778.38</pre>",
        )

    def test_parentheses_work_in_long_numeric_expression(self) -> None:
        result = evaluate_tokens(parse_numeric_expression("(1,000 + 5,000) * 2"))
        self.assertEqual(result["result"], "12000")


if __name__ == "__main__":
    unittest.main()
