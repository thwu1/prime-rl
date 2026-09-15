"""Verification tests for the 4-bit ALU: correctness, analysis, optimized adder, and report."""


import sys
import os
import json
import pytest

sys.path.insert(0, '/app')
from hdl import Wire, Bus, simulate, bus_to_int, int_to_input_map, const
from design import build_alu

Wire.reset()
_opcode = Bus.input(3, "op")
_a = Bus.input(4, "a")
_b = Bus.input(4, "b")
_result = build_alu(_opcode, _a, _b)


def _run(op, av, bv):
    inp = {}
    inp.update(int_to_input_map(_opcode, op))
    inp.update(int_to_input_map(_a, av))
    inp.update(int_to_input_map(_b, bv))
    return bus_to_int(simulate(_result, inp))


def _exp(op, a, b):
    M = 0xF
    return [
        (a + b) & M,
        (a - b) & M,
        a & b,
        a | b,
        a ^ b,
        (~a) & M,
        (a << 1) & M,
        a >> 1,
    ][op]


_OP_NAMES = ['ADD', 'SUB', 'AND', 'OR', 'XOR', 'NOT', 'SHL', 'SHR']


# ── ALU correctness (exhaustive) ──────────────────────────────────────

@pytest.mark.parametrize("op", range(8), ids=_OP_NAMES)
def test_operation(op):
    bad = []
    for a in range(16):
        for b in range(16):
            g = _run(op, a, b)
            e = _exp(op, a, b)
            if g != e:
                bad.append(f"a={a} b={b} exp={e} got={g}")
    assert not bad, (
        f"{_OP_NAMES[op]}: {len(bad)} failures. First: {bad[0]}"
    )


# ── Analysis: count_gates ─────────────────────────────────────────────

def test_analysis_count_gates_single():
    """count_gates on a single AND gate returns 1."""
    from analysis import count_gates
    Wire.reset()
    x = Bus.input(2, "x")
    y = x[0] & x[1]
    assert count_gates(Bus([y])) == 1


def test_analysis_count_gates_chain():
    """count_gates on a 2-gate chain returns 2."""
    from analysis import count_gates
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    c = Wire(name="c_in")
    t = a & b
    out = t | c
    assert count_gates(Bus([out])) == 2


def test_analysis_count_gates_shared():
    """Shared intermediate wires are counted once."""
    from analysis import count_gates
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    t = a & b          # 1 gate
    out1 = t | a       # 1 gate
    out2 = t ^ b       # 1 gate
    assert count_gates(Bus([out1, out2])) == 3


# ── Analysis: critical_path ───────────────────────────────────────────

def test_analysis_critical_path_single():
    """Critical path of a single gate is 1."""
    from analysis import critical_path
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    out = a ^ b
    assert critical_path(Bus([out])) == 1


def test_analysis_critical_path_chain():
    """Critical path of a chain of 3 gates is 3."""
    from analysis import critical_path
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    c = Wire(name="c_in")
    d = Wire(name="d_in")
    t1 = a & b
    t2 = t1 | c
    t3 = t2 ^ d
    assert critical_path(Bus([t3])) == 3


def test_analysis_critical_path_diamond():
    """Critical path through a diamond DAG is 2, not 3."""
    from analysis import critical_path
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    t1 = a & b
    t2 = a | b
    out = t1 ^ t2
    assert critical_path(Bus([out])) == 2


def test_analysis_critical_path_const():
    """Constants have depth 0."""
    from analysis import critical_path
    Wire.reset()
    a = Wire(name="a_in")
    c = const(1)
    out = a & c
    assert critical_path(Bus([out])) == 1


# ── Analysis: max_fanout ──────────────────────────────────────────────

def test_analysis_max_fanout_single():
    """Each input to a single gate has fanout 1."""
    from analysis import max_fanout
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    out = a & b
    assert max_fanout(Bus([out])) == 1


def test_analysis_max_fanout_chain():
    """In a simple chain, every wire has fanout 1."""
    from analysis import max_fanout
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    c = Wire(name="c_in")
    t1 = a & b
    t2 = t1 | c
    assert max_fanout(Bus([t2])) == 1


def test_analysis_max_fanout_shared():
    """Wire feeding 3 gates has fanout 3."""
    from analysis import max_fanout
    Wire.reset()
    a = Wire(name="a_in")
    b = Wire(name="b_in")
    c = Wire(name="c_in")
    t1 = a & b    # a feeds gate 1
    t2 = a | c    # a feeds gate 2
    t3 = a ^ t1   # a feeds gate 3
    assert max_fanout(Bus([t2, t3])) == 3


# ── Fast adder correctness ──────────────────────────────────────────

