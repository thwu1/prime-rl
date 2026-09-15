
"""
Tests for the scientific braille translation table.

Each test verifies that a specific input text produces the correct
Unicode braille output when forward-translated using lou_translate
with the sci-notation.ctb table and unicode.dis display table.

Unicode braille block (U+2800-U+28FF) encodes dot patterns as:
  U+2800 + sum(2^(dot-1) for each raised dot)

Key dot patterns used in expected outputs:
  numsign     = dots 3456 = U+283C
  capsletter  = dots 6    = U+2820
  prefix_ind  = dots 5    = U+2810 (function contraction prefix)
  superscript = dots 35   = U+2814
  subscript   = dots 16   = U+2821
  decimal_pt  = dots 46   = U+2828
  period      = dots 256  = U+2832
  comma       = dots 2    = U+2802
  plus        = dots 346  = U+282C
  minus       = dots 36   = U+2824
  equals      = dots 2356 = U+2836
  caret_sign  = dots 45   = U+2818
  uscore_sign = dots 456  = U+2838
  open_paren  = dots 12356= U+2837
  close_paren = dots 23456= U+283E
  space       = dots 0    = U+2800
"""

import os
import subprocess
import pytest

TABLE = "/app/tables/sci-notation.ctb"
DISPLAY = "unicode.dis"


def translate(text):
    """Forward-translate text using lou_translate with Unicode braille display."""
    env = os.environ.copy()
    env["LOUIS_TABLEPATH"] = "/usr/share/liblouis/tables"
    table_list = f"{DISPLAY},{TABLE}"
    result = subprocess.run(
        ["lou_translate", "-f", table_list],
        input=text + "\n",
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"lou_translate failed: stderr={result.stderr}"
    )
    lines = result.stdout.split("\n")
    return lines[0] if lines else ""


# =====================================================================
# Sanity checks — should pass with just character definitions
# =====================================================================


class TestSanity:
    def test_basic_word(self):
        """Basic lowercase word translates correctly."""
        # h=125, e=15, l=123, l=123, o=135
        assert translate("hello") == "\u2813\u2811\u2807\u2807\u2815"

    def test_basic_number(self):
        """Digits get number sign prefix."""
        # numsign=3456, 4=145, 2=12
        assert translate("42") == "\u283c\u2819\u2803"


# =====================================================================
# Function contraction tests
# =====================================================================


class TestFunctionContractions:
    """Function names must contract to prefix(5) + first letter,
    but ONLY when they appear as standalone words — never inside
    regular English words."""

    def test_sin(self):
        """'sin' contracts to prefix(5) + s(234)."""
        assert translate("sin") == "\u2810\u280e"

    def test_cos(self):
        """'cos' contracts to prefix(5) + c(14)."""
        assert translate("cos") == "\u2810\u2809"

    def test_tan(self):
        """'tan' contracts to prefix(5) + t(2345)."""
        assert translate("tan") == "\u2810\u281e"

    def test_log(self):
        """'log' contracts to prefix(5) + l(123)."""
        assert translate("log") == "\u2810\u2807"

    def test_exp(self):
        """'exp' contracts to prefix(5) + e(15)."""
        assert translate("exp") == "\u2810\u2811"

    def test_sin_not_in_since(self):
        """'sin' must NOT contract inside 'since'."""
        # s=234, i=24, n=1345, c=14, e=15
        assert translate("since") == "\u280e\u280a\u281d\u2809\u2811"

    def test_sin_not_in_basin(self):
        """'sin' must NOT contract inside 'basin'."""
        # b=12, a=1, s=234, i=24, n=1345
        assert translate("basin") == "\u2803\u2801\u280e\u280a\u281d"

    def test_cos_not_in_cosine(self):
        """'cos' must NOT contract inside 'cosine'."""
        # c=14, o=135, s=234, i=24, n=1345, e=15
        assert translate("cosine") == "\u2809\u2815\u280e\u280a\u281d\u2811"

    def test_exp_not_in_explore(self):
        """'exp' must NOT contract inside 'explore'."""
        # e=15, x=1346, p=1234, l=123, o=135, r=1235, e=15
        assert translate("explore") == "\u2811\u282d\u280f\u2807\u2815\u2817\u2811"

    def test_sin_before_parens(self):
        """'sin(x)' must contract 'sin' — parens are word boundaries."""
        # prefix(5) s(234) open_paren(12356) x(1346) close_paren(23456)
        assert translate("sin(x)") == "\u2810\u280e\u2837\u282d\u283e"


# =====================================================================
# Decimal point and number formatting tests
# =====================================================================


class TestDecimalHandling:
    """Period between digits = decimal (dots 46). Period elsewhere =
    sentence punctuation (dots 256). Commas between digits = thousands
    separator keeping one number sign."""

    def test_period_end_of_word(self):
        """Period after a word uses punctuation dots 256."""
        # e=15, n=1345, d=145, period=256
        assert translate("end.") == "\u2811\u281d\u2819\u2832"

    def test_decimal_between_digits(self):
        """Period between digits becomes decimal point (dots 46)."""
        # numsign=3456, 3=14, decimal=46, 1=1, 4=145
        assert translate("3.14") == "\u283c\u2809\u2828\u2801\u2819"

    def test_leading_decimal(self):
        """Leading decimal '.5' treated as number with decpoint."""
        # numsign=3456, decimal=46, 5=15
        assert translate(".5") == "\u283c\u2828\u2811"

    def test_thousands_separator(self):
        """Comma between digits keeps one number sign for entire number."""
        # numsign=3456, 1=1, comma=2, 2=12, 3=14, 4=145
        assert translate("1,234") == "\u283c\u2801\u2802\u2803\u2809\u2819"


