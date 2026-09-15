#!/usr/bin/env python3
"""
Complete CEGIS-based program synthesizer for the 16-bit bitvector DSL.

Reference solution.  Encodes synthesis as Z3 satisfiability with Int selectors
for operations/operands (shared across examples) and BitVec(16) data-flow
variables (per example).  A CEGIS loop iteratively refines candidates with
counterexamples from oracle queries.
"""
import sys
import os
import json
import random

sys.path.insert(0, '/app')

from z3 import (
    BitVec, BitVecVal, Int, If, And, LShR, Solver, sat,
)
from dsl import (
    OPS, NUM_OPS, NUM_INPUTS, MASK, BITS,
    evaluate_program, validate_program, program_to_string,
)
from oracle import get_oracle, ORACLES

# -----------------------------------------------------------------------
# Z3 helpers
# -----------------------------------------------------------------------

def _select_reg(selector, regs):
    """Build an ITE chain that returns regs[selector]."""
    expr = regs[-1]
    for k in range(len(regs) - 2, -1, -1):
        expr = If(selector == k, regs[k], expr)
    return expr


_SHIFT_MASK = None


def _apply_op(op_sel, x, y):
    """Build an ITE chain that applies operation op_sel to (x, y)."""
    global _SHIFT_MASK
    if _SHIFT_MASK is None:
        _SHIFT_MASK = BitVecVal(0xf, BITS)
    m = _SHIFT_MASK

    #  9: not   ~x
    expr = ~x
    #  8: neg   -x
    expr = If(op_sel == 8, -x, expr)
    #  7: shr   LShR(x, y & 0xf)
    expr = If(op_sel == 7, LShR(x, y & m), expr)
    #  6: shl   x << (y & 0xf)
    expr = If(op_sel == 6, x << (y & m), expr)
    #  5: xor
    expr = If(op_sel == 5, x ^ y, expr)
    #  4: or
    expr = If(op_sel == 4, x | y, expr)
    #  3: and
    expr = If(op_sel == 3, x & y, expr)
    #  2: mul
    expr = If(op_sel == 2, x * y, expr)
    #  1: sub
    expr = If(op_sel == 1, x - y, expr)
    #  0: add
    expr = If(op_sel == 0, x + y, expr)
    return expr


# -----------------------------------------------------------------------
# Constraint encoding
# -----------------------------------------------------------------------

def _add_io(solver, ops, a1s, a2s, inputs, expected, num_lines, eid):
    """Encode one I/O example as Z3 constraints."""
    regs = [BitVecVal(inputs[k], BITS) for k in range(NUM_INPUTS)]

    for i in range(num_lines):
        arg1_val = _select_reg(a1s[i], regs)
        arg2_val = _select_reg(a2s[i], regs)
        result   = _apply_op(ops[i], arg1_val, arg2_val)

        reg = BitVec(f'r{NUM_INPUTS + i}_e{eid}', BITS)
        solver.add(reg == result)
        regs.append(reg)

    solver.add(regs[-1] == BitVecVal(expected, BITS))


def _extract(model, ops, a1s, a2s, num_lines):
    """Read the synthesised program from a Z3 model."""
    prog = []
    for i in range(num_lines):
        prog.append({
            "op":   model.eval(ops[i],  model_completion=True).as_long(),
            "arg1": model.eval(a1s[i],  model_completion=True).as_long(),
            "arg2": model.eval(a2s[i],  model_completion=True).as_long(),
        })
    return prog


# -----------------------------------------------------------------------
# Verification
# -----------------------------------------------------------------------

def _find_counterexample(prog, oracle_fn, rng, n=50000):
    """Test *prog* against *oracle_fn* on random inputs.

    Returns (inputs, expected_output) on mismatch, else None.
    """
    for _ in range(n):
        inp = tuple(rng.randint(0, MASK) for _ in range(NUM_INPUTS))
        exp = oracle_fn(*inp)
        if evaluate_program(prog, inp) != exp:
            return inp, exp
    return None


# -----------------------------------------------------------------------
# CEGIS for a fixed program length
# -----------------------------------------------------------------------