def test_fast_adder_correctness():
    """Fast adder must produce correct sum and carry for all inputs."""
    from fast_alu import fast_adder
    Wire.reset()
    a = Bus.input(4, "a")
    b = Bus.input(4, "b")
    cin = Wire(name="cin")
    s, cout = fast_adder(a, b, cin)

    bad = []
    for av in range(16):
        for bv in range(16):
            for cv in range(2):
                inp = {}
                inp.update(int_to_input_map(a, av))
                inp.update(int_to_input_map(b, bv))
                inp[cin] = cv
                result = bus_to_int(simulate(s, inp))
                carry = simulate(Bus([cout]), inp)[0]
                total = av + bv + cv
                exp_sum = total & 0xF
                exp_carry = (total >> 4) & 1
                if result != exp_sum or carry != exp_carry:
                    bad.append(
                        f"a={av} b={bv} cin={cv}: "
                        f"exp={exp_sum},c={exp_carry} "
                        f"got={result},c={carry}"
                    )
    assert not bad, f"fast_adder: {len(bad)} failures. First: {bad[0]}"


def test_fast_alu_correctness():
    """Fast ALU must match reference for all operations and inputs."""
    from fast_alu import build_alu_fast
    Wire.reset()
    opcode = Bus.input(3, "op")
    a = Bus.input(4, "a")
    b = Bus.input(4, "b")
    result = build_alu_fast(opcode, a, b)

    bad = []
    for op in range(8):
        for av in range(16):
            for bv in range(16):
                inp = {}
                inp.update(int_to_input_map(opcode, op))
                inp.update(int_to_input_map(a, av))
                inp.update(int_to_input_map(b, bv))
                got = bus_to_int(simulate(result, inp))
                exp = _exp(op, av, bv)
                if got != exp:
                    bad.append(
                        f"op={op} a={av} b={bv}: exp={exp} got={got}"
                    )
    assert not bad, f"fast ALU: {len(bad)} failures. First: {bad[0]}"


# ── Fast vs ripple-carry comparison ──────────────────────────────────

def test_fast_adder_shorter_critical_path():
    """Fast adder must have strictly shorter critical path."""
    from analysis import critical_path
    from fast_alu import fast_adder
    from design import ripple_adder

    # Build ripple-carry adder
    Wire.reset()
    a1 = Bus.input(4, "rc_a")
    b1 = Bus.input(4, "rc_b")
    rc_sum, _ = ripple_adder(a1, b1, const(0))
    rc_depth = critical_path(rc_sum)

    # Build fast adder
    Wire.reset()
    a2 = Bus.input(4, "fa_a")
    b2 = Bus.input(4, "fa_b")
    fa_sum, _ = fast_adder(a2, b2, const(0))
    fa_depth = critical_path(fa_sum)

    assert fa_depth < rc_depth, (
        f"Fast adder critical path ({fa_depth}) must be less than "
        f"ripple-carry ({rc_depth})"
    )


# ── Report schema validation ─────────────────────────────────────────

def test_report_exists():
    assert os.path.exists('/app/report.json'), "/app/report.json not found"


def test_report_schema():
    with open('/app/report.json') as f:
        data = json.load(f)

    assert "bugs" in data, "report missing 'bugs' key"
    assert "analysis" in data, "report missing 'analysis' key"
    assert "evaluation" in data, "report missing 'evaluation' key"

    # Bugs validation
    assert isinstance(data["bugs"], list), "'bugs' must be a list"
    assert len(data["bugs"]) >= 4, (
        f"Expected at least 4 bugs documented, found {len(data['bugs'])}"
    )

    for i, bug in enumerate(data["bugs"]):
        assert "function" in bug, f"bug[{i}] missing 'function'"
        assert "location" in bug, f"bug[{i}] missing 'location'"
        assert "description" in bug, f"bug[{i}] missing 'description'"
        assert "fix" in bug, f"bug[{i}] missing 'fix'"

    # Analysis validation
    analysis = data["analysis"]
    assert "original" in analysis, "analysis missing 'original'"
    assert "optimized" in analysis, "analysis missing 'optimized'"
    for key in ["original", "optimized"]:
        sub = analysis[key]
        for field in ["gate_count", "critical_path_depth", "max_fanout"]:
            assert field in sub, (
                f"analysis.{key} missing '{field}'"
            )
            assert isinstance(sub[field], int), (
                f"analysis.{key}.{field} must be int"
            )
            assert sub[field] > 0, (
                f"analysis.{key}.{field} must be positive"
            )

    # Evaluation validation
    assert isinstance(data["evaluation"], str), "'evaluation' must be a string"
    assert len(data["evaluation"]) >= 80, (
        f"'evaluation' too short ({len(data['evaluation'])} chars, need >=80)"
    )


def test_report_analysis_values():
    """Optimized design must have lower critical path than original."""
    with open('/app/report.json') as f:
        data = json.load(f)
    orig = data["analysis"]["original"]
    opt = data["analysis"]["optimized"]
    assert opt["critical_path_depth"] < orig["critical_path_depth"], (
        f"Optimized critical path ({opt['critical_path_depth']}) must be "
        f"less than original ({orig['critical_path_depth']})"
    )
