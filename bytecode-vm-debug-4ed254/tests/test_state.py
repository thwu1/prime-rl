"""
Tests for the bytecode expression evaluator.

Verifies correct evaluation and disassembly across all expression types:
arithmetic, comparisons, boolean short-circuit, ternary, nil coalescing,
ranges, membership testing, array/map operations, predicate builtins
(filter, map, any, all, count, reduce), and bytecode disassembly output.

"""
import json
import subprocess
import pytest

BINARY = "/app/evaluator"
APP_DIR = "/app"


@pytest.fixture(scope="session", autouse=True)
def build_evaluator():
    """Build the Go evaluator binary once before all tests."""
    result = subprocess.run(
        ["go", "build", "-o", BINARY, "."],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Build failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def evaluate(expr, env=None):
    """Run an expression through the evaluator and return the result."""
    if env is None:
        env = {}
    input_data = json.dumps({"expr": expr, "env": env})
    result = subprocess.run(
        [BINARY],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Evaluation failed for expr={expr!r}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout.strip())


def disasm(expr):
    """Run --disasm on an expression and return the output."""
    input_data = json.dumps({"expr": expr, "env": {}})
    result = subprocess.run(
        [BINARY, "--disasm"],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Disasm failed for expr={expr!r}: {result.stderr.strip()}"
        )
    return result.stdout


# ===== Basic Arithmetic =====

class TestArithmetic:
    def test_add(self):
        assert evaluate("1 + 2") == 3

    def test_subtract(self):
        assert evaluate("10 - 3") == 7

    def test_multiply(self):
        assert evaluate("4 * 5") == 20

    def test_divide(self):
        assert evaluate("10 / 2") == 5

    def test_modulo(self):
        assert evaluate("10 % 3") == 1

    def test_precedence(self):
        assert evaluate("10 - 3 * 2") == 4

    def test_parens(self):
        assert evaluate("(1 + 2) * 3") == 9

    def test_negate(self):
        assert evaluate("-5 + 3") == -2

    def test_complex_expr(self):
        assert evaluate("(10 + 5) / 3 + 2 * 4") == 13


# ===== Comparisons =====

class TestComparisons:
    def test_eq_true(self):
        assert evaluate("3 == 3") is True

    def test_eq_false(self):
        assert evaluate("3 == 4") is False

    def test_neq(self):
        assert evaluate("1 != 2") is True

    def test_lt(self):
        assert evaluate("1 < 2") is True

    def test_gt(self):
        assert evaluate("2 > 1") is True

    def test_lteq(self):
        assert evaluate("5 <= 5") is True

    def test_gteq(self):
        assert evaluate("5 >= 5") is True

    def test_not_true(self):
        assert evaluate("!true") is False

    def test_not_false(self):
        assert evaluate("!false") is True


# ===== Boolean Short-Circuit =====

class TestBooleanLogic:
    def test_and_true_true(self):
        assert evaluate("true && true") is True

    def test_and_true_false(self):
        assert evaluate("true && false") is False

    def test_and_false_true(self):
        assert evaluate("false && true") is False

    def test_and_false_false(self):
        assert evaluate("false && false") is False

    def test_or_true_false(self):
        assert evaluate("true || false") is True

    def test_or_false_true(self):
        assert evaluate("false || true") is True

    def test_or_false_false(self):
        assert evaluate("false || false") is False

    def test_or_true_true(self):
        assert evaluate("true || true") is True

    def test_short_circuit_and(self):
        """false && (1/0 > 0) must short-circuit; evaluating 1/0 would panic."""
        assert evaluate("false && (1 / 0 > 0)") is False

    def test_short_circuit_or(self):
        """true || (1/0 > 0) must short-circuit; evaluating 1/0 would panic."""
        assert evaluate("true || (1 / 0 > 0)") is True

    def test_compound_logic(self):
        assert evaluate("(1 < 2) && (3 > 1)") is True

    def test_compound_or(self):
        assert evaluate("(1 > 2) || (3 > 1)") is True


# ===== Ternary =====

class TestTernary:
    def test_true_branch(self):
        assert evaluate("true ? 1 : 2") == 1

    def test_false_branch(self):
        assert evaluate("false ? 1 : 2") == 2

    def test_expr_cond(self):
        assert evaluate("1 > 0 ? 10 : 20") == 10

    def test_nested_ternary(self):
        assert evaluate("true ? (false ? 1 : 2) : 3") == 2


# ===== Arrays =====

class TestArrays:
    def test_literal(self):
        assert evaluate("[1, 2, 3]") == [1, 2, 3]

    def test_index_first(self):
        assert evaluate("[10, 20, 30][0]") == 10

    def test_index_last(self):
        assert evaluate("[10, 20, 30][2]") == 30

    def test_len(self):
        assert evaluate("len([1, 2, 3])") == 3

    def test_empty(self):
        assert evaluate("[]") == []

    def test_nested(self):
        assert evaluate("[[1, 2], [3, 4]][1][0]") == 3


# ===== Maps =====

class TestMaps:
    def test_access(self):
        assert evaluate('{"a": 1, "b": 2}["a"]') == 1

    def test_access_second(self):
        assert evaluate('{"x": 10, "y": 20}["y"]') == 20


# ===== In Operator =====

class TestInOperator:
    def test_in_array_found(self):
        assert evaluate("2 in [1, 2, 3]") is True

    def test_in_array_not_found(self):
        assert evaluate("4 in [1, 2, 3]") is False

    def test_in_map_found(self):
        assert evaluate('"a" in {"a": 1, "b": 2}') is True

    def test_in_map_not_found(self):
        assert evaluate('"c" in {"a": 1, "b": 2}') is False

    def test_in_range(self):
        assert evaluate("3 in 1..5") is True

    def test_not_in_range(self):
        assert evaluate("6 in 1..5") is False


# ===== Range =====

class TestRange:
    def test_simple_range(self):
        assert evaluate("1..5") == [1, 2, 3, 4, 5]

    def test_range_len(self):
        assert evaluate("len(1..5)") == 5

    def test_single_element_range(self):
        assert evaluate("3..3") == [3]

    def test_range_index(self):
        assert evaluate("(1..5)[0]") == 1

    def test_range_last(self):
        assert evaluate("(1..5)[4]") == 5


# ===== Nil Coalescing =====

class TestNilCoalescing:
    def test_nil_fallback(self):
        assert evaluate("nil ?? 42") == 42

    def test_non_nil_keeps(self):
        assert evaluate("1 ?? 42") == 1

    def test_env_nil_fallback(self):
        assert evaluate("x ?? 99", {"x": None}) == 99

    def test_env_non_nil_keeps(self):
        assert evaluate("x ?? 99", {"x": 7}) == 7


# ===== Environment Variables =====

class TestEnv:
    def test_simple(self):
        assert evaluate("x + 1", {"x": 5}) == 6

    def test_comparison(self):
        assert evaluate("x > 0", {"x": 5}) is True

    def test_multiple_vars(self):
        assert evaluate("x + y", {"x": 3, "y": 7}) == 10


# ===== Filter =====

class TestFilter:
    def test_basic(self):
        assert evaluate("filter([10, 20, 30], # > 15)") == [20, 30]

    def test_all_pass(self):
        assert evaluate("filter([1, 2, 3], # > 0)") == [1, 2, 3]

    def test_none_pass(self):
        assert evaluate("filter([1, 2, 3], # > 10)") == []

    def test_with_range(self):
        assert evaluate("filter(1..10, # > 5)") == [6, 7, 8, 9, 10]

    def test_even_numbers(self):
        assert evaluate("filter(1..10, # % 2 == 0)") == [2, 4, 6, 8, 10]

    def test_with_index(self):
        assert evaluate("filter([10, 20, 30], #index > 0)") == [20, 30]


# ===== Map =====

class TestMapBuiltin:
    def test_double(self):
        assert evaluate("map([1, 2, 3], # * 2)") == [2, 4, 6]

    def test_add_const(self):
        assert evaluate("map([10, 20, 30], # + 5)") == [15, 25, 35]

    def test_with_range(self):
        assert evaluate("map(1..5, # * # )") == [1, 4, 9, 16, 25]

    def test_negate(self):
        assert evaluate("map([1, 2, 3], -#)") == [-1, -2, -3]

    def test_with_index(self):
        assert evaluate("map([10, 20, 30], # + #index)") == [10, 21, 32]


# ===== Any / All =====

class TestAnyAll:
    def test_any_true(self):
        assert evaluate("any([1, 2, 3], # > 2)") is True

    def test_any_false(self):
        assert evaluate("any([1, 2, 3], # > 5)") is False

    def test_any_eq(self):
        assert evaluate("any([1, 2, 3], # == 2)") is True

    def test_all_true(self):
        assert evaluate("all([1, 2, 3], # > 0)") is True

    def test_all_false(self):
        assert evaluate("all([1, 2, 3], # > 2)") is False

    def test_any_empty(self):
        assert evaluate("any([], # > 0)") is False

    def test_all_empty(self):
        assert evaluate("all([], # > 0)") is True

    def test_any_with_range(self):
        assert evaluate("any(1..10, # > 9)") is True

    def test_all_with_range(self):
        assert evaluate("all(1..5, # > 0)") is True


# ===== Count =====

class TestCount:
    def test_basic(self):
        assert evaluate("count([1, 2, 3, 4, 5], # > 3)") == 2

    def test_none(self):
        assert evaluate("count([1, 2, 3], # > 10)") == 0

    def test_all(self):
        assert evaluate("count([1, 2, 3], # > 0)") == 3

    def test_with_range(self):
        assert evaluate("count(1..20, # % 3 == 0)") == 6

    def test_even_in_range(self):
        assert evaluate("count(1..10, # % 2 == 0)") == 5


# ===== Reduce =====

class TestReduce:
    def test_sum(self):
        assert evaluate("reduce([1, 2, 3, 4], # + #acc, 0)") == 10

    def test_product(self):
        assert evaluate("reduce([1, 2, 3, 4], # * #acc, 1)") == 24

    def test_string_concat(self):
        assert evaluate('reduce(["a", "b", "c"], # + #acc, "")') == "cba"

    def test_with_range(self):
        assert evaluate("reduce(1..5, # + #acc, 0)") == 15

    def test_single_element(self):
        assert evaluate("reduce([42], # + #acc, 0)") == 42


# ===== Combined / Integration =====

class TestIntegration:
    def test_filter_then_len(self):
        assert evaluate("len(filter(1..10, # > 5))") == 5

    def test_map_then_reduce(self):
        assert evaluate("reduce(map([1, 2, 3], # * 2), # + #acc, 0)") == 12

    def test_nested_any(self):
        assert evaluate("any([1, 2, 3], # > 1 && # < 3)") is True

    def test_ternary_with_env(self):
        assert evaluate("x > 0 ? x * 2 : -x", {"x": 5}) == 10

    def test_ternary_with_env_neg(self):
        assert evaluate("x > 0 ? x * 2 : -x", {"x": -3}) == 3

    def test_nil_coalesce_in_expr(self):
        assert evaluate("(x ?? 0) + 10", {"x": None}) == 10

    def test_complex_filter(self):
        assert evaluate("filter(1..20, # % 2 == 0 && # > 10)") == [12, 14, 16, 18, 20]

    def test_nested_filter_map(self):
        assert evaluate("map(filter([1, 2, 3, 4, 5], # > 2), # * 10)") == [30, 40, 50]

    def test_reduce_over_range(self):
        assert evaluate("reduce(1..5, # + #acc, 0)") == 15

    def test_count_even_range(self):
        assert evaluate("count(1..10, # % 2 == 0)") == 5

    def test_or_with_ternary(self):
        assert evaluate("(false || true) ? 1 : 0") == 1

    def test_nil_coalesce_chain(self):
        assert evaluate("nil ?? nil ?? 7") == 7


# ===== Disassembler =====

class TestDisasm:
    def test_simple_add(self):
        output = disasm("1 + 2")
        assert "OpPush" in output
        assert "OpAdd" in output
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 3

    def test_constant_annotation(self):
        output = disasm("1 + 2")
        assert "; 1" in output
        assert "; 2" in output

    def test_address_format(self):
        output = disasm("1 + 2")
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert lines[0].startswith("0000")
        assert lines[1].startswith("0001")
        assert lines[2].startswith("0002")

    def test_ternary_uses_jump_if_false(self):
        output = disasm("true ? 1 : 2")
        assert "OpJumpIfFalse" in output
        assert "OpJumpIfTrue" not in output or "OpTrue" in output

    def test_or_uses_jump_if_true(self):
        output = disasm("true || false")
        assert "OpJumpIfTrue" in output

    def test_and_uses_jump_if_false(self):
        output = disasm("true && false")
        assert "OpJumpIfFalse" in output

    def test_nil_coalesce_uses_jump_if_not_nil(self):
        output = disasm("nil ?? 42")
        assert "OpJumpIfNotNil" in output

    def test_filter_has_scope_ops(self):
        output = disasm("filter([1, 2, 3], # > 1)")
        assert "OpBegin" in output
        assert "OpEnd" in output
        assert "OpJumpIfEnd" in output
        assert "OpPointer" in output
        assert "OpIncrIndex" in output

    def test_reduce_has_acc_ops(self):
        output = disasm("reduce([1, 2, 3], # + #acc, 0)")
        assert "OpSetAcc" in output
        assert "OpGetAcc" in output
        assert "OpBegin" in output

    def test_string_constant_quoted(self):
        output = disasm('"hello"')
        assert '"hello"' in output

    def test_loadenv(self):
        input_data = json.dumps({"expr": "x + 1", "env": {"x": 5}})
        result = subprocess.run(
            [BINARY, "--disasm"],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        output = result.stdout
        assert "OpLoadEnv" in output
        assert '"x"' in output
