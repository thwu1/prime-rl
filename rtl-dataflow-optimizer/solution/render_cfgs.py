#!/usr/bin/env python3
"""
Generates Graphviz DOT control-flow graphs and renders them to SVG.

"""

import sys
import os
import subprocess

sys.path.insert(0, '/app')
from rtl import load_program
from optimizer import optimize

PROGRAMS_DIR = '/app/programs'
OUTPUT_DIR = '/app/cfg_output'
NAMES = ['poly_eval', 'const_arith', 'dead_triangle', 'branch_const', 'cascade', 'loop_constprop', 'nested_diamond', 'strength_chain']


def get_successors(instr):
    kind = instr["kind"]
    if kind == "nop":
        return [instr["succ"]]
    elif kind == "op":
        return [instr["succ"]]
    elif kind == "cond":
        return [instr["ifso"], instr["ifnot"]]
    elif kind == "ret":
        return []
    return []


def get_reachable(prog):
    code = prog["code"]
    entry = prog["entrypoint"]
    visited = set()
    queue = [entry]
    while queue:
        n = queue.pop(0)
        if n in visited or n not in code:
            continue
        visited.add(n)
        for s in get_successors(code[n]):
            if s not in visited:
                queue.append(s)
    return visited


def instr_label(instr):
    kind = instr["kind"]
    if kind == "nop":
        return "nop"
    elif kind == "op":
        op = instr["op"]
        if op == "const":
            return "r%d = %d" % (instr["dst"], instr["imm"])
        elif op == "move":
            return "r%d = r%d" % (instr["dst"], instr["args"][0])
        else:
            args_str = ", ".join("r%d" % a for a in instr["args"])
            return "r%d = %s(%s)" % (instr["dst"], op, args_str)
    elif kind == "cond":
        return "%s(r%d, r%d)" % (instr["cmp"], instr["arg1"], instr["arg2"])
    elif kind == "ret":
        return "ret r%d" % instr["arg"]
    return "?"


def prog_to_dot(prog, title):
    reachable = get_reachable(prog)
    code = prog["code"]
    lines = ['digraph "%s" {' % title.replace('"', '\\"')]
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=box, fontname="monospace"];')
    for n in sorted(reachable):
        instr = code[n]
        label = "%d: %s" % (n, instr_label(instr))
        label = label.replace('"', '\\"')
        lines.append('  n%d [label="%s"];' % (n, label))
    for n in sorted(reachable):
        instr = code[n]
        succs = get_successors(instr)
        if instr["kind"] == "cond" and len(succs) == 2:
            lines.append('  n%d -> n%d [label="T"];' % (n, succs[0]))
            lines.append('  n%d -> n%d [label="F"];' % (n, succs[1]))
        else:
            for s in succs:
                if s in code:
                    lines.append('  n%d -> n%d;' % (n, s))
    lines.append('}')
    return '\n'.join(lines)


os.makedirs(OUTPUT_DIR, exist_ok=True)

for name in NAMES:
    prog = load_program(os.path.join(PROGRAMS_DIR, '%s.json' % name))
    opt = optimize(prog)

    for tag, p in [('before', prog), ('after', opt)]:
        dot_content = prog_to_dot(p, '%s (%s)' % (name, tag))
        dot_path = os.path.join(OUTPUT_DIR, '%s_%s.dot' % (name, tag))
        svg_path = os.path.join(OUTPUT_DIR, '%s_%s.svg' % (name, tag))
        with open(dot_path, 'w') as f:
            f.write(dot_content)
        subprocess.run(['dot', '-Tsvg', '-o', svg_path, dot_path], check=True)

    print('Rendered %s' % name)

print('All CFGs rendered.')
