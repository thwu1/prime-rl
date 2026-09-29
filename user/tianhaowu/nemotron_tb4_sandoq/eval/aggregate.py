"""Merge Nemotron TB4 eval runs into one per-task table.

Every scored rollout across the given run dirs counts. Rollouts that hit infrastructure errors
(sandbox provisioning, taskset setup, tunnels) are excluded; a HarnessError (the agent process
itself died, e.g. killed by the sandbox OOM killer after an agent command) is agent behaviour and
counts as a failed attempt. Per task this reports attempts, solves, pass@1
(mean solve rate) and pass@k (any solve), overall and split into trained / held-out tasks.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

TRAINED = {
    "atrx-vep-crispr", "batched-eval-parity", "embedding-drift-monitor", "interleaved-vigenere",
    "protein-autointerp-disulfide", "react-lead-form", "risk-scorer-replay", "sound-change-cascade",
    "vpp-loss-divergence", "fin-saccr-rwa", "formal-crypto", "hof-topology-interpenetration",
    "html-js-filter", "mp-checkpoint-consolidation", "mvcc-lsm-compaction", "production-planning",
    "shadow-relay", "wal-recovery-ordering", "wdm-design",
}


AGENT_ERRORS = {"HarnessError"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path, help="eval output dirs")
    parser.add_argument("--tasks", type=Path, required=True, help="task list defining the denominator")
    args = parser.parse_args()

    wanted = [line.strip() for line in args.tasks.read_text().splitlines() if line.strip()]
    scored: dict[str, list[dict]] = defaultdict(list)
    errored: dict[str, str] = {}
    for run in args.runs:
        for line in (run / "results.jsonl").read_text().splitlines():
            row = json.loads(line)
            name = row["task"]["name"].split("/")[-1]
            error_types = {error.get("type") for error in row.get("errors") or []}
            if error_types - AGENT_ERRORS:
                errored.setdefault(name, row["errors"][0].get("type", "error"))
            else:
                scored[name].append(row)

    def solved(row: dict) -> bool:
        return row.get("rewards", {}).get("solved") == 1.0

    print(f"{'task':32s} {'trained':7s} {'solves':>7s} {'pass@1':>6s} {'turns':>6s} stops")
    for name in wanted:
        rows = scored.get(name, [])
        if not rows:
            print(f"{name:32s} {str(name in TRAINED):7s} {'-':>7s} {'-':>6s} {'-':>6s} {errored.get(name, 'not run')}")
            continue
        wins = sum(map(solved, rows))
        turns = sum(sum(1 for node in r["nodes"] if node.get("model_io")) for r in rows) / len(rows)
        stops = ",".join(
            sorted({"HarnessError" if r.get("errors") else str(r.get("stop_condition")) for r in rows})
        )
        print(f"{name:32s} {str(name in TRAINED):7s} {f'{wins}/{len(rows)}':>7s} {wins / len(rows):6.2f} {turns:6.0f} {stops}")

    def summarize(label: str, names: list[str]) -> None:
        if not names:
            return
        have = [n for n in names if scored.get(n)]
        pass1 = sum(sum(map(solved, scored[n])) / len(scored[n]) for n in have)
        passk = sum(any(map(solved, scored[n])) for n in have)
        attempts = sum(len(scored[n]) for n in have)
        print(f"{label:16s} pass@1 {pass1:5.2f}/{len(names)} ({pass1 / len(names):.1%})  "
              f"pass@k {passk}/{len(names)}  attempts {attempts}  missing {len(names) - len(have)}")

    print()
    summarize("all tasks", wanted)
    summarize("trained tasks", [n for n in wanted if n in TRAINED])
    summarize("held-out tasks", [n for n in wanted if n not in TRAINED])


if __name__ == "__main__":
    main()
