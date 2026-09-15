#!/usr/bin/env python3
"""
Static analysis tool for RTL programs.
Computes dataflow properties: definitions, uses, control flow, reachability.

Usage: python3 rtl_analyze.py <program.json>

"""

import sys
from rtl import load_function, Inop, Iop, Icond, Ireturn


def analyze(func):
    print(f"=== Analysis of {func.name} ===")
    print(f"Parameters: {func.params}")
    print(f"Entry: node {func.entry}")
    print(f"Total nodes: {len(func.code)}")
    print()

    reachable = func.reachable_nodes()
    print(f"Reachable nodes: {sorted(reachable)}")
    unreachable = set(func.code.keys()) - reachable
    if unreachable:
        print(f"Unreachable nodes: {sorted(unreachable)}")
    print()

    preds = func.predecessors()

    print("--- Instructions ---")
    for node in sorted(func.code.keys()):
        instr = func.code[node]
        mark = " " if node in reachable else "!"
        print(f"  {mark} node {node:3d}: {instr}")
    print()

    defs = {}
    for node in sorted(func.code.keys()):
        instr = func.code[node]
        if isinstance(instr, Iop):
            defs.setdefault(instr.dest, []).append(node)

    uses = {}
    for node in sorted(func.code.keys()):
        instr = func.code[node]
        if isinstance(instr, Iop):
            for arg in instr.args:
                uses.setdefault(arg, []).append(node)
        elif isinstance(instr, Icond):
            for arg in instr.args:
                uses.setdefault(arg, []).append(node)
        elif isinstance(instr, Ireturn) and instr.arg:
            uses.setdefault(instr.arg, []).append(node)

    print("--- Definitions ---")
    for reg in sorted(defs.keys()):
        nodes = defs[reg]
        use_nodes = uses.get(reg, [])
        dead = " [DEAD]" if not use_nodes else ""
        print(f"  {reg}: def@{nodes} use@{use_nodes}{dead}")
    print()

    print("--- Constants ---")
    for node in sorted(func.code.keys()):
        instr = func.code[node]
        if isinstance(instr, Iop) and instr.op == "const":
            print(f"  node {node}: {instr.dest} = {instr.imm}")
    print()

    print("--- Control Flow ---")
    for node in sorted(func.code.keys()):
        instr = func.code[node]
        pred_list = sorted(preds.get(node, []))
        succ_list = instr.successors()
        nop_chain = ""
        if isinstance(instr, Inop):
            chain = []
            cur = instr.succ
            visited = {node}
            while cur in func.code and isinstance(func.code[cur], Inop) and cur not in visited:
                chain.append(cur)
                visited.add(cur)
                cur = func.code[cur].succ
            if chain:
                nop_chain = f"  [nop chain -> {cur}]"
        print(f"  node {node:3d}: preds={pred_list} succs={succ_list}{nop_chain}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 rtl_analyze.py <program.json>")
        sys.exit(1)

    func = load_function(sys.argv[1])
    analyze(func)
