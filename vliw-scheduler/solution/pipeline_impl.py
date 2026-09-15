#!/usr/bin/env python3
"""
VLIW Scheduler Pipeline — orchestration script.

Subcommands:
  schedule  — schedule all programs, write bundle JSON to /app/output/
  dot       — generate Graphviz DOT dependency graphs to /app/output/
  report    — produce /app/output/report.json with scheduling statistics
"""


import json
import os
import sys

sys.path.insert(0, "/app")
from isa import get_reads_writes, get_unit, is_memory_access
from scheduler import schedule
from simulator import run_vliw

PROG_NAMES = ["prog1", "prog2", "prog3"]
OUTPUT_DIR = "/app/output"


def load_program(name):
    with open(f"/app/programs/{name}.json") as f:
        return json.load(f)


# ── Dependency graph construction (for DOT generation) ────────────────────

def _build_dependency_graph(instrs):
    """Build a dependency DAG over instruction indices.
    Tracks RAW, WAR, WAW register hazards and memory ordering."""
    n = len(instrs)
    deps = [set() for _ in range(n)]
    last_writer = {}
    last_readers = {}
    last_mem_op = -1

    for i, instr in enumerate(instrs):
        reads, writes = get_reads_writes(instr)
        unit, op = instr[0], instr[1]

        for r in reads:
            if r in last_writer:
                deps[i].add(last_writer[r])
        for r in writes:
            if r in last_writer:
                deps[i].add(last_writer[r])
        for r in writes:
            if r in last_readers:
                deps[i].update(last_readers[r])
        if is_memory_access(instr):
            if last_mem_op >= 0:
                deps[i].add(last_mem_op)
            last_mem_op = i
        if unit == "flow" and op == "halt":
            for j in range(i):
                if instrs[j][0] == "store":
                    deps[i].add(j)

        for r in writes:
            last_writer[r] = i
            last_readers[r] = set()
        for r in reads:
            if r not in last_readers:
                last_readers[r] = set()
            last_readers[r].add(i)

    return deps


def _instr_label(i, instr):
    """Short label for an instruction node in DOT."""
    unit, op = instr[0], instr[1]
    args = instr[2:]
    if unit == "alu":
        return f"i{i}: {op} r{args[0]},r{args[1]},r{args[2]}"
    elif unit == "load":
        if op == "const":
            return f"i{i}: const r{args[0]},{args[1]}"
        else:
            return f"i{i}: load r{args[0]},[r{args[1]}]"
    elif unit == "store":
        return f"i{i}: store [r{args[0]}],r{args[1]}"
    elif unit == "flow":
        if op == "halt":
            return f"i{i}: halt"
        else:
            return f"i{i}: mov r{args[0]},r{args[1]}"
    return f"i{i}: {unit}.{op}"


def _generate_dot(instrs, deps, prog_name):
    """Generate Graphviz DOT digraph representation of the dependency graph."""
    lines = [f"digraph {prog_name}_deps {{"]
    lines.append("  rankdir=TB;")
    lines.append('  node [shape=box, fontsize=10];')

    unit_colors = {
        "alu": "#ffcccc", "load": "#ccffcc",
        "store": "#ccccff", "flow": "#ffffcc"
    }

    for i, instr in enumerate(instrs):
        label = _instr_label(i, instr).replace('"', '\\"')
        unit = get_unit(instr)
        color = unit_colors.get(unit, "#ffffff")
        lines.append(
            f'  n{i} [label="{label}", style=filled, fillcolor="{color}"];'
        )

    for i, dep_set in enumerate(deps):
        for j in sorted(dep_set):
            lines.append(f"  n{j} -> n{i};")

    lines.append("}")
    return "\n".join(lines)


# ── Subcommands ───────────────────────────────────────────────────────────

def cmd_schedule():
    """Schedule all programs, write bundle JSON to output directory."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for prog_name in PROG_NAMES:
        prog = load_program(prog_name)
        instrs = prog["instructions"]
        bundles = schedule(instrs, max_registers=256)
        out_path = f"{OUTPUT_DIR}/{prog_name}_bundles.json"
        with open(out_path, "w") as f:
            json.dump(bundles, f, indent=2)
        print(f"{prog_name}: {len(instrs)} instructions -> {len(bundles)} bundles")


def cmd_dot():
    """Generate Graphviz DOT dependency graph files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for prog_name in PROG_NAMES:
        prog = load_program(prog_name)
        instrs = prog["instructions"]
        deps = _build_dependency_graph(instrs)
        dot_content = _generate_dot(instrs, deps, prog_name)
        out_path = f"{OUTPUT_DIR}/{prog_name}_deps.dot"
        with open(out_path, "w") as f:
            f.write(dot_content)
        print(f"{prog_name}: DOT graph -> {out_path}")


def cmd_report():
    """Generate scheduling statistics report as JSON."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report = {}
    for prog_name in PROG_NAMES:
        prog = load_program(prog_name)
        instrs = prog["instructions"]
        memory_init = {int(k): v for k, v in prog["memory_init"].items()}

        bundles = schedule(instrs, max_registers=256)
        _, vliw_cycles = run_vliw(bundles, memory_init)

        all_regs = set()
        for bundle in bundles:
            for instr in bundle:
                reads, writes = get_reads_writes(instr)
                all_regs.update(reads)
                all_regs.update(writes)

        seq_cycles = len(instrs)
        report[prog_name] = {
            "sequential_cycles": seq_cycles,
            "vliw_cycles": vliw_cycles,
            "speedup": round(seq_cycles / vliw_cycles, 4),
            "num_bundles": len(bundles),
            "total_instructions": sum(len(b) for b in bundles),
            "max_register": max(all_regs) if all_regs else 0
        }

    out_path = f"{OUTPUT_DIR}/report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report -> {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: pipeline.py {schedule|dot|report}", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    commands = {"schedule": cmd_schedule, "dot": cmd_dot, "report": cmd_report}
    if cmd not in commands:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(commands)}", file=sys.stderr)
        sys.exit(1)

    commands[cmd]()


if __name__ == "__main__":
    main()
