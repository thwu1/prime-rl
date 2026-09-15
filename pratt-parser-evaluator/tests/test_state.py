
import subprocess
import pytest
import tempfile
import os


def _build():
    """Ensure the project is built."""
    if not os.path.exists("/app/minipratt"):
        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"Build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


class TestBuildAndTooling:
    """Verify the flex+make build pipeline works correctly."""

    def test_flex_specification_exists(self):
        assert os.path.exists("/app/lexer.l"), "lexer.l must exist"
        with open("/app/lexer.l") as f:
            content = f.read()
        assert "%%" in content, "lexer.l must contain flex section delimiters (%%)"

    def test_build_succeeds(self):
        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"make failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert os.path.exists("/app/minipratt"), "minipratt binary not produced"


TESTS = [
    (
        "basic_arith",
        "2 + 3 * 4",
        14,
    ),
    (
        "power_right_assoc",
        "2 ** 3 ** 2",
        512,
    ),
    (
        "unary_negation",
        "- - 3 + - 2",
        1,
    ),
    (
        "parentheses",
        "(2 + 3) * (7 - 4)",
        15,
    ),
    (
        "ternary",
        "3 > 2 ? 10 : 20",
        10,
    ),
    (
        "ternary_chain",
        "0 ? 1 : 0 ? 2 : 3",
        3,
    ),
    (
        "bitwise_precedence",
        "5 & 3 | 8 ^ 2",
        11,
    ),
    (
        "shift_vs_add",
        "1 << 3 + 1",
        16,
    ),
    (
        "let_binding",
        "let x = 10 in let y = x * 2 in y + x",
        30,
    ),
    (
        "function_call",
        "fn square(x) = x * x;\nsquare(7)",
        49,
    ),
    (
        "recursion",
        "fn fact(n) = if n <= 1 then 1 else n * fact(n - 1);\nfact(12)",
        479001600,
    ),
    (
        "mutual_recursion",
        "fn even(n) = if n == 0 then 1 else odd(n - 1);\n"
        "fn odd(n) = if n == 0 then 0 else even(n - 1);\n"
        "even(10) * 100 + odd(11)",
        101,
    ),
    (
        "custom_infix_left",
        "operator infixl 11 plus (a, b) = a + b;\n"
        "3 plus 4 * 2",
        11,
    ),
    (
        "custom_infix_right",
        "operator infixr 11 cat (a, b) = a * 10 + b;\n"
        "1 cat 2 cat 3",
        33,
    ),
    (
        "custom_prefix",
        "operator prefix 14 dbl (x) = x * 2;\n"
        "dbl 5 + 3",
        13,
    ),
    (
        "mixed_precedence",
        "2 + 3 * 4 ** 2 - 1",
        49,
    ),
    (
        "logical_short_circuit",
        "1 && 0 || 1 && 1",
        1,
    ),
    (
        "complex_program",
        "fn abs(x) = if x < 0 then 0 - x else x;\n"
        "fn gcd(a, b) = if b == 0 then a else gcd(b, a % b);\n"
        "operator infixl 12 divides (a, b) = if b % a == 0 then 1 else 0;\n"
        "let g = gcd(abs(0 - 48), abs(36)) in\n"
        "let check = g divides 48 in\n"
        "g * 1000 + check * 100 + gcd(100, 75)",
        12125,
    ),
]


@pytest.mark.parametrize(
    "name,program,expected",
    TESTS,
    ids=[t[0] for t in TESTS],
)
def test_minipratt(name, program, expected):
    """Run a MiniPratt program through the C binary and verify output."""
    _build()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mp", delete=False
    ) as f:
        f.write(program)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["/app/minipratt", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"minipratt exited with code {result.returncode}.\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )
        output = result.stdout.strip()
        assert output == str(expected), (
            f"For test '{name}':\n"
            f"  program: {program!r}\n"
            f"  expected: {expected}\n"
            f"  got:      {output!r}"
        )
    finally:
        os.unlink(tmp_path)
