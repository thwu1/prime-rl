#!/usr/bin/env python3

"""
Z3-based component program synthesizer using CEGIS (counterexample-guided
inductive synthesis). Encodes the synthesis search space as Z3 bitvector
constraints with iterative deepening on program length.
"""

import json
import sys
from z3 import (
    Solver, BitVecVal, Int, If, And, Or, LShR, sat
)

OPERATORS = ['add', 'sub', 'mul', 'band', 'bor', 'bxor', 'shl', 'lshr']
NUM_OPS = len(OPERATORS)
CONST_NAMES = ['c0', 'c1', 'c65535']


def get_const_vals(bw):
    mask = (1 << bw) - 1
    return [0, 1, mask]


def eval_op_concrete(op, a, b, mask):
    """Evaluate a DSL operation on concrete unsigned values."""
    if op == 'add':
        return (a + b) & mask
    if op == 'sub':
        return (a - b) & mask
    if op == 'mul':
        return (a * b) & mask
    if op == 'band':
        return a & b
    if op == 'bor':
        return a | b
    if op == 'bxor':
        return a ^ b
    if op == 'shl':
        return (a << (b & 0xF)) & mask
    if op == 'lshr':
        return a >> (b & 0xF)
    raise ValueError(f"Unknown op: {op}")


def eval_program_concrete(program, result_var, inputs, bw):
    """Evaluate a synthesized program on concrete inputs."""
    mask = (1 << bw) - 1
    env = {}
    for i, v in enumerate(inputs):
        env[f'x{i}'] = v & mask
    env['c0'] = 0
    env['c1'] = 1
    env['c65535'] = mask
    for step in program:
        a = env[step['arg1']]
        b = env[step['arg2']]
        env[step['dest']] = eval_op_concrete(step['op'], a, b, mask)
    return env[result_var]


def z3_apply_op(op_idx, a, b, bw):
    """Encode operator application as Z3 If-Then-Else chain."""
    mask_val = BitVecVal(0xF, bw)
    result = LShR(a, b & mask_val)                           # 7: lshr
    result = If(op_idx == 6, (a << (b & mask_val)), result)   # 6: shl
    result = If(op_idx == 5, a ^ b, result)                   # 5: bxor
    result = If(op_idx == 4, a | b, result)                   # 4: bor
    result = If(op_idx == 3, a & b, result)                   # 3: band
    result = If(op_idx == 2, a * b, result)                   # 2: mul
    result = If(op_idx == 1, a - b, result)                   # 1: sub
    result = If(op_idx == 0, a + b, result)                   # 0: add
    return result


def z3_select(idx, values):
    """Select a value from a list based on an integer index variable."""
    if len(values) == 1:
        return values[0]
    result = values[-1]
    for i in range(len(values) - 2, -1, -1):
        result = If(idx == i, values[i], result)
    return result


def extract_program(model, op_vars, arg1_vars, arg2_vars, num_lines,
                    num_inputs):
    """Extract a concrete program from a Z3 model."""
    program = []
    for i in range(num_lines):
        op_idx = model.eval(op_vars[i], model_completion=True).as_long()
        a1_idx = model.eval(arg1_vars[i], model_completion=True).as_long()
        a2_idx = model.eval(arg2_vars[i], model_completion=True).as_long()
        all_names = (
            [f'x{j}' for j in range(num_inputs)]
            + CONST_NAMES
            + [f't{j}' for j in range(i)]
        )
        program.append({
            'op': OPERATORS[op_idx],
            'arg1': all_names[a1_idx],
            'arg2': all_names[a2_idx],
            'dest': f't{i}',
        })
    return program


