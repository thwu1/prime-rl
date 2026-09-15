
import subprocess
import os
import pytest


def compile_parser():
    """Attempt to build the parser using available build systems."""
    # Try cmake
    if os.path.exists("/app/CMakeLists.txt"):
        subprocess.run(
            ["cmake", "-B", "/app/build", "-S", "/app"],
            capture_output=True, text=True, timeout=30
        )
        subprocess.run(
            ["cmake", "--build", "/app/build"],
            capture_output=True, text=True, timeout=60
        )

    # Try make
    if os.path.exists("/app/Makefile"):
        subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=30
        )

    return os.path.isfile("/app/parser") and os.access("/app/parser", os.X_OK)


def run_parser(input_text: str) -> tuple[str, int]:
    r = subprocess.run(
        ["/app/parser"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return r.stdout.strip(), r.returncode


@pytest.fixture(scope="session", autouse=True)
def ensure_compiled():
    assert compile_parser(), "Parser binary not found at /app/parser after build"


# ---------------------------------------------------------------------------
# Basic arithmetic
# ---------------------------------------------------------------------------

class TestBasicArithmetic:
    def test_add(self):
        out, _ = run_parser("2 + 3;\n")
        assert out == "5"

    def test_sub(self):
        out, _ = run_parser("10 - 4;\n")
        assert out == "6"

    def test_mul(self):
        out, _ = run_parser("3 * 7;\n")
        assert out == "21"

    def test_div(self):
        out, _ = run_parser("20 / 4;\n")
        assert out == "5"

    def test_mod(self):
        out, _ = run_parser("10 % 3;\n")
        assert out == "1"

    def test_number(self):
        out, _ = run_parser("42;\n")
        assert out == "42"

    def test_parens(self):
        out, _ = run_parser("(2 + 3) * 4;\n")
        assert out == "20"

    def test_nested_parens(self):
        out, _ = run_parser("(2 + 3) * (4 - 1);\n")
        assert out == "15"


# ---------------------------------------------------------------------------
# Operator precedence across all levels
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_mul_then_add(self):
        """3 * 4 + 2 = 14, not 18."""
        out, _ = run_parser("3 * 4 + 2;\n")
        assert out == "14"

    def test_mixed_chain(self):
        """1 + 2 * 3 + 4 = 11."""
        out, _ = run_parser("1 + 2 * 3 + 4;\n")
        assert out == "11"

    def test_arith_vs_compare(self):
        """2 * 3 > 5 = (6 > 5) = 1, not 2 * 0 = 0."""
        out, _ = run_parser("2 * 3 > 5;\n")
        assert out == "1"

    def test_add_vs_compare(self):
        """3 + 1 > 3 = (4 > 3) = 1, not 3 + 0 = 3."""
        out, _ = run_parser("3 + 1 > 3;\n")
        assert out == "1"

    def test_compare_vs_and(self):
        """1 < 2 && 3 < 4 = (1) && (1) = 1, not 1 < (2&&(3<4)) = 0."""
        out, _ = run_parser("1 < 2 && 3 < 4;\n")
        assert out == "1"

    def test_and_vs_or(self):
        """0 && 1 || 1 = (0&&1) || 1 = 0 || 1 = 1, not 0&&(1||1) = 0."""
        out, _ = run_parser("0 && 1 || 1;\n")
        assert out == "1"

    def test_add_vs_ternary(self):
        """1 + 0 ? 10 : 20 = (1+0) ? 10 : 20 = 1?10:20 = 10."""
        out, _ = run_parser("1 + 0 ? 10 : 20;\n")
        assert out == "10"

    def test_sub_vs_ternary(self):
        """5 - 5 ? 1 : 2 = (5-5)?1:2 = 0?1:2 = 2."""
        out, _ = run_parser("5 - 5 ? 1 : 2;\n")
        assert out == "2"

    def test_compare_vs_or(self):
        """0 > 1 || 0 < 1 = (0>1) || (0<1) = 0 || 1 = 1."""
        out, _ = run_parser("0 > 1 || 0 < 1;\n")
        assert out == "1"


# ---------------------------------------------------------------------------
# Left-associativity
# ---------------------------------------------------------------------------

class TestAssociativity:
    def test_left_assoc_sub(self):
        """8 - 3 - 2 = (8-3)-2 = 3, not 8-(3-2)=7."""
        out, _ = run_parser("8 - 3 - 2;\n")
        assert out == "3"

    def test_left_assoc_div(self):
        """12 / 3 / 2 = (12/3)/2 = 2, not 12/(3/2)=12."""
        out, _ = run_parser("12 / 3 / 2;\n")
        assert out == "2"

    def test_left_assoc_mod(self):
        """100 % 7 % 3 = (100%7)%3 = 2%3 = 2, not 100%(7%3)=0."""
        out, _ = run_parser("100 % 7 % 3;\n")
        assert out == "2"

    def test_left_assoc_compare(self):
        """1 < 2 < 3 means (1<2) < 3 = 1 < 3 = 1."""
        out, _ = run_parser("1 < 2 < 3;\n")
        assert out == "1"


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class TestComparison:
    def test_lt(self):
        out, _ = run_parser("3 < 5;\n")
        assert out == "1"

    def test_gt(self):
        out, _ = run_parser("5 > 3;\n")
        assert out == "1"

    def test_le(self):
        out, _ = run_parser("3 <= 3;\n")
        assert out == "1"

    def test_ge_false(self):
        out, _ = run_parser("3 >= 4;\n")
        assert out == "0"

    def test_eq(self):
        out, _ = run_parser("5 == 5;\n")
        assert out == "1"

    def test_neq_true(self):
        """Requires lexer to correctly tokenize !=."""
        out, _ = run_parser("5 != 3;\n")
        assert out == "1"

    def test_neq_false(self):
        out, _ = run_parser("3 != 3;\n")
        assert out == "0"

    def test_neq_with_precedence(self):
        """1 + 2 != 3 = (1+2) != 3 = 3 != 3 = 0."""
        out, _ = run_parser("1 + 2 != 3;\n")
        assert out == "0"


# ---------------------------------------------------------------------------
# Logical operators and short-circuit evaluation
# ---------------------------------------------------------------------------

class TestLogicalOps:
    def test_and_tt(self):
        out, _ = run_parser("1 && 1;\n")
        assert out == "1"

    def test_and_tf(self):
        out, _ = run_parser("1 && 0;\n")
        assert out == "0"

    def test_or_ft(self):
        out, _ = run_parser("0 || 1;\n")
        assert out == "1"

    def test_or_ff(self):
        out, _ = run_parser("0 || 0;\n")
        assert out == "0"

    def test_not_zero(self):
        out, _ = run_parser("!0;\n")
        assert out == "1"

    def test_not_nonzero(self):
        out, _ = run_parser("!1;\n")
        assert out == "0"

    def test_not_expr(self):
        out, _ = run_parser("!(3 > 5);\n")
        assert out == "1"


class TestShortCircuit:
    def test_and_short(self):
        """0 && 1/0 must short-circuit to 0 without error."""
        out, _ = run_parser("0 && 1 / 0;\n")
        assert out == "0"

    def test_or_short(self):
        """1 || 1/0 must short-circuit to 1 without error."""
        out, _ = run_parser("1 || 1 / 0;\n")
        assert out == "1"

    def test_and_short_undef_var(self):
        """0 && novar must short-circuit to 0 without error."""
        out, _ = run_parser("0 && novar;\n")
        assert out == "0"

    def test_or_short_undef_var(self):
        """1 || novar must short-circuit to 1 without error."""
        out, _ = run_parser("1 || novar;\n")
        assert out == "1"

    def test_no_short_and_error(self):
        """1 && 1/0 does NOT short-circuit; should produce error with recovery."""
        out, _ = run_parser("1 && 1 / 0; 9;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("ERROR")
        assert lines[1] == "9"


# ---------------------------------------------------------------------------
# Ternary operator
# ---------------------------------------------------------------------------

class TestTernary:
    def test_true(self):
        out, _ = run_parser("1 ? 42 : 0;\n")
        assert out == "42"

    def test_false(self):
        out, _ = run_parser("0 ? 1 : 2;\n")
        assert out == "2"

    def test_nested_right_assoc(self):
        """1 ? 0 ? 3 : 4 : 5 = 1 ? (0?3:4) : 5 = 1?4:5 = 4."""
        out, _ = run_parser("1 ? 0 ? 3 : 4 : 5;\n")
        assert out == "4"

    def test_with_compare(self):
        """3 > 2 ? 10 : 20 = 1?10:20 = 10."""
        out, _ = run_parser("3 > 2 ? 10 : 20;\n")
        assert out == "10"

    def test_with_arith(self):
        """2 * 3 ? 10 + 1 : 20 + 2 = 6?11:22 = 11."""
        out, _ = run_parser("2 * 3 ? 10 + 1 : 20 + 2;\n")
        assert out == "11"


# ---------------------------------------------------------------------------
# Let-bindings (basic)
# ---------------------------------------------------------------------------

class TestLetBindings:
    def test_simple_let(self):
        out, _ = run_parser("let x = 5 in x + 1;\n")
        assert out == "6"

    def test_nested_let(self):
        out, _ = run_parser("let x = 3 in let y = 4 in x * y;\n")
        assert out == "12"

    def test_let_shadow(self):
        out, _ = run_parser("let x = 1 in let x = 2 in x;\n")
        assert out == "2"

    def test_let_with_arith_init(self):
        out, _ = run_parser("let x = 2 + 3 in x * 2;\n")
        assert out == "10"

    def test_let_in_ternary_branch(self):
        out, _ = run_parser("1 ? let x = 42 in x : 0;\n")
        assert out == "42"


# ---------------------------------------------------------------------------
# Scope isolation (let-binding scoping)
# ---------------------------------------------------------------------------

class TestScopeIsolation:
    def test_scope_shadow_restore(self):
        """Inner let shadows x=1 to x=2; after inner body, x should be 1 again.
        Result: (2) + (1) = 3, not (2) + (2) = 4."""
        out, _ = run_parser("let x = 1 in (let x = 2 in x) + x;\n")
        assert out == "3"

    def test_scope_after_let(self):
        """x should not be visible after the let body completes."""
        out, _ = run_parser("let x = 5 in x + 1; x;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0] == "6"
        assert lines[1].startswith("ERROR")

    def test_nested_scope_cleanup(self):
        """After nested lets, both bindings should be cleaned up."""
        out, _ = run_parser("let a = 1 in let b = 2 in a + b; a;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0] == "3"
        assert lines[1].startswith("ERROR")


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------

class TestUnary:
    def test_neg(self):
        out, _ = run_parser("-5 + 3;\n")
        assert out == "-2"

    def test_double_neg(self):
        out, _ = run_parser("--5;\n")
        assert out == "5"

    def test_pos(self):
        out, _ = run_parser("+5;\n")
        assert out == "5"

    def test_neg_in_mul(self):
        out, _ = run_parser("2 * -3;\n")
        assert out == "-6"

    def test_complex_unary(self):
        """2 * -3 + 1 = -6 + 1 = -5."""
        out, _ = run_parser("2 * -3 + 1;\n")
        assert out == "-5"


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------

class TestErrorRecovery:
    def test_error_then_valid(self):
        out, _ = run_parser("2 + ;\n3 + 4;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("ERROR")
        assert lines[1] == "7"

    def test_valid_error_valid(self):
        out, _ = run_parser("5;\n+ ;\n3;\n")
        lines = out.split("\n")
        assert len(lines) == 3
        assert lines[0] == "5"
        assert lines[1].startswith("ERROR")
        assert lines[2] == "3"

    def test_multiple_errors(self):
        out, _ = run_parser("+ ;\n* ;\n7;\n")
        lines = out.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("ERROR")
        assert lines[1].startswith("ERROR")
        assert lines[2] == "7"

    def test_div_zero_recovery(self):
        out, _ = run_parser("1 / 0;\n9;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("ERROR")
        assert lines[1] == "9"

    def test_mod_zero_recovery(self):
        out, _ = run_parser("7 % 0;\n3;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("ERROR")
        assert lines[1] == "3"

    def test_mismatched_paren(self):
        out, _ = run_parser("(2 + 3;\n8;\n")
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("ERROR")
        assert lines[1] == "8"


# ---------------------------------------------------------------------------
# Boolean literals
# ---------------------------------------------------------------------------

class TestBooleans:
    def test_true(self):
        out, _ = run_parser("true;\n")
        assert out == "1"

    def test_false(self):
        out, _ = run_parser("false;\n")
        assert out == "0"

    def test_true_and_true(self):
        out, _ = run_parser("true && true;\n")
        assert out == "1"

    def test_false_or_false(self):
        out, _ = run_parser("false || false;\n")
        assert out == "0"

    def test_not_true(self):
        out, _ = run_parser("!true;\n")
        assert out == "0"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_stmts(self):
        out, _ = run_parser(";;;\n")
        assert out == ""

    def test_comments(self):
        out, _ = run_parser("# comment\n2 + 3;\n")
        assert out == "5"

    def test_inline_comment(self):
        out, _ = run_parser("2 + 3; # comment\n4;\n")
        lines = out.split("\n")
        assert lines[0] == "5"
        assert lines[1] == "4"

    def test_multi_stmts(self):
        out, _ = run_parser("1 + 1; 2 * 3; 4 - 1;\n")
        lines = out.split("\n")
        assert lines == ["2", "6", "3"]

    def test_zero(self):
        out, _ = run_parser("0;\n")
        assert out == "0"

    def test_large_number(self):
        out, _ = run_parser("1000000 * 1000000;\n")
        assert out == "1000000000000"

    def test_empty_between_semis(self):
        out, _ = run_parser("5;; 10;\n")
        lines = out.split("\n")
        assert lines == ["5", "10"]
