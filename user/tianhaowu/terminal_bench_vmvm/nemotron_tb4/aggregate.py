"""Merge Nemotron TB4 eval runs into one per-task table.

For each task the first scored result (a rollout without runtime errors) across the given run
dirs wins, so later retry runs fill in tasks whose earlier attempt hit infrastructure errors.
Reports solve rate overall and for the tasks present in the SFT training data.
"""

import argparse
import json
from pathlib import Path

TRAINED = {
    "atrx-vep-crispr", "batched-eval-parity", "embedding-drift-monitor", "interleaved-vigenere",
    "protein-autointerp-disulfide", "react-lead-form", "risk-scorer-replay", "sound-change-cascade",
    "vpp-loss-divergence", "fin-saccr-rwa", "formal-crypto", "hof-topology-interpenetration",
    "html-js-filter", "mp-checkpoint-consolidation", "mvcc-lsm-compaction", "production-planning",
    "shadow-relay", "wal-recovery-ordering", "wdm-design",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path, help="eval output dirs (earlier first)")
    parser.add_argument("--tasks", type=Path, required=True, help="task list defining the denominator")
    args = parser.parse_args()

    wanted = [line.strip() for line in args.tasks.read_text().splitlines() if line.strip()]
    best: dict[str, dict] = {}
    errored: dict[str, str] = {}
    for run in args.runs:
        for line in (run / "results.jsonl").read_text().splitlines():
            row = json.loads(line)
            name = row["task"]["name"].split("/")[-1]
            if row.get("errors"):
                errored.setdefault(name, row["errors"][0].get("type", "error"))
                continue
            best.setdefault(name, row)

    def summarize(names: list[str]) -> str:
        scored = [n for n in names if n in best]
        solved = sum(best[n].get("rewards", {}).get("solved") == 1.0 for n in scored)
        return f"solved {solved}/{len(names)} (scored {len(scored)}, missing {len(names) - len(scored)})"

    print(f"{'task':32s} {'trained':7s} {'solved':6s} {'turns':>5s} stop")
    for name in wanted:
        row = best.get(name)
        if row is None:
            print(f"{name:32s} {str(name in TRAINED):7s} {'-':6s} {'-':>5s} {errored.get(name, 'not run')}")
            continue
        turns = sum(1 for node in row["nodes"] if node.get("model_io"))
        solved = row.get("rewards", {}).get("solved")
        print(f"{name:32s} {str(name in TRAINED):7s} {str(solved):6s} {turns:5d} {row.get('stop_condition')}")
    print()
    print("all tasks:     ", summarize(wanted))
    print("trained tasks: ", summarize([n for n in wanted if n in TRAINED]))
    print("held-out tasks:", summarize([n for n in wanted if n not in TRAINED]))


if __name__ == "__main__":
    main()
