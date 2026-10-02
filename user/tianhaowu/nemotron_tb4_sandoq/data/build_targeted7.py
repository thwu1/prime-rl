"""Pool passing GLM-5.3-Flash traces of generated tasks for the 7 targeted TB4 families.

Sources (all ThWu/tmp exports, downloaded under /checkpoint/ram/tianhaowu/datasets/ThWu-tmp):
  - glm53flash-targeted-v2-720-passed-20261002: native trajectories + manifest; keep Submitted, no
    execution error, no user-reported task-quality concern.
  - glm53flash-targeted25-92-traces-20261002: native trajectories; keep reward 1 and Submitted.
  - nemotron-honeycomb-216-20260929: content-part SFT rows (already reward 1, Submitted); drop the
    rows the export's language filter removed (CJK text).
Writes one content-part `traces.sft.jsonl` for data/prepare.sh.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from convert_native import BASH_TOOL, convert_trajectory

FAMILIES = (
    "embedding-drift-monitor",
    "fin-saccr-rwa",
    "mvcc-lsm-compaction",
    "protein-autointerp-disulfide",
    "wal-recovery-ordering",
    "batched-eval-parity",
    "shadow-relay",
)
TARGETED25_PREFIX = {
    "batched": "batched-eval-parity",
    "embedding": "embedding-drift-monitor",
    "mvcc": "mvcc-lsm-compaction",
    "saccr": "fin-saccr-rwa",
    "shadow": "shadow-relay",
}


def native_row(path: Path, task: str, trace_id: str, family: str, source: str) -> dict:
    return {
        "task_id": task,
        "trace_id": trace_id,
        "messages": convert_trajectory(path),
        "tools": [BASH_TOOL],
        "source": {"dataset": source, "family": family, "path": str(path)},
    }


def from_targeted_v2(root: Path):
    extracted = root / "extracted" / root.name
    for trace in json.loads((root / "manifest.json").read_text())["traces"]:
        if trace["family"] not in FAMILIES or trace["exit_status"] != "Submitted" or trace.get("error"):
            continue
        if "user_reported_task_quality_concern" in trace.get("flags", []):
            continue
        yield native_row(
            extracted / trace["native_trace"], trace["task"], f"{trace['group']}/{trace['trial']}",
            trace["family"], root.name,
        )


def from_targeted25(root: Path):
    extracted = root / "extracted" / root.name
    for entry in json.loads((root / "manifest.json").read_text())["entries"]:
        if entry["reward"] != 1.0 or entry["audit"]["exit_status"] != "Submitted":
            continue
        family = TARGETED25_PREFIX[entry["task"].split("-")[0]]
        path = extracted / entry["task"] / entry["trial"] / "agent" / "mini-swe-agent.trajectory.json"
        yield native_row(path, entry["task"], entry["trial"], family, root.name)


def from_honeycomb(root: Path):
    dropped = {d["trace_id"] for d in json.loads((root / "language-filter.json").read_text())["dropped"]}
    for line in (root / "traces.sft.jsonl").read_text().split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        if row["trace_id"] in dropped:
            continue
        family = next(f for f in FAMILIES if row["task_id"].startswith(f))
        row["source"] = {**row["source"], "dataset": root.name, "family": family}
        yield row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/checkpoint/ram/tianhaowu/datasets/ThWu-tmp"))
    parser.add_argument("--dst", type=Path, required=True)
    parser.add_argument("--exclude-trace", action="append", default=[], help="drop this trace_id (e.g. over seq_len)")
    args = parser.parse_args()
    sources = [
        from_targeted_v2(args.root / "glm53flash-targeted-v2-720-passed-20261002"),
        from_targeted25(args.root / "glm53flash-targeted25-92-traces-20261002"),
        from_honeycomb(args.root / "nemotron-honeycomb-216-20260929"),
    ]
    counts = Counter()
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    with args.dst.open("w") as out:
        for source in sources:
            for row in source:
                if row["trace_id"] in args.exclude_trace:
                    continue
                counts[(row["source"]["family"], row["source"]["dataset"])] += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    for family in FAMILIES:
        per = {d.split("-2026")[0]: n for (f, d), n in counts.items() if f == family}
        print(f"{family:30s} {sum(per.values()):4d} {per}")
    print(f"total {sum(counts.values())} rows -> {args.dst}")


if __name__ == "__main__":
    main()
