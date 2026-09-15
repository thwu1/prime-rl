"""
Tests for the verified DAG optimizer.

Verifies:
1. Optimizer preserves semantic equivalence for all 8 programs
2. Computational node counts meet targets
3. Z3 verification report classifies candidate rules correctly
4. Counterexamples for unsound rules are valid
5. Range analysis generalizes to novel DAGs (anti-cheat)
6. Algebraic factoring generalizes to novel DAGs (anti-cheat)
7. Power-of-2 strength reduction works on novel constants (anti-cheat)

"""
import sys
import os
import json

sys.path.insert(0, "/app")

import pytest
from dag_ir import DAG, Op
from programs import PROGRAMS

from optimizer import optimize

MASK32 = 0xFFFFFFFF

# Test inputs for 1-arg programs
INPUTS_1 = [
    [0], [1], [2], [42], [255], [256], [12345],
    [0x7FFFFFFF], [0x80000000], [0xDEADBEEF], [0xFFFFFFFF],
    [0xCAFEBABE], [0x12345678], [100], [999999],
]

# Test inputs for 2-arg programs
INPUTS_2 = [
    [0, 0], [1, 2], [0, 1], [1, 0], [42, 137],
    [255, 256], [0xDEAD, 0xBEEF], [0xDEADBEEF, 0xCAFEBABE],
    [0xFFFFFFFF, 0], [0, 0xFFFFFFFF], [0xFFFFFFFF, 0xFFFFFFFF],
    [0x80000000, 0x80000000], [12345, 67890], [1, 1], [7, 3],
]

TWO_ARG_PROGRAMS = {
    "cancel_annihilate", "cond_collapse", "multi_pass_compose",
    "verified_rewrites", "range_fold", "algebraic_factor",
}


def _get_inputs(name: str):
    return INPUTS_2 if name in TWO_ARG_PROGRAMS else INPUTS_1


def _run_program_test(name: str):
    builder = PROGRAMS[name]
    dag, target = builder()

    inputs = _get_inputs(name)
    ref_outputs = [dag.evaluate(args) for args in inputs]

    opt_dag = optimize(dag)

    for args, ref in zip(inputs, ref_outputs):
        actual = opt_dag.evaluate(args)
        assert actual == ref, (
            f"Program '{name}': output mismatch for input {[hex(a) for a in args]}. "
            f"Expected {[hex(r) for r in ref]}, got {[hex(a) for a in actual]}"
        )

    comp = opt_dag.computational_node_count()
    assert comp <= target, (
        f"Program '{name}': computational nodes = {comp}, target <= {target}"
    )


# ===== optimizer correctness tests =====

def test_identity_cleanup():
    _run_program_test("identity_cleanup")

def test_const_propagation():
    _run_program_test("const_propagation")

def test_cancel_annihilate():
    _run_program_test("cancel_annihilate")

def test_cond_collapse():
    _run_program_test("cond_collapse")

def test_range_fold():
    _run_program_test("range_fold")

def test_algebraic_factor():
    _run_program_test("algebraic_factor")

def test_multi_pass_compose():
    _run_program_test("multi_pass_compose")

def test_verified_rewrites():
    _run_program_test("verified_rewrites")


# ===== meta-tests: basic sanity =====

def test_optimizer_trivial():
    """Optimizer handles a DAG that is already minimal."""
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)
    r = d.add(x, y)
    d.set_outputs([r])
    opt = optimize(d)
    assert opt.evaluate([3, 4]) == [7]
    assert opt.computational_node_count() <= 1

def test_optimizer_single_const():
    """Optimizer handles a pure-constant DAG."""
    d = DAG()
    c = d.const(42)
    d.set_outputs([c])
    opt = optimize(d)
    assert opt.evaluate([]) == [42]
    assert opt.computational_node_count() == 0


# ===== anti-cheat: range analysis must generalize =====

def test_optimizer_range_novel_4bit():
    """Range analysis must fold comparisons on novel 4-bit-masked DAGs."""
    d = DAG()
    x = d.arg(0)
    c_mask = d.const(0xF)
    x_lo = d.and_(x, c_mask)           # range: [0, 15]
    c16 = d.const(16)
    cond = d.cmplt(x_lo, c16)          # provably true: 15 < 16
    c42 = d.const(42)
    result = d.where(cond, x_lo, c42)  # → x_lo
    d.set_outputs([result])
    opt = optimize(d)
    assert opt.computational_node_count() <= 1, \
        f"Range-folded DAG should have ≤1 comp node, got {opt.computational_node_count()}"
    for v in [0, 1, 15, 255, 0xFFFFFFFF]:
        assert opt.evaluate([v]) == [v & 0xF]

def test_optimizer_range_novel_sum():
    """Range analysis must handle ADD of two masked values."""
    d = DAG()
    x = d.arg(0)
    y = d.arg(1)
    c_mask = d.const(0x7F)              # 7-bit mask
    a = d.and_(x, c_mask)               # [0, 127]
    b = d.and_(y, c_mask)               # [0, 127]
    s = d.add(a, b)                     # [0, 254]
    c256 = d.const(256)
    cond = d.cmplt(s, c256)             # provably true: 254 < 256
    fallback = d.xor(x, y)
    result = d.where(cond, s, fallback)
    d.set_outputs([result])
    opt = optimize(d)
    assert opt.computational_node_count() <= 3, \
        f"Range-folded sum DAG should have ≤3 comp nodes, got {opt.computational_node_count()}"
    for xv, yv in [(0, 0), (127, 127), (0xFF, 0xFF), (1, 2)]:
        assert opt.evaluate([xv, yv]) == [((xv & 0x7F) + (yv & 0x7F)) & MASK32]


