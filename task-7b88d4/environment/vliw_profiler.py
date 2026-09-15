#!/usr/bin/env python3
"""
VLIW Kernel Profiler -- profiles kernels running on the custom VLIW SIMD simulator.

Subcommands:
  profile    Quick profile: run kernel and print cycle count and correctness
  trace      Run kernel with tracing, output Chrome Trace Event Format JSON
  report     Generate comprehensive JSON profile report with slot utilization
  compare    Compare two profile reports side by side
"""

import argparse
import json
import sys
import os
import random
import hashlib
from copy import copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from problem import (
    Machine, Tree, Input, build_mem_image, reference_kernel2,
    N_CORES, SLOT_LIMITS, VLEN
)
from perf_takehome import KernelBuilder, BASELINE


def _run_kernel(seed, height, rounds, batch_size, trace=False):
    """Run the kernel and return (correct, cycles, machine, kb)."""
    random.seed(seed)
    forest = Tree.generate(height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)
    ref_mem = copy(mem)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)

    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES, trace=trace)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for rm in reference_kernel2(ref_mem):
        pass

    inp_values_p = ref_mem[6]
    inp_indices_p = ref_mem[5]
    n_vals = len(inp.values)
    n_idxs = len(inp.indices)
    values_ok = (
        machine.mem[inp_values_p : inp_values_p + n_vals]
        == ref_mem[inp_values_p : inp_values_p + n_vals]
    )
    indices_ok = (
        machine.mem[inp_indices_p : inp_indices_p + n_idxs]
        == ref_mem[inp_indices_p : inp_indices_p + n_idxs]
    )

    return values_ok and indices_ok, machine.cycle, machine, kb


def _compute_utilization(kb, cycles):
    """Compute per-engine slot utilization from instruction bundles."""
    engine_slots = {e: 0 for e in SLOT_LIMITS if e != "debug"}
    non_debug_bundles = 0

    for instr in kb.instrs:
        has_non_debug = any(k != "debug" for k in instr)
        if not has_non_debug:
            continue
        non_debug_bundles += 1
        for engine, slots in instr.items():
            if engine != "debug" and engine in engine_slots:
                engine_slots[engine] += len(slots)

    utilization = {}
    for engine, used in engine_slots.items():
        limit = SLOT_LIMITS[engine]
        max_possible = limit * cycles
        utilization[engine] = {
            "slots_used": used,
            "max_possible_slots": max_possible,
            "utilization_pct": round(
                used / max_possible * 100, 2
            ) if max_possible > 0 else 0.0,
        }

    return utilization, non_debug_bundles


def _kernel_fingerprint(kb):
    """Compute a fingerprint of the kernel instruction stream."""
    h = hashlib.sha256()
    for instr in kb.instrs:
        h.update(repr(sorted(instr.items())).encode())
    return h.hexdigest()[:16]


def cmd_profile(args):
    """Quick profile of the kernel."""
    correct, cycles, _machine, kb = _run_kernel(
        args.seed, args.height, args.rounds, args.batch
    )
    status = "CORRECT" if correct else "INCORRECT"
    speedup = BASELINE / cycles if cycles > 0 else float("inf")
    print(f"Status:             {status}")
    print(f"Cycles:             {cycles}")
    print(f"Baseline:           {BASELINE}")
    print(f"Speedup:            {speedup:.2f}x")
    print(f"Instruction count:  {len(kb.instrs)}")
    print(f"Kernel fingerprint: {_kernel_fingerprint(kb)}")
    if not correct:
        sys.exit(1)


def cmd_trace(args):
    """Run kernel with tracing enabled. Writes trace in Chrome Trace Event Format."""
    correct, cycles, machine, kb = _run_kernel(
        args.seed, args.height, args.rounds, args.batch, trace=True
    )
    del machine  # triggers __del__ which closes the trace file

    trace_path = os.path.abspath("trace.json")
    if args.output and os.path.abspath(args.output) != trace_path:
        os.rename(trace_path, os.path.abspath(args.output))
        trace_path = os.path.abspath(args.output)

    print(f"Trace written to {trace_path}")
    print(f"Cycles: {cycles}, Correct: {correct}")
    print()
    print("Analyze with jq:")
    print(f"  jq '.[0:10]' {trace_path}")
    print(f"  jq '[.[] | select(.cat==\"op\" and .name!=\"init\")] | length' {trace_path}")
    print(f"  jq '[.[] | select(.ph==\"M\" and .name==\"thread_name\")] | .[].args.name' {trace_path}")
    if not correct:
        sys.exit(1)


