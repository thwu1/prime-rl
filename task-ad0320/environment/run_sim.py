#!/usr/bin/env python3
"""Run the MOESI coherence simulator with diagnostics or a JSON trace."""


import json
import sys
from moesi_sim.simulator import MOESISimulator


def run_trace(path, json_output=None):
    """Load and execute a JSON trace file."""
    with open(path) as f:
        trace = json.load(f)
    sim = MOESISimulator()
    results = sim.execute_trace(trace)

    bank_stats = sim.get_bank_stats()
    memory_state = sim.get_memory_state()

    print("=== Execution Results ===")
    for r in results:
        if r["op"] in ("load", "lr"):
            print(f"  Core {r['core']}: {r['op']} "
                  f"addr={hex(r['addr'])} -> {r['value']}")
        elif r["op"] == "store":
            print(f"  Core {r['core']}: store addr={hex(r['addr'])}")
        elif r["op"] == "sc":
            ok = "SUCCESS" if r["success"] else "FAIL"
            print(f"  Core {r['core']}: sc addr={hex(r['addr'])} -> {ok}")

    print("\n=== Bank Statistics ===")
    for bid, st in bank_stats.items():
        total = sum(st.values())
        print(f"  Bank {bid}: total_requests={total}  {st}")

    print("\n=== Final Memory ===")
    for ba in sorted(memory_state.keys()):
        print(f"  block {ba} (addr {hex(ba << 6)}): {memory_state[ba]}")

    if json_output:
        output = {
            "results": results,
            "bank_stats": {str(k): v for k, v in bank_stats.items()},
            "memory_state": {str(k): v for k, v in memory_state.items()},
            "summary": dict(sim.stats),
        }
        with open(json_output, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nJSON output written to {json_output}")


def diagnostics():
    """Run protocol diagnostic checks and report pass/fail."""
    sep = "=" * 60
    errors = 0

    # --- Check 1: Bank interleaving ---
    print(sep)
    print("CHECK 1: Bank interleaving distribution")
    print(sep)
    sim = MOESISimulator()
    for i in range(16):
        sim.load(0, i * 64)
    stats = sim.get_bank_stats()
    for bid in range(4):
        print(f"  Bank {bid}: gets={stats[bid]['gets']}")
    if all(stats[b]["gets"] == 4 for b in range(4)):
        print("  >> PASS")
    else:
        print("  >> FAIL: traffic is not evenly distributed")
        errors += 1

    # --- Check 2: Read coherence after write-sharing ---
    print(f"\n{sep}")
    print("CHECK 2: Read coherence after write-sharing")
    print(sep)
    sim2 = MOESISimulator()
    sim2.store(0, 0x100, 42)
    val1 = sim2.load(1, 0x100)
    print(f"  Core 0 stores 42; Core 1 reads -> {val1}")
    sim2.store(2, 0x100, 99)
    val2 = sim2.load(0, 0x100)
    print(f"  Core 2 stores 99; Core 0 reads -> {val2}")
    if val1 == 42 and val2 == 99:
        print("  >> PASS")
    else:
        print(f"  >> FAIL: coherence violation detected")
        errors += 1

    # --- Check 3: LR/SC atomicity ---
    print(f"\n{sep}")
    print("CHECK 3: LR/SC atomicity under contention")
    print(sep)
    sim3 = MOESISimulator()
    sim3.store(0, 0x200, 10)
    sim3.load_reserved(0, 0x200)
    print("  Core 0: LR addr=0x200 (reservation set)")
    sim3.store(1, 0x200, 20)
    print("  Core 1: store 20 to 0x200")
    ok = sim3.store_conditional(0, 0x200, 30)
    print(f"  Core 0: SC -> {'SUCCESS' if ok else 'FAIL'}")
    if not ok:
        print("  >> PASS")
    else:
        print("  >> FAIL: SC should not have succeeded")
        errors += 1

    # --- Check 4: Upgrade optimization ---
    print(f"\n{sep}")
    print("CHECK 4: Upgrade transaction optimization")
    print(sep)
    sim4 = MOESISimulator()
    sim4.store(0, 0x300, 1)
    sim4.load(1, 0x300)
    sim4.store(1, 0x300, 2)
    stats4 = sim4.get_bank_stats()
    bank = sim4.interleaver.get_bank(0x300)
    upg = stats4[bank]["upgrade"]
    getm = stats4[bank]["getm"]
    print(f"  Bank {bank}: getm={getm}, upgrade={upg}")
    val = sim4.load(0, 0x300)
    print(f"  Core 0 reads -> {val} (expected 2)")
    if upg > 0 and val == 2:
        print("  >> PASS")
    else:
        reasons = []
        if upg == 0:
            reasons.append("no Upgrade transactions observed")
        if val != 2:
            reasons.append(f"incorrect value (got {val})")
        print(f"  >> FAIL: {'; '.join(reasons)}")
        errors += 1

    # --- Summary ---
    print(f"\n{sep}")
    passed = 4 - errors
    print(f"RESULT: {passed}/4 checks passed")
    if errors > 0:
        print(f"  {errors} check(s) FAILED")
    print(sep)
    return errors


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--trace" in args:
        trace_idx = args.index("--trace")
        if trace_idx + 1 >= len(args):
            print("Usage: python3 run_sim.py --trace <file.json> [--json-output <out.json>]")
            sys.exit(1)
        trace_file = args[trace_idx + 1]
        json_output = None
        if "--json-output" in args:
            jo_idx = args.index("--json-output")
            if jo_idx + 1 < len(args):
                json_output = args[jo_idx + 1]
        run_trace(trace_file, json_output)
    else:
        print("MOESI Coherence Protocol Simulator - Diagnostics\n")
        errors = diagnostics()
        sys.exit(1 if errors else 0)
