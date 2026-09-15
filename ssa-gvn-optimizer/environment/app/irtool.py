#!/usr/bin/env python3
"""
irtool.py - CLI toolkit for working with toy SSA IR programs.

"""
import sys
import os
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ir import Function, Block, Instr, Phi, Terminator, interpret, count_ops


def parse_ir(text):
    """Parse text-format IR into a Function object."""
    lines = [l.rstrip() for l in text.strip().split('\n')]

    # Skip leading comments and blank lines
    header_idx = 0
    while header_idx < len(lines):
        stripped = lines[header_idx].strip()
        if stripped and not stripped.startswith('#'):
            break
        header_idx += 1

    m = re.match(r'function\s+(\w+)\((\d+)\):', lines[header_idx])
    if not m:
        raise ValueError(f"Expected function header, got: {lines[header_idx]}")
    func = Function(m.group(1), int(m.group(2)))

    current_block = None
    for raw_line in lines[header_idx + 1:]:
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue

        # Block header
        if re.match(r'\w+:$', line):
            bname = line.rstrip(':')
            current_block = func.add_block(bname)
            continue

        if current_block is None:
            raise ValueError(f"Instruction outside block: {line}")

        # Terminator
        if line.startswith(('jump ', 'branch ', 'return ')):
            parts = line.split()
            current_block.term = Terminator(parts[0], parts[1:])
            continue

        # Phi node
        m_phi = re.match(r'(\w+)\s*=\s*phi\s+(.*)', line)
        if m_phi:
            dst = m_phi.group(1)
            incoming = {}
            for pair in m_phi.group(2).split():
                pred, val = pair.split(':')
                incoming[pred] = val
            current_block.phis.append(Phi(dst, incoming))
            continue

        # Regular instruction
        m_instr = re.match(r'(\w+)\s*=\s*(\w+)\s*(.*)', line)
        if m_instr:
            dst = m_instr.group(1)
            op = m_instr.group(2)
            args_str = m_instr.group(3).strip()
            args = []
            if args_str:
                for a in args_str.split():
                    try:
                        args.append(int(a))
                    except ValueError:
                        args.append(a)
            current_block.instrs.append(Instr(dst, op, args))
            continue

        raise ValueError(f"Cannot parse line: {line}")

    return func


def dump_ir(func):
    """Serialize a Function back to text IR format."""
    lines = [f"function {func.name}({func.n_args}):"]
    for bname in func.block_order:
        block = func.blocks[bname]
        lines.append(f"{bname}:")
        for phi in block.phis:
            parts = " ".join(f"{k}:{v}" for k, v in sorted(phi.incoming.items()))
            lines.append(f"  {phi.dst} = phi {parts}")
        for instr in block.instrs:
            args = " ".join(str(a) for a in instr.args)
            lines.append(f"  {instr.dst} = {instr.op} {args}")
        if block.term:
            args = " ".join(str(a) for a in block.term.args)
            lines.append(f"  {block.term.op} {args}")
    return "\n".join(lines)


def get_stats(func):
    """Compute per-opcode instruction counts and phi count."""
    stats = {}
    n_phis = 0
    for bname in func.block_order:
        block = func.blocks[bname]
        n_phis += len(block.phis)
        for instr in block.instrs:
            stats[instr.op] = stats.get(instr.op, 0) + 1
    return stats, n_phis


def parse_heap(heap_str):
    """Parse heap string 'obj,off:val;...' into dict."""
    heap = {}
    if not heap_str:
        return heap
    for entry in heap_str.split(';'):
        if not entry.strip():
            continue
        key_part, val_part = entry.split(':')
        obj, off = key_part.split(',')
        heap[(int(obj), int(off))] = int(val_part)
    return heap


