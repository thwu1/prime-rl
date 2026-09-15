#!/usr/bin/env python3
"""
Run the dirty page write throttling simulation and save results.

Usage:
    python3 /app/run.py

Results are written to /app/results/simulation.json and
/app/results/simulation.csv (for gnuplot).
"""


import json
import os
import sys

from config import CONFIG
from simulator import run_simulation


def main():
    print(f"System: {CONFIG['system']['total_pages']} pages, "
          f"limit={int(CONFIG['system']['total_pages'] * CONFIG['system']['dirty_limit_ratio'])}, "
          f"setpoint={int(CONFIG['system']['total_pages'] * CONFIG['system']['dirty_limit_ratio'] * CONFIG['system']['setpoint_ratio'])}")
    print(f"BDIs: {', '.join(b['name'] + '=' + str(b['bandwidth']) + ' pg/tick' for b in CONFIG['bdis'])}")
    print(f"Tasks: {len(CONFIG['tasks'])} writers")
    print(f"Running {CONFIG['simulation']['num_ticks']} ticks...")
    print()

    try:
        history = run_simulation(CONFIG)
    except NotImplementedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Some throttle functions are not yet implemented.", file=sys.stderr)
        sys.exit(1)

    # Save results
    os.makedirs("/app/results", exist_ok=True)

    results_path = "/app/results/simulation.json"
    with open(results_path, "w") as f:
        json.dump(history, f)

    # Save CSV for gnuplot
    bdi_names = [b["name"] for b in CONFIG["bdis"]]
    csv_path = "/app/results/simulation.csv"
    with open(csv_path, "w") as f:
        header = "tick,nr_dirty,setpoint,limit," + ",".join(
            f"{name}_dirty" for name in bdi_names
        )
        f.write(header + "\n")
        for h in history:
            bdi_cols = ",".join(
                str(h["bdi"][name]["dirty"]) for name in bdi_names
            )
            f.write(f"{h['tick']},{h['nr_dirty']},{h['setpoint']},"
                    f"{h['limit']},{bdi_cols}\n")

    # Print summary
    print(f"Wrote {len(history)} ticks to {results_path}")
    print(f"Wrote CSV to {csv_path}")
    print()

    last = history[-1]
    print(f"Final state (tick {last['tick']}):")
    print(f"  nr_dirty = {last['nr_dirty']}, setpoint = {last['setpoint']}, "
          f"limit = {last['limit']}, pos_ratio = {last['pos_ratio']}")
    for name, state in last["bdi"].items():
        print(f"  {name}: dirty={state['dirty']:.0f}, "
              f"writers_est={state['writers_est']:.1f}, "
              f"dirtied_last_tick={state['dirtied']:.0f}")

    # Check convergence
    if len(history) >= 100:
        last_100 = history[-100:]
        avg = sum(h["nr_dirty"] for h in last_100) / 100
        setpoint = last_100[0]["setpoint"]
        pct = abs(avg - setpoint) / setpoint * 100
        print(f"\n  Avg dirty (last 100 ticks): {avg:.0f}  "
              f"(deviation from setpoint: {pct:.1f}%)")
        if pct < 10:
            print("  STATUS: CONVERGED")
        else:
            print("  STATUS: NOT CONVERGED")


if __name__ == "__main__":
    main()
