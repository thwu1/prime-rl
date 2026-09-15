#!/usr/bin/env python3
"""
Concolic testing engine for WHILE3ADDR programs.


Combines concrete execution with symbolic constraint tracking (via Z3) to
systematically explore execution paths and discover inputs that trigger
assertion failures.
"""

import sys
import os

sys.path.insert(0, '/app')
from interpreter import (
    parse, execute, Program,
    ConstAssign, InputAssign, CopyAssign, BinOpAssign,
    CondGoto, Goto, Assert, Halt,
    OPS, RELOPS
)

from z3 import Int, IntVal, Not, Solver, sat


def count_inputs(program):
    """Count the number of input() instructions in a program."""
    return sum(1 for inst in program.instructions if isinstance(inst, InputAssign))


def _z3_binop(op, a, b):
    """Apply a binary operation symbolically. Returns None if unsupported."""
    if op == '+':
        return a + b
    elif op == '-':
        return a - b
    elif op == '*':
        return a * b
    elif op == '/':
        from z3 import If
        return If(b != 0, a / b, IntVal(0))
    elif op == '%':
        from z3 import If
        return If(b != 0, a % b, IntVal(0))
    return None


def _z3_relop(relop, a, b):
    """Create a Z3 boolean expression from a relational operator."""
    if relop == '==':
        return a == b
    elif relop == '!=':
        return a != b
    elif relop == '<':
        return a < b
    elif relop == '>':
        return a > b
    elif relop == '<=':
        return a <= b
    elif relop == '>=':
        return a >= b
    raise ValueError(f"Unknown relop: {relop}")


def _concolic_run(program, concrete_inputs, sym_inputs, max_steps=200000):
    """Execute a program with dual concrete/symbolic tracking.

    Returns:
        (assertion_failed, path_conditions)
        path_conditions: list of (z3_bool_expr, was_taken_concretely)
    """
    c_env = {}
    s_env = {}
    path_conds = []
    input_idx = 0
    pc = 0
    steps = 0

    while pc < len(program.instructions) and steps < max_steps:
        inst = program.instructions[pc]
        steps += 1

        if isinstance(inst, Halt):
            break

        elif isinstance(inst, ConstAssign):
            c_env[inst.var] = inst.value
            s_env[inst.var] = IntVal(inst.value)
            pc += 1

        elif isinstance(inst, InputAssign):
            if input_idx >= len(concrete_inputs):
                break
            c_env[inst.var] = concrete_inputs[input_idx]
            s_env[inst.var] = sym_inputs[input_idx]
            input_idx += 1
            pc += 1

        elif isinstance(inst, CopyAssign):
            c_env[inst.dst] = c_env[inst.src]
            s_env[inst.dst] = s_env[inst.src]
            pc += 1

        elif isinstance(inst, BinOpAssign):
            cl = c_env[inst.left]
            cr = c_env[inst.right]
            sl = s_env[inst.left]
            sr = s_env[inst.right]

            c_result = OPS[inst.op](cl, cr)
            c_env[inst.dst] = c_result

            s_result = _z3_binop(inst.op, sl, sr)
            if s_result is not None:
                s_env[inst.dst] = s_result
            else:
                # Concolic fallback: use concrete value for unsupported ops
                s_env[inst.dst] = IntVal(c_result)
            pc += 1

        elif isinstance(inst, CondGoto):
            cl = c_env[inst.left]
            cr = c_env[inst.right]
            sl = s_env[inst.left]
            sr = s_env[inst.right]

            taken = RELOPS[inst.relop](cl, cr)
            sym_cond = _z3_relop(inst.relop, sl, sr)
            path_conds.append((sym_cond, taken))

            if taken:
                pc = program.labels[inst.label]
            else:
                pc += 1

        elif isinstance(inst, Goto):
            pc = program.labels[inst.label]

        elif isinstance(inst, Assert):
            cl = c_env[inst.left]
            cr = c_env[inst.right]
            if not RELOPS[inst.relop](cl, cr):
                return True, path_conds
            pc += 1

    return False, path_conds


def find_bug(program_path, max_iterations=2000, max_steps=200000):
    """Find inputs that trigger an assertion failure in the given program.

    Args:
        program_path: path to a .prog file
        max_iterations: maximum concolic exploration iterations
        max_steps: maximum execution steps per run

    Returns:
        A list of integers (the triggering inputs) or None if not found.
    """
    with open(program_path, 'r') as f:
        source = f.read()
    program = parse(source)

    num_inputs = count_inputs(program)
    if num_inputs == 0:
        _, failed, _ = execute(program, [])
        return [] if failed else None

    sym_inputs = [Int(f'inp_{i}') for i in range(num_inputs)]
    concrete_inputs = [0] * num_inputs

    explored = set()

    for _ in range(max_iterations):
        found, path_conds = _concolic_run(
            program, concrete_inputs, sym_inputs, max_steps
        )

        if found:
            return list(concrete_inputs)

        if not path_conds:
            break

        # DFS: try negating conditions from deepest to shallowest
        new_inputs = None
        for i in range(len(path_conds) - 1, -1, -1):
            prefix_key = tuple(t for _, t in path_conds[:i])
            neg_dir = not path_conds[i][1]
            expl_key = (prefix_key, i, neg_dir)

            if expl_key in explored:
                continue
            explored.add(expl_key)

            solver = Solver()
            solver.set("timeout", 10000)

            # Prefix: maintain same direction as concrete run
            for j in range(i):
                cond, taken = path_conds[j]
                solver.add(cond if taken else Not(cond))

            # Negate condition i
            cond, taken = path_conds[i]
            solver.add(Not(cond) if taken else cond)

            if solver.check() == sat:
                model = solver.model()
                new_inputs = []
                for sv in sym_inputs:
                    val = model.eval(sv, model_completion=True)
                    try:
                        new_inputs.append(int(val.as_long()))
                    except (AttributeError, ValueError):
                        new_inputs.append(0)
                break

        if new_inputs is None:
            break

        concrete_inputs = new_inputs

    return None


if __name__ == '__main__':
    import glob

    programs_dir = '/app/programs'
    prog_files = sorted(glob.glob(os.path.join(programs_dir, '*.prog')))

    all_ok = True
    for prog_path in prog_files:
        name = os.path.splitext(os.path.basename(prog_path))[0]
        print(f"Analyzing {name}...")

        result = find_bug(prog_path)
        if result is not None:
            print(f"  BUG FOUND with inputs: {result}")
            with open(prog_path, 'r') as f:
                prog = parse(f.read())
            _, failed, _ = execute(prog, result)
            verified = "VERIFIED" if failed else "VERIFICATION FAILED"
            print(f"  {verified}")
            if not failed:
                all_ok = False
        else:
            print(f"  No bug found")
            all_ok = False

    sys.exit(0 if all_ok else 1)
