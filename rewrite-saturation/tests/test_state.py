
import subprocess
import random
import os
import pytest


# ===================== S-Expression Parser =====================

def tokenize(s):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c == '(':
            tokens.append('(')
            i += 1
        elif c == ')':
            tokens.append(')')
            i += 1
        else:
            j = i
            while j < len(s) and not s[j].isspace() and s[j] not in '()':
                j += 1
            tok = s[i:j]
            i = j
            try:
                tokens.append(int(tok))
            except ValueError:
                tokens.append(tok)
    return tokens


def parse_sexp(s):
    tokens = tokenize(s)
    result, _ = _parse_at(tokens, 0)
    return result


def _parse_at(tokens, pos):
    if tokens[pos] == '(':
        pos += 1
        items = []
        while tokens[pos] != ')':
            item, pos = _parse_at(tokens, pos)
            items.append(item)
        return items, pos + 1
    else:
        return tokens[pos], pos + 1


# ===================== Evaluator =====================

def evaluate(sexp, env):
    """Evaluate an S-expression with the given variable bindings."""
    if isinstance(sexp, int):
        return sexp
    if isinstance(sexp, str):
        return env[sexp]
    op = sexp[0]
    if op == 'neg':
        return -evaluate(sexp[1], env)
    left = evaluate(sexp[1], env)
    right = evaluate(sexp[2], env)
    if op == '+':
        return left + right
    if op == '-':
        return left - right
    if op == '*':
        return left * right
    if op == '/':
        return left // right if right != 0 else 0
    if op == '<<':
        return left << right
    if op == '>>':
        return left >> right
    raise ValueError(f"Unknown op: {op}")


# ===================== Cost Calculator =====================

COST_MODEL = {'+': 1, '-': 1, '*': 3, '/': 5, '<<': 1, '>>': 1, 'neg': 1}


def compute_cost(sexp):
    """Compute the total cost of an expression."""
    if isinstance(sexp, (int, str)):
        return 0
    op = sexp[0]
    cost = COST_MODEL.get(op, 1)
    return cost + sum(compute_cost(c) for c in sexp[1:])


# ===================== Test Definitions =====================

# (filename, original_expr, max_cost, variable_names)
BENCHMARKS = [
    ("expr01.sexp", "(+ x 0)", 0, ["x"]),
    ("expr02.sexp", "(* y 2)", 1, ["y"]),
    ("expr03.sexp", "(+ (* a b) (* a c))", 4, ["a", "b", "c"]),
    ("expr04.sexp", "(neg (neg (+ a b)))", 1, ["a", "b"]),
    ("expr05.sexp", "(+ (+ (* x 0) y) 0)", 0, ["x", "y"]),
    ("expr06.sexp", "(* (+ a b) 4)", 2, ["a", "b"]),
    ("expr07.sexp", "(+ (* a 8) (* a 8))", 1, ["a"]),
    ("expr08.sexp", "(+ (* 2 x) (* 2 y))", 2, ["x", "y"]),
    ("expr09.sexp", "(+ (* (+ a b) 2) (* (+ a b) 2))", 2, ["a", "b"]),
    ("expr10.sexp", "(+ (* x 3) (* x 5))", 1, ["x"]),
]


