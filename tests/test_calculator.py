from decimal import Decimal
import unittest

from services.calculator import (
    CalculationError,
    evaluate_tokens,
    format_decimal,
    format_grouped_hundredths,
    format_hundredths,
    evaluate_running_tokens,
    parse_numeric_expression,
    render_normal_calculation,
    render_tape_html,
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

    def test_normal_calculation_uses_running_grouped_ledger_format(self) -> None:
        tokens = parse_numeric_expression("2,621,878.49 + 5,000 * 44.90")
        self.assertEqual(format_grouped_hundredths("1000"), "1,000.00")
        self.assertEqual(evaluate_running_tokens(tokens)["result"], "117946844.201")
        self.assertEqual(
            render_normal_calculation(tokens),
            "<pre>+ 2,621,878.49\n"
            "+ 5,000.00\n"
            "---------------\n"
            "+ 2,626,878.49\n"
            "* 44.90\n"
            "---------------\n"
            "+ 117,946,844.20</pre>",
        )

    def test_parentheses_work_in_long_numeric_expression(self) -> None:
        result = evaluate_tokens(parse_numeric_expression("(1,000 + 5,000) * 2"))
        self.assertEqual(result["result"], "12000")

    def test_running_steps_are_json_safe_and_left_to_right(self) -> None:
        result = evaluate_running_tokens(["2621878.49", "+", "5000", "*", "44.90"])
        self.assertEqual(result["result"], "117946844.201")
        self.assertEqual(result["steps"][1]["subtotal"], "2626878.49")
        self.assertIsInstance(result["steps"][2]["operand"], str)

    def test_running_percentage_is_a_tape_step(self) -> None:
        result = evaluate_running_tokens(["100", "+1%", "*", "2"])
        self.assertEqual(result["result"], "202")
        self.assertTrue(result["steps"][1]["percentage"])
        self.assertEqual(result["steps"][1]["operand"], "1%")

    def test_running_addition_accepts_zero(self) -> None:
        result = evaluate_running_tokens(["25", "+", "0"])
        self.assertEqual(result["result"], "25")

    def test_tape_share_contains_subtotals_and_escaped_labels(self) -> None:
        rendered = render_tape_html("Зардал", [
            {"operator": "+", "value": "1000", "label": "CBR <USD>"},
            {"operator": "*", "value": "2"},
        ])
        self.assertIn("<b>Зардал</b>", rendered)
        self.assertIn("CBR &lt;USD&gt;", rendered)
        self.assertIn("+ 2,000.00", rendered)


if __name__ == "__main__":
    unittest.main()