# ===== anti-cheat: algebraic factoring must generalize =====

def test_optimizer_factor_novel():
    """Algebraic factoring must handle novel constant pairs."""
    d = DAG()
    x = d.arg(0)
    c2 = d.const(2)
    c6 = d.const(6)
    a = d.mul(x, c2)                    # x * 2
    b = d.mul(x, c6)                    # x * 6
    s = d.add(a, b)                     # → MUL(x, 8) → SHL(x, 3)
    d.set_outputs([s])
    opt = optimize(d)
    assert opt.computational_node_count() <= 1, \
        f"Factored DAG should have ≤1 comp node, got {opt.computational_node_count()}"
    for v in [0, 1, 3, 42, 255, 0xFFFFFFFF]:
        assert opt.evaluate([v]) == [(v * 8) & MASK32]

def test_optimizer_power_of_two():
    """MUL by power of 2 should reduce to SHL."""
    d = DAG()
    x = d.arg(0)
    c16 = d.const(16)
    r = d.mul(x, c16)
    d.set_outputs([r])
    opt = optimize(d)
    assert opt.computational_node_count() <= 1, \
        f"Power-of-2 MUL should reduce to 1 comp node, got {opt.computational_node_count()}"
    for v in [0, 1, 42, 0x0FFFFFFF, 0xFFFFFFFF]:
        assert opt.evaluate([v]) == [(v * 16) & MASK32]


# ===== verification report tests =====

def test_verification_report_exists():
    """Verification report JSON file must exist."""
    assert os.path.isfile("/app/verification_report.json"), \
        "Missing /app/verification_report.json"

def test_verification_report_structure():
    """Report must have entries for all six candidate rules."""
    with open("/app/verification_report.json") as f:
        report = json.load(f)
    expected = {"C1", "C2", "C3", "C4", "C5", "C6"}
    assert set(report.keys()) == expected, \
        f"Expected keys {expected}, got {set(report.keys())}"
    for rid in expected:
        assert "verdict" in report[rid], f"Rule {rid} missing 'verdict'"
        assert report[rid]["verdict"] in ("sound", "unsound"), \
            f"Rule {rid}: invalid verdict '{report[rid]['verdict']}'"
        if report[rid]["verdict"] == "unsound":
            assert "counterexample" in report[rid], \
                f"Rule {rid} unsound but missing 'counterexample'"

def test_verification_verdicts():
    """Sound/unsound classification must be correct for all rules."""
    with open("/app/verification_report.json") as f:
        report = json.load(f)
    # Sound rules
    assert report["C1"]["verdict"] == "sound", \
        "C1 (bit partition) is sound — OR(AND(x,c),AND(x,~c))=x for all x,c"
    assert report["C4"]["verdict"] == "sound", \
        "C4 (sub inverse) is sound — x-(x-y)=y in modular arithmetic"
    assert report["C5"]["verdict"] == "sound", \
        "C5 (additive inverse) is sound — x+NEG(x)=0 in modular arithmetic"
    # Unsound rules
    assert report["C2"]["verdict"] == "unsound", \
        "C2 (shift roundtrip) is unsound — high bits lost by left shift"
    assert report["C3"]["verdict"] == "unsound", \
        "C3 (increment compare) is unsound — overflows at 0xFFFFFFFF"
    assert report["C6"]["verdict"] == "unsound", \
        "C6 (sub decreases) is unsound — unsigned underflow wraps around"

def test_counterexample_c2():
    """C2 counterexample must demonstrate SHR(SHL(x, c), c) != x."""
    with open("/app/verification_report.json") as f:
        report = json.load(f)
    ce = report["C2"]["counterexample"]
    x = ce["x"] & MASK32
    c = ce["c"]
    assert 1 <= c <= 31, f"C2: c must be in [1,31], got {c}"
    shl_result = (x << (c & 0x1F)) & MASK32
    shr_result = shl_result >> (c & 0x1F)
    assert shr_result != x, \
        f"C2 counterexample invalid: SHR(SHL({x:#x},{c}),{c})={shr_result:#x} == {x:#x}"

def test_counterexample_c3():
    """C3 counterexample must demonstrate CMPLT(x, ADD(x, 1)) != 1."""
    with open("/app/verification_report.json") as f:
        report = json.load(f)
    ce = report["C3"]["counterexample"]
    x = ce["x"] & MASK32
    added = (x + 1) & MASK32
    cmp_result = 1 if x < added else 0
    assert cmp_result != 1, \
        f"C3 counterexample invalid: CMPLT({x:#x},{added:#x})=1"

def test_counterexample_c6():
    """C6 counterexample must demonstrate CMPLT(SUB(x, y), x) != 1."""
    with open("/app/verification_report.json") as f:
        report = json.load(f)
    ce = report["C6"]["counterexample"]
    x = ce["x"] & MASK32
    y = ce["y"] & MASK32
    sub_result = (x - y) & MASK32
    cmp_result = 1 if sub_result < x else 0
    assert cmp_result != 1, \
        f"C6 counterexample invalid: CMPLT(SUB({x:#x},{y:#x}),{x:#x})=1"
