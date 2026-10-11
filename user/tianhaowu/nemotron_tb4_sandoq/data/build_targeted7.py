"""Pool passing GLM-5.3-Flash traces of generated tasks for the 7 targeted TB4 families.

Sources (all ThWu/tmp exports, downloaded under /checkpoint/ram/tianhaowu/datasets/ThWu-tmp):
  - glm53flash-targeted-v2-720-passed-20261002: native trajectories + manifest; keep Submitted, no
    execution error, no user-reported task-quality concern.
  - glm53flash-targeted25-92-traces-20261002: native trajectories; keep reward 1 and Submitted.
  - nemotron-honeycomb-216-20260929: content-part SFT rows (already reward 1, Submitted); drop the
    rows the export's language filter removed (CJK text).
  - frontierbench-1b8782c4-glm53flash-fullpass84-20261011 (--fullpass; holds the 85-trace snapshot):
    native trajectories + results.csv, all reward 1; keep explicitly submitted ones.
Writes one content-part `traces.sft.jsonl` for data/prepare.sh.

--clean drops trajectories whose teacher output the student should not imitate; the targeted-7 run
trained on all of them and turned "!!!" from 1% of teacher turns into 25% of its own, with most of
its 32k-capped responses ending in "Hmm, h!! Hmm, !!!!" loops. A trajectory is dropped if any
assistant turn has no tool call (a format error or a response cut at the output limit), any turn's
reasoning + text reaches --max-turn-tokens (the teacher's 32k output cap), or it has
--max-exclaim-runs or more "!!!" runs in total.
"""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from convert_native import BASH_TOOL, convert_trajectory

EXCLAIM = re.compile(r"!{3,}")

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


def from_fullpass(root: Path):
    extracted = root / "extracted"
    for entry in csv.DictReader((extracted / "results.csv").open()):
        if float(entry["reward"]) != 1.0 or entry["submitted"] != "True":
            continue
        yield native_row(extracted / entry["native_trace_path"], entry["task"], entry["trial"], entry["family"], root.name)


def degenerate(row: dict, tokenizer, max_turn_tokens: int, max_exclaim_runs: int) -> str | None:
    turns = [m for m in row["messages"] if m["role"] == "assistant"]
    if any(not m.get("tool_calls") for m in turns):
        return "turn without tool call"
    texts = ["".join((part.get("thinking") or "") + (part.get("text") or "") for part in m["content"]) for m in turns]
    if max(len(e.ids) for e in tokenizer.encode_batch(texts)) >= max_turn_tokens:
        return f"turn >= {max_turn_tokens} tokens"
    if sum(len(EXCLAIM.findall(t)) for t in texts) >= max_exclaim_runs:
        return f">= {max_exclaim_runs} '!!!' runs"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/checkpoint/ram/tianhaowu/datasets/ThWu-tmp"))
    parser.add_argument("--dst", type=Path, required=True)
    parser.add_argument("--exclude-trace", action="append", default=[], help="drop this trace_id (e.g. over seq_len)")
    parser.add_argument("--fullpass", action="store_true", help="add the frontierbench fullpass snapshot")
    parser.add_argument("--clean", action="store_true", help="drop degenerate trajectories (see module docstring)")
    parser.add_argument("--max-turn-tokens", type=int, default=30000)
    parser.add_argument("--max-exclaim-runs", type=int, default=10)
    parser.add_argument("--tokenizer", default="/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16/tokenizer.json")
    args = parser.parse_args()
    sources = [
        from_targeted_v2(args.root / "glm53flash-targeted-v2-720-passed-20261002"),
        from_targeted25(args.root / "glm53flash-targeted25-92-traces-20261002"),
        from_honeycomb(args.root / "nemotron-honeycomb-216-20260929"),
    ]
    if args.fullpass:
        sources.append(from_fullpass(args.root / "frontierbench-1b8782c4-glm53flash-fullpass84-20261011"))
    tokenizer = None
    if args.clean:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(args.tokenizer)
    counts, dropped = Counter(), Counter()
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    with args.dst.open("w") as out:
        for source in sources:
            for row in source:
                if row["trace_id"] in args.exclude_trace:
                    continue
                reason = tokenizer and degenerate(row, tokenizer, args.max_turn_tokens, args.max_exclaim_runs)
                if reason:
                    dropped[(row["source"]["dataset"].split("-2026")[0], reason)] += 1
                    continue
                counts[(row["source"]["family"], row["source"]["dataset"])] += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    for family in FAMILIES:
        per = {d.split("-2026")[0]: n for (f, d), n in counts.items() if f == family}
        print(f"{family:30s} {sum(per.values()):4d} {per}")
    for (dataset, reason), n in sorted(dropped.items()):
        print(f"dropped {n:3d} {dataset}: {reason}")
    print(f"total {sum(counts.values())} rows -> {args.dst}")


if __name__ == "__main__":
    main()
