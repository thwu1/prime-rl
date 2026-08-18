#!/usr/bin/env python3
"""Launch the Kimi V3 evaluation when fewer than N V2 tasks lack four good rollouts."""

import argparse
import json
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import msgspec


class RolloutInfo(msgspec.Struct):
    task_path: str | None = None


class Rollout(msgspec.Struct):
    info: RolloutInfo | None = None
    stop_condition: str | None = None
    num_turns: int | float | None = None


RESULT_DECODER = msgspec.json.Decoder(Rollout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-dir",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/eval/kimi-k26-17k-think-r4"),
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/datasets/terminal_bench"),
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=Path("/storage/home/tianhaowu/launch_v3_kimi.sh"),
    )
    parser.add_argument(
        "--status-file",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/eval/kimi-k26-v3-think-r4/gate_status.json"),
    )
    parser.add_argument(
        "--job-id-file",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/eval/kimi-k26-v3-think-r4/job_ids.tsv"),
    )
    parser.add_argument("--threshold", type=int, default=512)
    parser.add_argument("--poll-seconds", type=int, default=120)
    return parser.parse_args()


def load_tasks(dataset_dir: Path) -> list[set[str]]:
    tasks_by_shard = []
    for shard in range(4):
        dataset = dataset_dir / f"v2_train_full_tr_shard{shard}.jsonl"
        tasks = {json.loads(line)["Path"] for line in dataset.read_text(encoding="utf-8").splitlines() if line}
        tasks_by_shard.append(tasks)
    return tasks_by_shard


def scan_results(
    eval_dir: Path,
    positions: dict[Path, int],
    good_counts: Counter[str],
) -> tuple[int, int]:
    new_rows = 0
    new_good = 0
    for result_file in sorted(eval_dir.glob("**/results.jsonl")):
        position = positions.get(result_file, 0)
        size = result_file.stat().st_size
        if size < position:
            raise RuntimeError(f"result file shrank: {result_file}")

        with result_file.open("rb") as handle:
            handle.seek(position)
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    handle.seek(line_start)
                    break

                new_rows += 1
                result = RESULT_DECODER.decode(line)
                task_path = result.info.task_path if result.info else None
                if task_path and result.stop_condition != "has_error" and (result.num_turns or 0) > 0:
                    good_counts[task_path] += 1
                    new_good += 1

            positions[result_file] = handle.tell()
    return new_rows, new_good


def write_status(status_file: Path, status: dict) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = status_file.with_suffix(f"{status_file.suffix}.tmp")
    temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    temporary.replace(status_file)


def main() -> None:
    args = parse_args()
    if args.threshold < 1:
        raise ValueError("threshold must be positive")
    if args.poll_seconds < 1:
        raise ValueError("poll-seconds must be positive")

    tasks_by_shard = load_tasks(args.dataset_dir)
    positions: dict[Path, int] = {}
    good_counts: Counter[str] = Counter()
    rows_seen = 0
    good_seen = 0

    while True:
        started = time.monotonic()
        new_rows, new_good = scan_results(args.eval_dir, positions, good_counts)
        rows_seen += new_rows
        good_seen += new_good
        remaining_by_shard = [sum(good_counts[task] < 4 for task in tasks) for tasks in tasks_by_shard]
        remaining = sum(remaining_by_shard)
        status = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": "waiting",
            "threshold": args.threshold,
            "remaining": remaining,
            "remaining_by_shard": remaining_by_shard,
            "rows_seen": rows_seen,
            "good_rollouts_seen": good_seen,
            "result_files": len(positions),
            "scan_seconds": round(time.monotonic() - started, 3),
        }
        write_status(args.status_file, status)
        print(
            f"{status['updated_at']} remaining={remaining} "
            f"by_shard={remaining_by_shard} new_rows={new_rows} "
            f"new_good={new_good} files={len(positions)}",
            flush=True,
        )

        if remaining < args.threshold:
            print(
                f"V2 remaining {remaining} is below {args.threshold}; launching V3.",
                flush=True,
            )
            result = subprocess.run(["bash", str(args.launcher)], check=False)
            if result.returncode == 0 and args.job_id_file.exists() and args.job_id_file.stat().st_size:
                status["state"] = "launched"
                status["launched_at"] = datetime.now(timezone.utc).isoformat()
                status["v3_jobs"] = args.job_id_file.read_text(encoding="utf-8").splitlines()
                write_status(args.status_file, status)
                return
            print(
                f"V3 launch did not produce job IDs (exit={result.returncode}); retrying.",
                flush=True,
            )

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