# =====================================================================
# Superscript and subscript notation tests
# =====================================================================


class TestSuperscriptSubscript:
    """Caret before digit(s) -> superscript indicator (dots 35).
    Underscore before digit(s) -> subscript indicator (dots 16).
    Before non-digits, they keep their default sign representation.
    Pass2 removes the redundant number sign after these indicators."""

    def test_superscript_digit(self):
        """'x^2' -> x + superscript(35) + 2 (numsign removed by pass2)."""
        # x=1346, superscript=35, 2=12
        assert translate("x^2") == "\u282d\u2814\u2803"

    def test_subscript_digit(self):
        """'h_2' -> h + subscript(16) + 2 (numsign removed by pass2)."""
        # h=125, subscript=16, 2=12
        assert translate("h_2") == "\u2813\u2821\u2803"

    def test_caret_before_letter(self):
        """'e^x' -> caret stays as sign (dots 45) since x is not a digit."""
        # e=15, caret_sign=45, x=1346
        assert translate("e^x") == "\u2811\u2818\u282d"

    def test_subscript_then_superscript(self):
        """'x_1^2' -> both indicators fire, both numsigns removed."""
        # x=1346, subscript=16, 1=1, superscript=35, 2=12
        assert translate("x_1^2") == "\u282d\u2821\u2801\u2814\u2803"


# =====================================================================
# Expression cleanup tests (pass2 number sign removal)
# =====================================================================


class TestExpressionCleanup:
    """Pass2 rules remove redundant number signs after operators (+,-,=).
    The leading number sign is preserved; subsequent number signs after
    operators are deleted."""

    def test_plus(self):
        """'3+4' -> numsign 3 plus 4 (second numsign removed)."""
        # numsign=3456, 3=14, plus=346, 4=145
        assert translate("3+4") == "\u283c\u2809\u282c\u2819"

    def test_minus(self):
        """'3-4' -> numsign 3 minus 4 (second numsign removed)."""
        # numsign=3456, 3=14, minus=36, 4=145
        assert translate("3-4") == "\u283c\u2809\u2824\u2819"

    def test_equals(self):
        """'3=4' -> numsign 3 equals 4 (second numsign removed)."""
        # numsign=3456, 3=14, equals=2356, 4=145
        assert translate("3=4") == "\u283c\u2809\u2836\u2819"

    def test_chain(self):
        """'2+3=5' -> numsign 2 plus 3 equals 5 (all inner numsigns removed)."""
        # numsign=3456, 2=12, plus=346, 3=14, equals=2356, 5=15
        assert translate("2+3=5") == "\u283c\u2803\u282c\u2809\u2836\u2811"


# =====================================================================
# Combined / edge case tests
# =====================================================================


class TestCombined:
    """Tests combining multiple features to verify correct interaction
    between function contractions, decimal handling, superscript/subscript
    notation, and expression cleanup."""

    def test_function_with_superscript(self):
        """'sin x^2' -> contracted sin + space + x with superscript."""
        # prefix(5) s(234) space(0) x(1346) superscript(35) 2(12)
        assert translate("sin x^2") == "\u2810\u280e\u2800\u282d\u2814\u2803"

    def test_expression_with_superscripts(self):
        """'a^2+b^2' -> both superscript numsigns removed, no operator numsign issue."""
        # a(1) superscript(35) 2(12) plus(346) b(12) superscript(35) 2(12)
        assert translate("a^2+b^2") == "\u2801\u2814\u2803\u282c\u2803\u2814\u2803"

    def test_decimal_with_superscript(self):
        """'3.14^2' -> decimal number then superscript (numsign removed after ^)."""
        # numsign(3456) 3(14) decimal(46) 1(1) 4(145) superscript(35) 2(12)
        assert translate("3.14^2") == "\u283c\u2809\u2828\u2801\u2819\u2814\u2803"

    def test_function_with_decimal_arg(self):
        """'cos(3.14)' -> contracted cos + parens around decimal number."""
        # prefix(5) c(14) open_paren(12356) numsign(3456) 3(14) decimal(46) 1(1) 4(145) close_paren(23456)
        assert translate("cos(3.14)") == "\u2810\u2809\u2837\u283c\u2809\u2828\u2801\u2819\u283e"

    def test_decimal_chain_with_cleanup(self):
        """'3.14+2.71' -> first number + plus + second number (numsign removed after +)."""
        # numsign(3456) 3(14) decimal(46) 1(1) 4(145) plus(346) 2(12) decimal(46) 7(1245) 1(1)
        assert translate("3.14+2.71") == "\u283c\u2809\u2828\u2801\u2819\u282c\u2803\u2828\u281b\u2801"

    def test_subscript_in_expression(self):
        """'v_0 = 3.14' -> subscript + space + equals + space + decimal number."""
        # v(1236) subscript(16) 0(245) space(0) equals(2356) space(0) numsign(3456) 3(14) decimal(46) 1(1) 4(145)
        assert translate("v_0 = 3.14") == "\u2827\u2821\u281a\u2800\u2836\u2800\u283c\u2809\u2828\u2801\u2819"

    def test_multi_digit_superscript(self):
        """'x^23' -> superscript indicator + both digits (numsign removed)."""
        # x(1346) superscript(35) 2(12) 3(14)
        assert translate("x^23") == "\u282d\u2814\u2803\u2809"
