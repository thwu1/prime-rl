#!/usr/bin/env python3
"""
Execution tracer for RTL programs.
Runs step-by-step and shows register states at each node.

Usage: python3 rtl_trace.py <program.json> [arg1 arg2 ...]

"""

import sys
from rtl import load_function, Inop, Iop, Icond, Ireturn, eval_op, eval_cond


def trace(func, args, max_steps=1000):
    regs = {}
    for param, val in zip(func.params, args):
        regs[param] = val

    pc = func.entry
    step = 0

    print(f"=== Tracing {func.name}({', '.join(str(a) for a in args)}) ===")
    if func.params:
        print(f"Params: {dict(zip(func.params, args))}")
    print()

    while step < max_steps:
        step += 1
        if pc not in func.code:
            print(f"ERROR: jumped to non-existent node {pc}")
            return None

        instr = func.code[pc]

        if isinstance(instr, Inop):
            print(f"  [{step:3d}] node {pc:3d}: nop -> {instr.succ}")
            pc = instr.succ

        elif isinstance(instr, Iop):
            if instr.op == "const":
                result = instr.imm
                print(f"  [{step:3d}] node {pc:3d}: {instr.dest} = const {instr.imm} -> {instr.succ}")
            else:
                arg_strs = []
                concrete = []
                for a in instr.args:
                    v = regs.get(a, "UNDEF")
                    arg_strs.append(f"{a}={v}")
                    concrete.append(regs[a])
                result = eval_op(instr.op, concrete)
                print(f"  [{step:3d}] node {pc:3d}: {instr.dest} = {instr.op}({', '.join(arg_strs)}) => {result} -> {instr.succ}")
            regs[instr.dest] = result
            pc = instr.succ

        elif isinstance(instr, Icond):
            concrete = [regs[a] for a in instr.args]
            arg_strs = [f"{a}={regs[a]}" for a in instr.args]
            taken = eval_cond(instr.cond, concrete)
            target = instr.ifso if taken else instr.ifnot
            print(f"  [{step:3d}] node {pc:3d}: {instr.cond}({', '.join(arg_strs)}) => {'TRUE' if taken else 'FALSE'} -> {target}")
            pc = target

        elif isinstance(instr, Ireturn):
            if instr.arg:
                val = regs.get(instr.arg, "UNDEF")
                print(f"  [{step:3d}] node {pc:3d}: return {instr.arg}={val}")
                print(f"\nResult: {val}")
                return val
            else:
                print(f"  [{step:3d}] node {pc:3d}: return void")
                return None

    print(f"ERROR: exceeded {max_steps} steps")
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 rtl_trace.py <program.json> [arg1 arg2 ...]")
        sys.exit(1)

    func = load_function(sys.argv[1])
    args = [int(a) for a in sys.argv[2:]]
    trace(func, args)