def cmd_parse(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    print(func)


def cmd_dump(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    print(dump_ir(func))


def cmd_interpret(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    heap = parse_heap(args.heap)
    result = interpret(func, args.args, initial_heap=heap if heap else None)
    print(f"Result: {result}")


def cmd_stats(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    stats, n_phis = get_stats(func)
    total = sum(stats.values())
    print(f"Function: {func.name}({func.n_args} args)")
    print(f"Blocks: {len(func.blocks)}")
    print(f"Phi nodes: {n_phis}")
    print(f"Instructions by opcode:")
    for op in sorted(stats):
        print(f"  {op}: {stats[op]}")
    print(f"Total instructions: {total}")


def cmd_optimize(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    from optimize import optimize
    opt_func = optimize(func.deep_copy())
    print(dump_ir(opt_func))


def cmd_verify(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    from optimize import optimize
    heap = parse_heap(args.heap)
    h = heap if heap else None

    orig_result = interpret(func, args.args, initial_heap=dict(h) if h else None)
    opt_func = optimize(func.deep_copy())
    opt_result = interpret(opt_func, args.args, initial_heap=dict(h) if h else None)

    orig_stats, orig_phis = get_stats(func)
    opt_stats, opt_phis = get_stats(opt_func)
    orig_total = sum(orig_stats.values())
    opt_total = sum(opt_stats.values())

    print(f"Original result:  {orig_result}")
    print(f"Optimized result: {opt_result}")
    ok = orig_result == opt_result
    print(f"Semantics preserved: {ok}")
    print(f"Instructions: {orig_total} -> {opt_total} ({orig_total - opt_total} eliminated)")
    print(f"Phi nodes:    {orig_phis} -> {opt_phis} ({orig_phis - opt_phis} eliminated)")
    if not ok:
        sys.exit(1)


def cmd_diff(args):
    with open(args.file) as f:
        func = parse_ir(f.read())
    from optimize import optimize
    orig_text = dump_ir(func)
    opt_func = optimize(func.deep_copy())
    opt_text = dump_ir(opt_func)
    print("=== ORIGINAL ===")
    print(orig_text)
    print()
    print("=== OPTIMIZED ===")
    print(opt_text)


def main():
    parser = argparse.ArgumentParser(
        description='Toy SSA IR toolkit — parse, interpret, and optimize IR programs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 irtool.py stats benchmarks/local_cse.ir
  python3 irtool.py interpret benchmarks/local_cse.ir 3 5
  python3 irtool.py optimize benchmarks/local_cse.ir
  python3 irtool.py verify benchmarks/local_cse.ir 3 5
  python3 irtool.py diff benchmarks/local_cse.ir
  python3 irtool.py interpret benchmarks/heap_ops.ir 100 7 --heap '100,0:42'
""")
    sub = parser.add_subparsers(dest='cmd')

    p = sub.add_parser('parse', help='Parse and pretty-print an IR file')
    p.add_argument('file', help='Path to .ir file')
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser('dump', help='Dump IR in canonical text format')
    p.add_argument('file', help='Path to .ir file')
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser('interpret', help='Run an IR program with given arguments')
    p.add_argument('file', help='Path to .ir file')
    p.add_argument('args', nargs='*', type=int, help='Integer arguments')
    p.add_argument('--heap', default='', help='Initial heap: obj,off:val;obj,off:val;...')
    p.set_defaults(func=cmd_interpret)

    p = sub.add_parser('stats', help='Show operation statistics for an IR program')
    p.add_argument('file', help='Path to .ir file')
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser('optimize', help='Run optimizer and print the optimized IR')
    p.add_argument('file', help='Path to .ir file')
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser('verify', help='Compare original vs optimized output')
    p.add_argument('file', help='Path to .ir file')
    p.add_argument('args', nargs='*', type=int, help='Integer arguments')
    p.add_argument('--heap', default='', help='Initial heap: obj,off:val;obj,off:val;...')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('diff', help='Show before/after optimization side-by-side')
    p.add_argument('file', help='Path to .ir file')
    p.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == '__main__':
    main()
