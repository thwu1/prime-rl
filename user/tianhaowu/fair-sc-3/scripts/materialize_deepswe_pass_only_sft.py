#!/usr/bin/env python3
"""Materialize a pass-only view of a processed DeepSWE SFT dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--validation-size", type=int, default=32)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def row_key(split: str, row: dict[str, Any]) -> tuple[str, int]:
    source_row_index = row.get("source_row_index")
    if not isinstance(source_row_index, int):
        raise TypeError(f"{split} row has invalid source_row_index: {source_row_index!r}")
    return split, source_row_index


def select_passes(rows: list[dict[str, Any]], *, split: str) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        reward = row.get("reward")
        if reward not in {0, 1, 0.0, 1.0}:
            raise ValueError(f"{split} row has non-binary reward: {reward!r}")
        if reward == 1:
            if row.get("is_correct") is not True:
                raise ValueError(f"{split} reward-1 row is not marked correct")
            selected.append(row)
    return selected


def validation_view(
    rows: list[dict[str, Any]],
    *,
    validation_size: int,
    lengths: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        raise ValueError("Pass-only validation split is empty")
    if validation_size < len(rows):
        raise ValueError(
            f"validation-size {validation_size} is smaller than the {len(rows)} unique validation rows"
        )

    complete_repeats, remainder = divmod(validation_size, len(rows))
    padded = rows * complete_repeats
    ranked_indices = sorted(
        range(len(rows)),
        key=lambda index: (
            lengths[row_key("validation", rows[index])]["trainable_tokens"],
            lengths[row_key("validation", rows[index])]["tokens"],
            rows[index]["source_row_index"],
        ),
    )
    padded.extend(rows[index] for index in ranked_indices[:remainder])

    counts = Counter(row_key("validation", row) for row in padded)
    duplicates = [
        {
            "source_validation_index": index,
            "source_row_index": row["source_row_index"],
            "task_id": row["task_id"],
            "copies": counts[row_key("validation", row)],
            "rendered_tokens": lengths[row_key("validation", row)]["tokens"],
            "trainable_tokens": lengths[row_key("validation", row)]["trainable_tokens"],
        }
        for index, row in enumerate(rows)
        if counts[row_key("validation", row)] > 1
    ]
    return padded, duplicates


def materialize(source_root: Path, output_root: Path, validation_size: int) -> dict[str, Any]:
    source_manifest_path = source_root / "manifest.json"
    source_lengths_path = source_root / "rendered-lengths.jsonl"
    source_manifest = json.loads(source_manifest_path.read_text())
    source_train = read_jsonl(source_root / "train" / "train.jsonl")
    source_validation = read_jsonl(source_root / "validation" / "train.jsonl")
    train_rows = select_passes(source_train, split="train")
    validation_rows = select_passes(source_validation, split="validation")

    train_tasks = {row["task_id"] for row in train_rows}
    validation_tasks = {row["task_id"] for row in validation_rows}
    overlap = train_tasks & validation_tasks
    if overlap:
        raise ValueError(f"Train/validation task leakage: {sorted(overlap)[:5]}")

    all_lengths = read_jsonl(source_lengths_path)
    lengths = {
        (item["split"], item["source_row_index"]): item
        for item in all_lengths
        if item.get("retained") is True
    }
    selected_keys = {
        *(row_key("train", row) for row in train_rows),
        *(row_key("validation", row) for row in validation_rows),
    }
    missing_lengths = selected_keys - lengths.keys()
    if missing_lengths:
        raise ValueError(f"Missing rendered lengths for {sorted(missing_lengths)[:5]}")
    selected_lengths = [lengths[key] for key in selected_keys]
    if max(item["tokens"] for item in selected_lengths) > 192_000:
        raise ValueError("Pass-only selection contains a trajectory above 192000 tokens")

    padded_validation, duplicates = validation_view(
        validation_rows,
        validation_size=validation_size,
        lengths=lengths,
    )

    output_root.mkdir(parents=True, exist_ok=True)
    all_path = output_root / "all.parquet"
    pq.write_table(pa.Table.from_pylist(train_rows + validation_rows), all_path, compression="zstd")
    train_path = output_root / "train" / "train.jsonl"
    validation_path = output_root / "validation" / "train.jsonl"
    padded_validation_path = output_root / f"validation-cp2-{validation_size}" / "train.jsonl"
    write_jsonl(train_path, train_rows)
    write_jsonl(validation_path, validation_rows)
    write_jsonl(padded_validation_path, padded_validation)

    task_split_path = output_root / "task-split.json"
    task_split_path.write_text(
        json.dumps(
            {
                "parent": str(source_root / "task-split.json"),
                "train_tasks": sorted(train_tasks),
                "validation_tasks": sorted(validation_tasks),
            },
            indent=2,
        )
        + "\n"
    )
    rendered_lengths_path = output_root / "rendered-lengths.jsonl"
    write_jsonl(
        rendered_lengths_path,
        sorted(selected_lengths, key=lambda item: (item["split"], item["index"])),
    )

    validation_manifest_path = output_root / f"validation-cp2-{validation_size}-manifest.json"
    validation_manifest_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "purpose": "CP2 fixed-stack validation requires one row for each data rank",
                "source": str(validation_path),
                "unique_rows": len(validation_rows),
                "rows": len(padded_validation),
                "padding_policy": "repeat every row uniformly, then repeat the shortest trainable rows",
                "duplicates": duplicates,
                "train_jsonl_sha256": sha256_file(padded_validation_path),
            },
            indent=2,
        )
        + "\n"
    )

    manifest = {
        "format_version": 1,
        "dataset_id": "pass-only-matched-task-split-max192000-v1",
        "parent": {
            "path": str(source_root),
            "manifest_sha256": sha256_file(source_manifest_path),
            "dataset_id": source_manifest["dataset_id"],
        },
        "selection": {
            "policy": "retain byte-equivalent processed rows whose reward is exactly one",
            "max_rendered_tokens": 192_000,
            "task_split": "preserve the parent all-outcomes train/validation task assignment",
            "truncate": False,
        },
        "counts": {
            "source_rows": len(source_train) + len(source_validation),
            "rows": len(train_rows) + len(validation_rows),
            "train_rows": len(train_rows),
            "validation_rows": len(validation_rows),
            "validation_cp2_rows": len(padded_validation),
            "train_tasks": len(train_tasks),
            "validation_tasks": len(validation_tasks),
        },
        "artifacts": {
            "all.parquet": artifact(all_path, rows=len(train_rows) + len(validation_rows)),
            "train/train.jsonl": artifact(train_path, rows=len(train_rows)),
            "validation/train.jsonl": artifact(validation_path, rows=len(validation_rows)),
            f"validation-cp2-{validation_size}/train.jsonl": artifact(
                padded_validation_path, rows=len(padded_validation)
            ),
            "task-split.json": artifact(task_split_path),
            "rendered-lengths.jsonl": artifact(rendered_lengths_path, rows=len(selected_lengths)),
            validation_manifest_path.name: artifact(validation_manifest_path),
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    args = parse_args()
    if args.output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.output_root}")
    if args.validation_size < 1:
        raise ValueError("validation-size must be positive")

    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{args.output_root.name}.",
            dir=args.output_root.parent,
        )
    )
    completed = False
    try:
        manifest = materialize(args.source_root, temporary, args.validation_size)
        os.replace(temporary, args.output_root)
        completed = True
    finally:
        if not completed and temporary.exists():
            shutil.rmtree(temporary)

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
