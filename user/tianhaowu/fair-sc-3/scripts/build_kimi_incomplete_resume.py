#!/usr/bin/env python3
"""Build Kimi eval datasets for tasks with fewer than four valid rollouts."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

RESULT_PATTERNS = (
    "kimi-k26-12k-think/evals/**/results.jsonl",
    "kimi-k26-12k-think-pass2/evals/**/results.jsonl",
    "kimi-k26-17k-think-r4/**/results.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/eval"),
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("/checkpoint/ram/tianhaowu/datasets/terminal_bench"),
    )
    parser.add_argument("--minimum-rollouts", type=int, default=4)
    parser.add_argument("--output-suffix", default="incomplete4")
    return parser.parse_args()


def find_result_files(eval_root: Path) -> list[Path]:
    result_files = {
        path
        for pattern in RESULT_PATTERNS
        for path in eval_root.glob(pattern)
        if path.stat().st_size > 0
    }
    return sorted(result_files)


def is_valid_rollout(result: dict) -> bool:
    if result.get("error") is not None:
        return False
    if result.get("tb_outcome") == "env_error":
        return False
    return result.get("stop_condition") != "prompt_too_long"


def load_rollout_counts(result_files: list[Path]) -> tuple[Counter[str], int, int]:
    counts: Counter[str] = Counter()
    row_count = 0
    valid_count = 0

    for result_file in result_files:
        with result_file.open("rb") as handle:
            for line in handle:
                row_count += 1
                result = json.loads(line)
                if not is_valid_rollout(result):
                    continue

                info = result.get("info") or {}
                task_name = info.get("task_name")
                if not task_name:
                    task_path = info.get("task_path")
                    if not task_path:
                        raise ValueError(f"valid result lacks task identity: {result_file}")
                    task_name = Path(task_path).name
                counts[task_name] += 1
                valid_count += 1

    return counts, row_count, valid_count


def write_incomplete_shards(
    dataset_root: Path,
    output_suffix: str,
    minimum_rollouts: int,
    counts: Counter[str],
) -> None:
    coverage: Counter[int] = Counter()

    for shard in range(4):
        source = dataset_root / f"v2_train_full_tr_shard{shard}.jsonl"
        output = dataset_root / f"v2_train_full_tr_shard{shard}_{output_suffix}.jsonl"
        temp_output = output.with_suffix(f"{output.suffix}.tmp")

        source_rows = [json.loads(line) for line in source.read_bytes().splitlines()]
        for row in source_rows:
            coverage[min(counts[Path(row["Path"]).name], minimum_rollouts)] += 1
        remaining = [
            row
            for row in source_rows
            if counts[Path(row["Path"]).name] < minimum_rollouts
        ]

        with temp_output.open("w", encoding="utf-8") as handle:
            for row in remaining:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        os.replace(temp_output, output)

        print(
            f"shard{shard}: total={len(source_rows)} complete={len(source_rows) - len(remaining)} "
            f"remaining={len(remaining)} output={output}"
        )

    distribution = " ".join(
        f"{rollouts}={coverage[rollouts]}"
        for rollouts in range(minimum_rollouts)
    )
    print(f"coverage_before_resume: {distribution} {minimum_rollouts}+={coverage[minimum_rollouts]}")


def main() -> None:
    args = parse_args()
    result_files = find_result_files(args.eval_root)
    counts, row_count, valid_count = load_rollout_counts(result_files)
    print(
        f"results: files={len(result_files)} rows={row_count} "
        f"valid_rollouts={valid_count}"
    )
    write_incomplete_shards(
        args.dataset_root,
        args.output_suffix,
        args.minimum_rollouts,
        counts,
    )


if __name__ == "__main__":
    main()
