"""Tests for MiniCalc bytecode optimizer.

Verifies that:
1. Optimized bytecode produces identical output to unoptimized for all programs
2. Specific optimization patterns are applied correctly
3. Instruction counts decrease where optimizations should apply

"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, "/opt/minicalc")


def compile_source(source_code):
    """Compile MiniCalc source to bytecode dict."""
    from compiler import compile_source as _compile
    return _compile(source_code)


def run_bytecode_dict(bytecode):
    """Run bytecode through VM, return output string."""
    from vm import run_bytecode
    return run_bytecode(bytecode)


def run_optimizer(bytecode):
    """Run the optimizer on bytecode, return optimized bytecode dict."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fin:
        json.dump(bytecode, fin)
        in_path = fin.name
    out_path = in_path + ".opt.json"
    try:
        result = subprocess.run(
            [sys.executable, "/app/optimizer.py", in_path, out_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Optimizer failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        with open(out_path) as f:
            return json.load(f)
    finally:
        for p in [in_path, out_path]:
            if os.path.exists(p):
                os.unlink(p)


def count_instructions(bytecode):
    """Count total instructions across all code blocks."""
    total = len(bytecode["main"])
    for func_info in bytecode.get("functions", {}).values():
        total += len(func_info["code"])
    return total


def has_consecutive_opcodes(code, opcodes):
    """Check if code contains a consecutive sequence of the given opcodes."""
    for i in range(len(code) - len(opcodes) + 1):
        if all(code[i + j][0] == opcodes[j] for j in range(len(opcodes))):
            return True
    return False


def find_opcode_sequences(code, opcodes):
    """Find all positions where a consecutive opcode sequence appears."""
    positions = []
    for i in range(len(code) - len(opcodes) + 1):
        if all(code[i + j][0] == opcodes[j] for j in range(len(opcodes))):
            positions.append(i)
    return positions


def count_opcode(code, opcode):
    """Count occurrences of a specific opcode in code."""
    return sum(1 for instr in code if instr[0] == opcode)


# ---------------------------------------------------------------------------
# Load and compile all test programs from /opt/minicalc/programs/
# ---------------------------------------------------------------------------

PROGRAMS_DIR = "/opt/minicalc/programs"

PROGRAM_EXPECTED_OUTPUT = {
    "01_const_fold.mc": "5\n47\n31\n1\n",
    "02_dead_store.mc": "42\n3\n",
    "03_const_prop.mc": "30\n35\n",
    "04_dead_branch.mc": "1\n3\n5\n",
    "05_identity_ops.mc": "5\n5\n5\n",
    "06_mixed_opts.mc": "10\n5\n",
    "07_functions.mc": "16\n11\n0\n",
    "08_fibonacci.mc": "0\n1\n1\n2\n3\n5\n8\n13\n21\n34\n",
    "09_gcd.mc": "6\n25\n1\n",
    "10_primes.mc": "10\n",
    "11_nested_loops.mc": "60\n",
    "12_global_funcs.mc": "15\n45\n46\n",
}


def get_program_files():
    return sorted(f for f in os.listdir(PROGRAMS_DIR) if f.endswith(".mc"))


# ---------------------------------------------------------------------------
# Semantic equivalence tests: optimized output must match unoptimized
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("program", get_program_files())
def test_semantic_equivalence(program):
    """Optimized bytecode must produce identical output to original."""
    src_path = os.path.join(PROGRAMS_DIR, program)
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    expected = run_bytecode_dict(bytecode)

    # Verify unoptimized output matches known expected
    if program in PROGRAM_EXPECTED_OUTPUT:
        assert expected == PROGRAM_EXPECTED_OUTPUT[program], (
            f"Unoptimized output mismatch for {program}:\n"
            f"  got:      {expected!r}\n"
            f"  expected: {PROGRAM_EXPECTED_OUTPUT[program]!r}"
        )

    optimized = run_optimizer(bytecode)
    actual = run_bytecode_dict(optimized)
    assert actual == expected, (
        f"Optimized output differs for {program}:\n"
        f"  original:  {expected!r}\n"
        f"  optimized: {actual!r}"
    )


# ---------------------------------------------------------------------------
# Constant folding tests
# ---------------------------------------------------------------------------

def test_constant_folding_eliminates_literal_arithmetic():
    """After optimization, `2 + 3` should become a single PUSH_INT 5."""
    source = "x = 2 + 3;\nprint x;\n"
    bytecode = compile_source(source)
    # Unoptimized should have PUSH_INT, PUSH_INT, ADD
    assert has_consecutive_opcodes(bytecode["main"], ["PUSH_INT", "PUSH_INT", "ADD"])
    optimized = run_optimizer(bytecode)
    # Optimized should NOT have two consecutive PUSH_INT followed by ADD
    assert not has_consecutive_opcodes(optimized["main"], ["PUSH_INT", "PUSH_INT", "ADD"]), \
        "Constant folding did not eliminate PUSH_INT 2, PUSH_INT 3, ADD"


def test_constant_folding_chain():
    """Chained constant expressions: 2 + 3 * 4 should fully fold."""
    source = "x = 2 + 3 * 4;\nprint x;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    # Should not have any binary arithmetic between two PUSH_INTs
    for op in ["ADD", "SUB", "MUL", "DIV", "MOD"]:
        assert not has_consecutive_opcodes(optimized["main"], ["PUSH_INT", "PUSH_INT", op]), \
            f"Constant folding failed to eliminate PUSH_INT, PUSH_INT, {op}"
    # Output must still be correct
    assert run_bytecode_dict(optimized) == "14\n"


def test_constant_folding_comparison():
    """Constant comparison: 10 > 5 should fold to 1."""
    source = "x = 10 > 5;\nprint x;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert not has_consecutive_opcodes(optimized["main"], ["PUSH_INT", "PUSH_INT", "GT"])
    assert run_bytecode_dict(optimized) == "1\n"


def test_constant_folding_unary_neg():
    """PUSH_INT 5, NEG should fold to PUSH_INT -5."""
    source = "x = -5;\nprint x;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert not has_consecutive_opcodes(optimized["main"], ["PUSH_INT", "NEG"])
    assert run_bytecode_dict(optimized) == "-5\n"


# ---------------------------------------------------------------------------
# Constant propagation tests
# ---------------------------------------------------------------------------

def test_constant_propagation_simple():
    """After `a = 5;`, LOAD a should be replaced with PUSH_INT 5."""
    source = "a = 5;\nb = a + 10;\nprint b;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "15\n"
    # After full optimization (prop + fold), no LOADs for 'a' should remain in main
    loads_a = [i for i in optimized["main"] if i[0] == "LOAD" and i[1] == "a"]
    assert len(loads_a) == 0, "Constant propagation did not replace LOAD a"


def test_constant_propagation_chain():
    """Propagation through a chain: a=5, b=a+10 (=15), c=b*2 (=30)."""
    source = "a = 5;\nb = a + 10;\nc = b * 2;\nprint c;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "30\n"


# ---------------------------------------------------------------------------
# Dead store elimination tests
# ---------------------------------------------------------------------------

def test_dead_store_elimination():
    """Stores that are overwritten before being read should be eliminated."""
    source = "x = 100;\nx = 200;\nx = 42;\nprint x;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "42\n"
    # Should have fewer instructions
    assert count_instructions(optimized) < count_instructions(bytecode), \
        "Dead store elimination did not reduce instruction count"


def test_dead_store_not_eliminated_when_read():
    """A store that IS read before overwrite must NOT be eliminated."""
    source = "x = 5;\nprint x;\nx = 10;\nprint x;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "5\n10\n"


# ---------------------------------------------------------------------------
# Unreachable code elimination tests
# ---------------------------------------------------------------------------

def test_unreachable_after_return():
    """Code after return in a function should be removed."""
    source = (
        "func f(n) {\n"
        "    return n + 1;\n"
        "    print 999;\n"
        "    return n + 2;\n"
        "}\n"
        "print f(5);\n"
    )
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "6\n"
    # The optimized function code should be shorter
    orig_func_len = len(bytecode["functions"]["f"]["code"])
    opt_func_len = len(optimized["functions"]["f"]["code"])
    assert opt_func_len < orig_func_len, \
        "Unreachable code after return was not eliminated"


# ---------------------------------------------------------------------------
# Algebraic identity tests
# ---------------------------------------------------------------------------

def test_add_zero_identity():
    """x + 0 should simplify to just x."""
    source = "x = 7;\ny = x + 0;\nprint y;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "7\n"
    # Should not have PUSH_INT 0, ADD sequence
    assert not has_consecutive_opcodes(optimized["main"], ["PUSH_INT", "ADD"]) or \
        all(optimized["main"][i+1][0] != "ADD" or optimized["main"][i][1] != 0
            for i in range(len(optimized["main"]) - 1)
            if optimized["main"][i][0] == "PUSH_INT"), \
        "Identity x + 0 was not simplified"


def test_mul_one_identity():
    """x * 1 should simplify to just x."""
    source = "x = 13;\ny = x * 1;\nprint y;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "13\n"


def test_sub_zero_identity():
    """x - 0 should simplify to just x."""
    source = "x = 42;\ny = x - 0;\nprint y;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "42\n"


# ---------------------------------------------------------------------------
# Peephole optimization tests
# ---------------------------------------------------------------------------

def test_double_not_elimination():
    """NOT NOT should cancel out (for boolean context)."""
    source = "x = 1;\ny = !!x;\nprint y;\n"
    bytecode = compile_source(source)
    # Unoptimized should have two NOTs
    assert has_consecutive_opcodes(bytecode["main"], ["NOT", "NOT"])
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "1\n"
    # Should not have consecutive NOT NOT
    assert not has_consecutive_opcodes(optimized["main"], ["NOT", "NOT"]), \
        "Double NOT was not eliminated"


def test_double_neg_elimination():
    """NEG NEG should cancel out."""
    source = "x = 5;\ny = -(-x);\nprint y;\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == "5\n"
    assert not has_consecutive_opcodes(optimized["main"], ["NEG", "NEG"]), \
        "Double NEG was not eliminated"


# ---------------------------------------------------------------------------
# Overall instruction reduction tests
# ---------------------------------------------------------------------------

def test_instruction_reduction_const_fold():
    """Constant folding program should have fewer instructions after optimization."""
    src_path = os.path.join(PROGRAMS_DIR, "01_const_fold.mc")
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    orig_count = count_instructions(bytecode)
    opt_count = count_instructions(optimized)
    assert opt_count < orig_count, (
        f"Expected instruction reduction for const_fold: orig={orig_count}, opt={opt_count}")


def test_instruction_reduction_dead_store():
    """Dead store program should have fewer instructions after optimization."""
    src_path = os.path.join(PROGRAMS_DIR, "02_dead_store.mc")
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    orig_count = count_instructions(bytecode)
    opt_count = count_instructions(optimized)
    assert opt_count < orig_count, (
        f"Expected instruction reduction for dead_store: orig={orig_count}, opt={opt_count}")


def test_instruction_reduction_mixed():
    """Mixed optimization program should have fewer instructions."""
    src_path = os.path.join(PROGRAMS_DIR, "06_mixed_opts.mc")
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    orig_count = count_instructions(bytecode)
    opt_count = count_instructions(optimized)
    assert opt_count < orig_count, (
        f"Expected instruction reduction for mixed_opts: orig={orig_count}, opt={opt_count}")


def test_instruction_reduction_nested_loops():
    """Nested loop program should have fewer instructions (identity ops and constant folds)."""
    src_path = os.path.join(PROGRAMS_DIR, "11_nested_loops.mc")
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    orig_count = count_instructions(bytecode)
    opt_count = count_instructions(optimized)
    assert opt_count < orig_count, (
        f"Expected instruction reduction for nested_loops: orig={orig_count}, opt={opt_count}")


def test_instruction_reduction_global_funcs():
    """Global funcs program should have fewer instructions (constant folding)."""
    src_path = os.path.join(PROGRAMS_DIR, "12_global_funcs.mc")
    with open(src_path) as f:
        source = f.read()
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    orig_count = count_instructions(bytecode)
    opt_count = count_instructions(optimized)
    assert opt_count < orig_count, (
        f"Expected instruction reduction for global_funcs: orig={orig_count}, opt={opt_count}")


def test_total_benchmark_reduction():
    """Total instruction count across all programs must decrease by at least 15%."""
    total_orig = 0
    total_opt = 0
    for program in get_program_files():
        src_path = os.path.join(PROGRAMS_DIR, program)
        with open(src_path) as f:
            source = f.read()
        bytecode = compile_source(source)
        optimized = run_optimizer(bytecode)
        total_orig += count_instructions(bytecode)
        total_opt += count_instructions(optimized)
    reduction_pct = (total_orig - total_opt) / total_orig * 100
    assert reduction_pct >= 15.0, (
        f"Total instruction reduction {reduction_pct:.1f}% is below the 15% threshold "
        f"(orig={total_orig}, opt={total_opt})")


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

def test_empty_program():
    """An empty main body with HALT should not crash the optimizer."""
    bytecode = {"main": [["HALT"]], "functions": {}}
    optimized = run_optimizer(bytecode)
    assert run_bytecode_dict(optimized) == ""


def test_optimizer_preserves_function_params():
    """Optimizer must not alter function parameter lists."""
    source = "func add(a, b) {\n    return a + b;\n}\nprint add(1, 2);\n"
    bytecode = compile_source(source)
    optimized = run_optimizer(bytecode)
    assert optimized["functions"]["add"]["params"] == ["a", "b"]
    assert run_bytecode_dict(optimized) == "3\n"


def test_complex_control_flow_preserved():
    """Nested if/while with functions must produce correct output after optimization."""
    source = (
        "func abs_val(x) {\n"
        "    if (x < 0) {\n"
        "        return 0 - x;\n"
        "    }\n"
        "    return x;\n"
        "}\n"
        "\n"
        "i = -3;\n"
        "total = 0;\n"
        "while (i <= 3) {\n"
        "    total = total + abs_val(i);\n"
        "    i = i + 1;\n"
        "}\n"
        "print total;\n"
    )
    bytecode = compile_source(source)
    expected = run_bytecode_dict(bytecode)
    optimized = run_optimizer(bytecode)
    actual = run_bytecode_dict(optimized)
    assert actual == expected == "12\n"


def test_global_state_through_functions():
    """Optimizer must not break programs where functions modify global state."""
    source = (
        "func inc() {\n"
        "    counter = counter + 1;\n"
        "    return counter;\n"
        "}\n"
        "\n"
        "counter = 0;\n"
        "a = inc();\n"
        "b = inc();\n"
        "c = inc();\n"
        "print a;\n"
        "print b;\n"
        "print c;\n"
    )
    bytecode = compile_source(source)
    expected = run_bytecode_dict(bytecode)
    optimized = run_optimizer(bytecode)
    actual = run_bytecode_dict(optimized)
    assert actual == expected == "1\n2\n3\n"
