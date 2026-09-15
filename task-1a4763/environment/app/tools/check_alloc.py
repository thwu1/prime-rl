#!/usr/bin/env python3
"""CLI tool to validate a register allocation against an IR program."""

import sys
import os

sys.path.insert(0, "/app")
import ir


def main():
    if len(sys.argv) < 2:
        print("Usage: check_alloc.py <program.json> [--verbose]", file=sys.stderr)
        sys.exit(1)

    prog_path = sys.argv[1]
    verbose = "--verbose" in sys.argv

    if not os.path.exists(prog_path):
        print(f"ERROR: {prog_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        import allocator
    except ImportError:
        print("ERROR: /app/allocator.py not found or cannot be imported", file=sys.stderr)
        sys.exit(1)

    prog = ir.load_program(prog_path)
    func = prog.functions["target"]

    try:
        alloc = allocator.allocate(func)
    except Exception as e:
        print(f"ERROR: allocator raised {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    errors = []

    # Check completeness
    for vreg in func.vreg_classes:
        if vreg not in alloc:
            errors.append(f"Missing allocation for '{vreg}'")

    # Check class constraints
    for vreg, phys in alloc.items():
        if phys.startswith("stack"):
            continue
        cls = func.vreg_classes.get(vreg)
        if cls:
            valid = ir.regs_for_class(cls)
            if phys not in valid:
                errors.append(f"{vreg} ({cls}) -> {phys} (invalid for class)")

    # Count spills per class
    gp_spills = sum(1 for v, r in alloc.items()
                    if r.startswith("stack") and func.vreg_classes.get(v) == "gp")
    xmm_spills = sum(1 for v, r in alloc.items()
                     if r.startswith("stack") and func.vreg_classes.get(v) == "xmm")

    # Count remaining copy moves
    remaining_moves = 0
    for label in func.block_order:
        block = func.blocks[label]
        for instr in block.instructions:
            if instr.op == "copy" and instr.src1 in alloc and instr.dst in alloc:
                if alloc[instr.src1] != alloc[instr.dst]:
                    remaining_moves += 1

    if errors:
        print(f"FAIL: {prog.name}")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"OK: {prog.name}")
        print(f"  vregs={len(alloc)}  gp_spills={gp_spills}  xmm_spills={xmm_spills}  remaining_moves={remaining_moves}")

    if verbose:
        for v in sorted(alloc.keys()):
            print(f"  {v} ({func.vreg_classes.get(v, '?')}) -> {alloc[v]}")


if __name__ == "__main__":
    main()