def _cegis(oracle_fn, examples, num_lines, rng, max_rounds=50):
    """Try to synthesise a program of exactly *num_lines* instructions."""
    s = Solver()
    s.set("timeout", 120000)  # 120 s per check()

    # --- structural variables (define the program) ---
    ops = [Int(f'op_{i}')  for i in range(num_lines)]
    a1s = [Int(f'a1_{i}')  for i in range(num_lines)]
    a2s = [Int(f'a2_{i}')  for i in range(num_lines)]

    for i in range(num_lines):
        s.add(ops[i] >= 0, ops[i] < NUM_OPS)
        s.add(a1s[i] >= 0, a1s[i] < NUM_INPUTS + i)
        s.add(a2s[i] >= 0, a2s[i] < NUM_INPUTS + i)

        # Symmetry breaking: unary ops (neg=8, not=9) ignore arg2; fix to 0
        s.add(If(ops[i] >= 8, a2s[i] == 0, True))

        # Symmetry breaking: commutative ops use canonical arg order
        # add=0, mul=2, and=3, or=4, xor=5
        for comm_op in [0, 2, 3, 4, 5]:
            s.add(If(ops[i] == comm_op, a1s[i] <= a2s[i], True))

    # --- seed with initial examples ---
    ex = list(examples)
    for idx, (inp, out) in enumerate(ex):
        _add_io(s, ops, a1s, a2s, inp, out, num_lines, idx)

    # --- CEGIS loop ---
    for _ in range(max_rounds):
        if s.check() != sat:
            return None                    # UNSAT -> no program of this size

        prog = _extract(s.model(), ops, a1s, a2s, num_lines)
        ce = _find_counterexample(prog, oracle_fn, rng)
        if ce is None:
            return prog                    # verified!

        inp, out = ce
        idx = len(ex)
        ex.append((inp, out))
        _add_io(s, ops, a1s, a2s, inp, out, num_lines, idx)

    return None                            # rounds exhausted


# -----------------------------------------------------------------------
# Top-level entry point
# -----------------------------------------------------------------------

def synthesize(oracle_fn, max_lines=5):
    """Synthesise a DSL program equivalent to *oracle_fn*."""
    rng = random.Random(12345)

    # --- build initial I/O examples ---
    examples = []
    corners = [
        (0, 0, 0, 0),
        (MASK, MASK, MASK, MASK),
        (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1),
        (MASK, 0, 0, 0), (0, MASK, 0, 0), (0, 0, MASK, 0), (0, 0, 0, MASK),
        (1, 1, 1, 1),
        (0x00AA, 0x0055, 0x00F0, 0x000F),
        (0x1234, 0x5678, 0x9ABC, 0xDEF0),
    ]
    for inp in corners:
        examples.append((inp, oracle_fn(*inp)))
    for _ in range(7):
        inp = tuple(rng.randint(0, MASK) for _ in range(NUM_INPUTS))
        examples.append((inp, oracle_fn(*inp)))

    # --- iterative deepening over program length ---
    for num_lines in range(1, max_lines + 1):
        prog = _cegis(oracle_fn, examples, num_lines, rng)
        if prog is not None:
            return prog

    return None


# -----------------------------------------------------------------------
# CLI driver (same interface as the stub)
# -----------------------------------------------------------------------

def main():
    os.makedirs('/app/results', exist_ok=True)

    if len(sys.argv) < 2:
        print("Usage: python3 synthesize.py <oracle_id|all>")
        sys.exit(1)

    if sys.argv[1] == 'all':
        ids = sorted(ORACLES.keys())
    else:
        ids = [int(sys.argv[1])]

    for oid in ids:
        print(f"\n{'=' * 50}")
        print(f"Synthesizing oracle {oid} ...")
        print(f"{'=' * 50}")
        fn   = get_oracle(oid)
        prog = synthesize(fn)
        if prog is None:
            print(f"FAILED: oracle {oid}")
            sys.exit(1)
        if not validate_program(prog):
            print(f"ERROR: invalid program for oracle {oid}")
            sys.exit(1)
        print("Success:")
        print(program_to_string(prog))
        with open(f'/app/results/oracle_{oid}.json', 'w') as f:
            json.dump(prog, f, indent=2)


if __name__ == '__main__':
    main()