def cmd_report(args):
    """Generate comprehensive JSON profile report."""
    if not args.output:
        print(
            "Error: -o/--output is required for report generation", file=sys.stderr
        )
        sys.exit(1)

    correct, cycles, _machine, kb = _run_kernel(
        args.seed, args.height, args.rounds, args.batch
    )
    utilization, n_bundles = _compute_utilization(kb, cycles)
    speedup = BASELINE / cycles if cycles > 0 else float("inf")

    total_slots = sum(u["slots_used"] for u in utilization.values())

    report = {
        "profiler_version": "1.0.0",
        "kernel_fingerprint": _kernel_fingerprint(kb),
        "configuration": {
            "seed": args.seed,
            "tree_height": args.height,
            "rounds": args.rounds,
            "batch_size": args.batch,
        },
        "results": {
            "cycles": cycles,
            "baseline_cycles": BASELINE,
            "speedup": round(speedup, 2),
            "correct": correct,
        },
        "slot_utilization": utilization,
        "summary": {
            "instruction_count": len(kb.instrs),
            "non_debug_bundles": n_bundles,
            "avg_slots_per_bundle": round(total_slots / n_bundles, 2)
            if n_bundles > 0
            else 0.0,
        },
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Profile report written to {args.output}")
    print(json.dumps(report, indent=2))

    if not correct:
        sys.exit(1)


def cmd_compare(args):
    """Compare two profile reports side by side."""
    with open(args.report1) as f:
        r1 = json.load(f)
    with open(args.report2) as f:
        r2 = json.load(f)

    c1 = r1["results"]["cycles"]
    c2 = r2["results"]["cycles"]
    print(f"{'Metric':<30} {'Report 1':>12} {'Report 2':>12} {'Delta':>12}")
    print("-" * 66)
    print(f"{'Cycles':<30} {c1:>12} {c2:>12} {c2 - c1:>+12}")
    print(
        f"{'Speedup':<30} {r1['results']['speedup']:>11.2f}x {r2['results']['speedup']:>11.2f}x"
    )
    print(
        f"{'Correct':<30} {str(r1['results']['correct']):>12} {str(r2['results']['correct']):>12}"
    )
    print(
        f"{'Instructions':<30} {r1['summary']['instruction_count']:>12} {r2['summary']['instruction_count']:>12}"
    )
    print(
        f"{'Avg slots/bundle':<30} {r1['summary']['avg_slots_per_bundle']:>12.2f} {r2['summary']['avg_slots_per_bundle']:>12.2f}"
    )

    print(f"\n{'Engine Utilization':>30}")
    print("-" * 66)
    for engine in SLOT_LIMITS:
        if engine == "debug":
            continue
        u1 = r1["slot_utilization"].get(engine, {}).get("utilization_pct", 0)
        u2 = r2["slot_utilization"].get(engine, {}).get("utilization_pct", 0)
        delta = u2 - u1
        sign = "+" if delta > 0 else ""
        print(f"{engine:<30} {u1:>11.1f}% {u2:>11.1f}% {sign}{delta:>10.1f}pp")


def main():
    parser = argparse.ArgumentParser(
        description="VLIW Kernel Profiler -- profile and analyze kernels on the custom VLIW SIMD simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s profile                             Quick profile with defaults
  %(prog)s profile --seed 42                   Profile with specific seed
  %(prog)s trace -o /app/trace.json            Generate execution trace
  %(prog)s report -o /app/profile_report.json  Generate JSON profile report
  %(prog)s compare baseline.json opt.json      Compare two reports

The trace output uses Chrome Trace Event Format, viewable in Perfetto
(https://ui.perfetto.dev/) or analyzable with jq.
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    def add_common_args(p):
        p.add_argument(
            "--seed", type=int, default=123, help="Random seed (default: 123)"
        )
        p.add_argument(
            "--height", type=int, default=10, help="Tree height (default: 10)"
        )
        p.add_argument(
            "--rounds", type=int, default=16, help="Number of rounds (default: 16)"
        )
        p.add_argument(
            "--batch", type=int, default=256, help="Batch size (default: 256)"
        )

    p_profile = subparsers.add_parser(
        "profile", help="Quick profile: run kernel and print stats"
    )
    add_common_args(p_profile)

    p_trace = subparsers.add_parser(
        "trace",
        help="Generate execution trace (Chrome Trace Event Format)",
    )
    add_common_args(p_trace)
    p_trace.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output trace file (default: trace.json in cwd)",
    )

    p_report = subparsers.add_parser(
        "report", help="Generate comprehensive JSON profile report"
    )
    add_common_args(p_report)
    p_report.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        help="Output report file (required)",
    )

    p_compare = subparsers.add_parser(
        "compare", help="Compare two profile reports side by side"
    )
    p_compare.add_argument("report1", type=str, help="First profile report JSON")
    p_compare.add_argument("report2", type=str, help="Second profile report JSON")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "profile": cmd_profile,
        "trace": cmd_trace,
        "report": cmd_report,
        "compare": cmd_compare,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