def synthesize(num_inputs, max_ops, io_pairs, bw=16):
    """
    CEGIS-based program synthesis with iterative deepening.
    """
    mask = (1 << bw) - 1
    const_vals = get_const_vals(bw)
    num_consts = len(CONST_NAMES)

    for num_lines in range(1, max_ops + 1):
        print(f"Trying {num_lines} operation(s)...", file=sys.stderr)

        # CEGIS: start with a small subset of I/O pairs
        initial_count = min(3, len(io_pairs))
        active_set = set(range(initial_count))

        for cegis_iter in range(len(io_pairs) + 20):
            active_pairs = [io_pairs[i] for i in sorted(active_set)]

            solver = Solver()
            solver.set('timeout', 90000)  # 90s per Z3 invocation

            # Program structure variables
            op_vars = [Int(f'op_{i}') for i in range(num_lines)]
            arg1_vars = [Int(f'a1_{i}') for i in range(num_lines)]
            arg2_vars = [Int(f'a2_{i}') for i in range(num_lines)]

            # Domain constraints
            for i in range(num_lines):
                solver.add(And(op_vars[i] >= 0, op_vars[i] < NUM_OPS))
                num_avail = num_inputs + num_consts + i
                solver.add(And(arg1_vars[i] >= 0, arg1_vars[i] < num_avail))
                solver.add(And(arg2_vars[i] >= 0, arg2_vars[i] < num_avail))

            # Dead code elimination: every intermediate except the last
            # must be used by at least one later line
            for i in range(num_lines - 1):
                temp_idx = num_inputs + num_consts + i
                used_clauses = []
                for j in range(i + 1, num_lines):
                    used_clauses.append(arg1_vars[j] == temp_idx)
                    used_clauses.append(arg2_vars[j] == temp_idx)
                solver.add(Or(*used_clauses))

            # No constant-only operations
            for i in range(num_lines):
                const_start = num_inputs
                const_end = num_inputs + num_consts
                solver.add(Or(
                    arg1_vars[i] < const_start,
                    arg1_vars[i] >= const_end,
                    arg2_vars[i] < const_start,
                    arg2_vars[i] >= const_end,
                ))

            # I/O constraints for active pairs only
            for pair_idx, (inputs, output) in enumerate(active_pairs):
                input_bvs = [BitVecVal(v & mask, bw) for v in inputs]
                const_bvs = [BitVecVal(v, bw) for v in const_vals]
                temps = []
                for i in range(num_lines):
                    available = input_bvs + const_bvs + temps
                    a = z3_select(arg1_vars[i], available)
                    b = z3_select(arg2_vars[i], available)
                    t = z3_apply_op(op_vars[i], a, b, bw)
                    temps.append(t)
                solver.add(temps[-1] == BitVecVal(output & mask, bw))

            result = solver.check()
            if result != sat:
                print(
                    f"  {result} with {len(active_pairs)} pairs",
                    file=sys.stderr,
                )
                break  # Try next program length

            # Extract candidate program from model
            model = solver.model()
            program = extract_program(
                model, op_vars, arg1_vars, arg2_vars,
                num_lines, num_inputs,
            )
            result_var = f't{num_lines - 1}'

            # Verify candidate against ALL I/O pairs, collecting
            # ALL counterexamples at once
            new_counterexamples = []
            for idx in range(len(io_pairs)):
                if idx in active_set:
                    continue
                inp, out = io_pairs[idx]
                try:
                    actual = eval_program_concrete(
                        program, result_var, inp, bw,
                    )
                except (KeyError, ValueError):
                    new_counterexamples.append(idx)
                    continue
                if actual != (out & mask):
                    new_counterexamples.append(idx)

            if not new_counterexamples:
                print(
                    f"Found {num_lines}-op solution "
                    f"(verified on {len(io_pairs)} pairs)!",
                    file=sys.stderr,
                )
                return {'program': program, 'result': result_var}

            # Add all counterexamples
            active_set.update(new_counterexamples)
            print(
                f"  CEGIS iter {cegis_iter}: added {len(new_counterexamples)} "
                f"counterexamples (total active: {len(active_set)})",
                file=sys.stderr,
            )

    return None


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: synthesizer.py <spec.json> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(sys.argv[1]) as f:
        spec = json.load(f)

    solution = synthesize(
        num_inputs=spec['num_inputs'],
        max_ops=spec['max_ops'],
        io_pairs=spec['io_pairs'],
        bw=spec.get('bit_width', 16),
    )

    if solution is None:
        print("Synthesis failed: no solution found.", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[2], 'w') as f:
        json.dump(solution, f, indent=2)

    print(f"Solution written to {sys.argv[2]}", file=sys.stderr)


if __name__ == '__main__':
    main()