def run_optimizer(expr_file):
    """Run the optimizer and return stdout."""
    result = subprocess.run(
        ["python3", "/app/optimize.py", expr_file],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Optimizer exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    output = result.stdout.strip()
    assert output, "Optimizer produced empty output"
    return output


# ===================== Expression Correctness Tests =====================

@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_optimizer_correctness(filename, original_expr, max_cost, var_names):
    """Check that the optimized expression is semantically equivalent."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    assert os.path.exists(expr_file), f"Benchmark file missing: {expr_file}"

    output = run_optimizer(expr_file)
    out_sexp = parse_sexp(output)
    in_sexp = parse_sexp(original_expr)

    rng = random.Random(42)
    for _ in range(50):
        env = {v: rng.randint(1, 100) for v in var_names}
        expected = evaluate(in_sexp, env)
        actual = evaluate(out_sexp, env)
        assert expected == actual, (
            f"Semantic mismatch for {filename} with env={env}: "
            f"expected {expected}, got {actual}.\n"
            f"Original: {original_expr}\nOptimized: {output}"
        )


@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_optimizer_cost(filename, original_expr, max_cost, var_names):
    """Check that the optimized expression meets the cost bound."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    output = run_optimizer(expr_file)
    out_sexp = parse_sexp(output)
    actual_cost = compute_cost(out_sexp)
    assert actual_cost <= max_cost, (
        f"Cost for {filename}: {actual_cost} exceeds target {max_cost}.\n"
        f"Original: {original_expr}\nOptimized: {output}"
    )


# ===================== LLVM IR Verification Tests =====================

@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_llvm_ir_valid(filename, original_expr, max_cost, var_names):
    """Verify the generated LLVM IR passes LLVM's structural verifier."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    run_optimizer(expr_file)
    basename = filename.replace('.sexp', '')
    ll_file = f"/app/output/{basename}.ll"
    assert os.path.exists(ll_file), (
        f"LLVM IR file not generated at {ll_file}. "
        f"The optimizer must write LLVM IR for each benchmark."
    )
    result = subprocess.run(
        ["opt", "-passes=verify", "-disable-output", ll_file],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"LLVM IR verification failed for {filename}.\n"
        f"opt stderr: {result.stderr}"
    )


@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_llvm_ir_has_function(filename, original_expr, max_cost, var_names):
    """Verify the LLVM IR defines the @optimized function with correct signature."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    run_optimizer(expr_file)
    basename = filename.replace('.sexp', '')
    ll_file = f"/app/output/{basename}.ll"
    assert os.path.exists(ll_file), f"LLVM IR file not found: {ll_file}"
    with open(ll_file) as f:
        ir_text = f.read()
    assert "define i64 @optimized(" in ir_text, (
        f"LLVM IR for {filename} must define 'i64 @optimized(...)' function.\n"
        f"Got:\n{ir_text[:500]}"
    )
    expected_params = len(var_names)
    # Count i64 parameters in the function signature
    import re
    m = re.search(r'define i64 @optimized\(([^)]*)\)', ir_text)
    assert m, f"Could not parse @optimized signature in {ll_file}"
    param_str = m.group(1).strip()
    if param_str:
        actual_params = len([p for p in param_str.split(',') if 'i64' in p])
    else:
        actual_params = 0
    assert actual_params == expected_params, (
        f"@optimized in {filename} has {actual_params} params, expected {expected_params} "
        f"(one per variable: {var_names})"
    )


# ===================== Z3 SMT Proof Tests =====================

@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_smt2_proof_valid(filename, original_expr, max_cost, var_names):
    """Verify the Z3 equivalence proof returns unsat."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    run_optimizer(expr_file)
    basename = filename.replace('.sexp', '')
    smt2_file = f"/app/output/{basename}.smt2"
    assert os.path.exists(smt2_file), (
        f"SMT-LIB2 proof file not generated at {smt2_file}. "
        f"The optimizer must write an equivalence proof for each benchmark."
    )
    result = subprocess.run(
        ["z3", smt2_file],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Z3 returned error for {filename}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    z3_output = result.stdout.strip()
    assert z3_output == "unsat", (
        f"Z3 equivalence proof failed for {filename}: "
        f"expected 'unsat', got '{z3_output}'.\n"
        f"The SMT-LIB2 script must prove that the original and "
        f"optimized expressions are equivalent over 64-bit bitvectors."
    )


@pytest.mark.parametrize(
    "filename,original_expr,max_cost,var_names",
    BENCHMARKS,
    ids=[b[0] for b in BENCHMARKS],
)
def test_smt2_uses_qf_bv(filename, original_expr, max_cost, var_names):
    """Verify the SMT-LIB2 script uses QF_BV logic and declares variables."""
    expr_file = f"/opt/eqsat/benchmarks/{filename}"
    run_optimizer(expr_file)
    basename = filename.replace('.sexp', '')
    smt2_file = f"/app/output/{basename}.smt2"
    assert os.path.exists(smt2_file), f"SMT2 file not found: {smt2_file}"
    with open(smt2_file) as f:
        smt2_text = f.read()
    assert "(set-logic QF_BV)" in smt2_text, (
        f"SMT2 for {filename} must use (set-logic QF_BV).\n"
        f"Got:\n{smt2_text[:500]}"
    )
    for v in var_names:
        assert f"(declare-const {v}" in smt2_text or f"(declare-fun {v}" in smt2_text, (
            f"SMT2 for {filename} must declare variable '{v}' as a 64-bit bitvector."
        )
    assert "(check-sat)" in smt2_text, (
        f"SMT2 for {filename} must contain (check-sat)."
    )


# ===================== Existence Test =====================

def test_optimizer_exists():
    """Check that the optimizer script exists."""
    assert os.path.exists("/app/optimize.py"), (
        "/app/optimize.py not found. Create the optimizer at /app/optimize.py."
    )
