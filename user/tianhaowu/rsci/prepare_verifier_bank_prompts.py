#!/usr/bin/env python3
"""Build a deterministic, held-out-clean verifier-bank prompt view."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DATA_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k")
DEFAULT_SOURCE_ROOT = DEFAULT_DATA_ROOT / "sources"
DEFAULT_UPSTREAM_MANIFEST = DEFAULT_DATA_ROOT / "dataset_manifest.json"
DEFAULT_OUTPUT_DIR = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/frozen-base-op10-12-op15-40-r128-v1/prompts"
)
DEFAULT_HELDOUT_RANGES = (
    (
        10,
        20,
        Path(
            "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
            "datasets--Interplay-LM-Reasoning--composition/snapshots/"
            "a09d5c14c02bfa339143fb00a93274d1a84aa31d/val"
        ),
    ),
    (21, 30, Path("/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/generated-eval-op21-30-v1")),
    (31, 40, Path("/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/generated-eval-op31-40-v1")),
)
DEFAULT_OPERATIONS = (10, 11, 12, *range(15, 41))
DEFAULT_PROMPTS_PER_OPERATION = 1000
DEFAULT_SELECTION_SEED = 20260807
EXPECTED_CONTEXTS = ("movie", "teacher", "zoo")
EXPECTED_MODES = ("forwardreverse", "normalforward")
EXPECTED_CELLS = tuple((context, mode) for context in EXPECTED_CONTEXTS for mode in EXPECTED_MODES)
MANIFEST_NAME = "prompt_view_manifest.json"
SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--upstream-manifest", type=Path, default=DEFAULT_UPSTREAM_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--operations", type=int, nargs="+", default=list(DEFAULT_OPERATIONS))
    parser.add_argument("--prompts-per-operation", type=int, default=DEFAULT_PROMPTS_PER_OPERATION)
    parser.add_argument("--selection-seed", type=int, default=DEFAULT_SELECTION_SEED)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def stable_digest(*parts: object) -> str:
    material = "\0".join(str(part) for part in parts).encode()
    return hashlib.sha256(material).hexdigest()


def prompt_text(row: dict[str, Any]) -> str:
    prompt = row.get("prompt")
    if prompt is None:
        prompt = f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Prompt row {row.get('id')!r} has no usable prompt")
    return prompt


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"Blank JSONL record at {path}:{line_number}")
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSONL record is not an object at {path}:{line_number}")
        rows.append(row)
    if not rows:
        raise ValueError(f"JSONL file is empty: {path}")
    return rows


def upstream_train_sources(path: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        raise ValueError(f"Upstream manifest has no sources list: {path}")
    indexed: dict[int, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict) or source.get("split") != "train":
            continue
        operation = source.get("operation")
        if isinstance(operation, bool) or not isinstance(operation, int) or operation < 1:
            raise ValueError(f"Upstream train source has an invalid operation: {source!r}")
        if operation in indexed:
            raise ValueError(f"Upstream manifest has duplicate OP{operation} train sources")
        if not isinstance(source.get("data"), str) or not source["data"]:
            raise ValueError(f"Upstream OP{operation} train source has no data path")
        if isinstance(source.get("rows"), bool) or not isinstance(source.get("rows"), int):
            raise ValueError(f"Upstream OP{operation} train source has no integer row count")
        data_sha256 = source.get("data_sha256")
        if not isinstance(data_sha256, str) or len(data_sha256) != 64:
            raise ValueError(f"Upstream OP{operation} train source has no SHA-256 identity")
        indexed[operation] = source
    return indexed


def heldout_path(operation: int, heldout_ranges: tuple[tuple[int, int, Path], ...]) -> Path:
    matches = [root for minimum, maximum, root in heldout_ranges if minimum <= operation <= maximum]
    if len(matches) != 1:
        raise ValueError(f"Operation {operation} has {len(matches)} held-out sources; expected exactly one")
    return matches[0] / f"op{operation}-200.jsonl"


def cell_quotas(operation: int, count: int, seed: int) -> dict[tuple[str, str], int]:
    if count < len(EXPECTED_CELLS):
        raise ValueError(f"prompts_per_operation must be at least {len(EXPECTED_CELLS)}")
    base, remainder = divmod(count, len(EXPECTED_CELLS))
    rotation = int(stable_digest("quota", seed, operation)[:16], 16) % len(EXPECTED_CELLS)
    extra = {(rotation + offset) % len(EXPECTED_CELLS) for offset in range(remainder)}
    return {cell: base + int(index in extra) for index, cell in enumerate(EXPECTED_CELLS)}


def select_rows(
    rows: list[dict[str, Any]],
    *,
    operation: int,
    count: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    ids = set()
    prompts = set()
    for index, row in enumerate(rows):
        required = {"id", "op", "context", "mode", "problem", "question", "solution", "template"}
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"OP{operation} source row {index} is missing fields: {missing}")
        if int(row["op"]) != operation:
            raise ValueError(f"OP{operation} source row {index} has op={row['op']}")
        sample_id = str(row["id"])
        prompt = prompt_text(row)
        if sample_id in ids:
            raise ValueError(f"OP{operation} source contains duplicate id: {sample_id}")
        if prompt in prompts:
            raise ValueError(f"OP{operation} source contains duplicate prompt: {sample_id}")
        ids.add(sample_id)
        prompts.add(prompt)
        cell = (str(row["context"]), str(row["mode"]))
        if cell not in EXPECTED_CELLS:
            raise ValueError(f"OP{operation} source row {index} has unexpected cell: {cell}")
        cells[cell].append(row)

    if set(cells) != set(EXPECTED_CELLS):
        raise ValueError(f"OP{operation} source cells are incomplete: {sorted(cells)}")
    if count > len(rows):
        raise ValueError(f"OP{operation} has {len(rows)} source rows, fewer than requested count {count}")
    selected = []
    if count == len(rows):
        selected.extend(rows)
    else:
        quotas = cell_quotas(operation, count, seed)
        for cell in EXPECTED_CELLS:
            ranked = sorted(
                cells[cell],
                key=lambda row: (
                    stable_digest("select", seed, operation, cell[0], cell[1], row["id"]),
                    str(row["id"]),
                ),
            )
            quota = quotas[cell]
            if len(ranked) < quota:
                raise ValueError(f"OP{operation} cell {cell} has {len(ranked)} rows, but quota is {quota}")
            selected.extend(ranked[:quota])

    selected.sort(
        key=lambda row: (
            stable_digest("order", seed, operation, row["id"]),
            str(row["id"]),
        )
    )
    selected_counts = Counter(f"{row['context']}/{row['mode']}" for row in selected)
    source_counts = Counter(f"{row['context']}/{row['mode']}" for row in rows)
    if len(selected) != count or max(selected_counts.values()) - min(selected_counts.values()) > 1:
        raise RuntimeError(f"OP{operation} balanced selection invariant failed")
    return selected, dict(sorted(source_counts.items())), dict(sorted(selected_counts.items()))


def jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n" for row in rows).encode()


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(content)
    partial.replace(path)


def write_json_atomic(path: Path, payload: object) -> None:
    content = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    write_bytes_atomic(path, content)


def build_prompt_view(
    *,
    source_root: Path,
    upstream_manifest: Path,
    output_dir: Path,
    operations: tuple[int, ...],
    prompts_per_operation: int,
    selection_seed: int,
    heldout_ranges: tuple[tuple[int, int, Path], ...] = DEFAULT_HELDOUT_RANGES,
    validate_only: bool = False,
) -> dict[str, Any]:
    if not operations or len(operations) != len(set(operations)) or any(operation < 1 for operation in operations):
        raise ValueError("operations must be unique positive integers")
    if prompts_per_operation < 1:
        raise ValueError("prompts_per_operation must be positive")
    if isinstance(selection_seed, bool) or not isinstance(selection_seed, int) or selection_seed < 0:
        raise ValueError("selection_seed must be a non-negative integer")
    if not upstream_manifest.is_file():
        raise FileNotFoundError(upstream_manifest)
    upstream_sources = upstream_train_sources(upstream_manifest)
    missing_upstream = sorted(set(operations) - set(upstream_sources))
    if missing_upstream:
        raise ValueError(f"Upstream manifest has no train sources for operations: {missing_upstream}")

    per_operation: dict[str, Any] = {}
    expected_files: dict[Path, bytes] = {}
    all_selected_ids = set()
    all_selected_prompts = set()
    all_heldout_ids = set()
    all_heldout_prompts = set()
    for operation in operations:
        source_path = source_root / f"op{operation}" / "train.jsonl"
        source_rows = read_jsonl(source_path)
        upstream_source = upstream_sources[operation]
        if Path(upstream_source["data"]).expanduser().resolve() != source_path.resolve():
            raise ValueError(f"OP{operation} source path differs from the upstream manifest")
        source_sha256 = file_sha256(source_path)
        if upstream_source["rows"] != len(source_rows) or upstream_source["data_sha256"] != source_sha256:
            raise ValueError(f"OP{operation} source identity differs from the upstream manifest")
        selected, source_counts, selected_counts = select_rows(
            source_rows,
            operation=operation,
            count=prompts_per_operation,
            seed=selection_seed,
        )
        output_path = output_dir / f"op{operation}-{prompts_per_operation}.jsonl"
        content = jsonl_bytes(selected)
        expected_files[output_path] = content

        heldout = heldout_path(operation, heldout_ranges)
        heldout_rows = read_jsonl(heldout)
        heldout_ids = {str(row["id"]) for row in heldout_rows}
        heldout_prompts = {prompt_text(row) for row in heldout_rows}
        selected_ids = {str(row["id"]) for row in selected}
        selected_prompts = {prompt_text(row) for row in selected}
        id_overlap = selected_ids & heldout_ids
        prompt_overlap = selected_prompts & heldout_prompts
        if id_overlap or prompt_overlap:
            raise ValueError(
                f"OP{operation} selected/held-out overlap: ids={len(id_overlap)}, prompts={len(prompt_overlap)}"
            )
        duplicate_ids = all_selected_ids & selected_ids
        duplicate_prompts = all_selected_prompts & selected_prompts
        if duplicate_ids or duplicate_prompts:
            raise ValueError(
                f"OP{operation} duplicates earlier selected rows: ids={len(duplicate_ids)}, "
                f"prompts={len(duplicate_prompts)}"
            )
        all_selected_ids.update(selected_ids)
        all_selected_prompts.update(selected_prompts)
        all_heldout_ids.update(heldout_ids)
        all_heldout_prompts.update(heldout_prompts)

        per_operation[str(operation)] = {
            "source": {
                "path": str(source_path.resolve()),
                "rows": len(source_rows),
                "sha256": source_sha256,
                "counts_by_cell": source_counts,
                "upstream_manifest_record_sha256": canonical_json_sha256(upstream_source),
            },
            "selection": {
                "rows": len(selected),
                "counts_by_cell": selected_counts,
                "prompt_sequence_sha256": canonical_json_sha256(
                    [{"id": str(row["id"]), "prompt": prompt_text(row)} for row in selected]
                ),
            },
            "output": {
                "path": str(output_path.resolve()),
                "rows": len(selected),
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            "heldout": {
                "path": str(heldout.resolve()),
                "rows": len(heldout_rows),
                "sha256": file_sha256(heldout),
                "id_overlap": 0,
                "prompt_overlap": 0,
            },
        }

    if all_selected_ids & all_heldout_ids or all_selected_prompts & all_heldout_prompts:
        raise RuntimeError("Global selected/held-out overlap invariant failed")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol": {
            "operations": list(operations),
            "prompts_per_operation": prompts_per_operation,
            "selection_seed": selection_seed,
            "cells": [list(cell) for cell in EXPECTED_CELLS],
            "quota_rule": "balanced floor allocation with operation-rotated remainder",
            "selection_rule": "lowest SHA-256 rank within each operation/context/mode cell",
            "full_source_rule": "when the requested count equals the source count, every row is selected",
            "ordering_rule": "SHA-256 rank over selected sample ids",
        },
        "upstream_manifest": {
            "path": str(upstream_manifest.resolve()),
            "size_bytes": upstream_manifest.stat().st_size,
            "sha256": file_sha256(upstream_manifest),
        },
        "counts": {
            "operations": len(operations),
            "selected_prompts": len(all_selected_ids),
            "unique_selected_ids": len(all_selected_ids),
            "unique_selected_prompts": len(all_selected_prompts),
            "heldout_id_overlap": 0,
            "heldout_prompt_overlap": 0,
        },
        "per_operation": per_operation,
        "implementation": {
            "path": "user/tianhaowu/rsci/prepare_verifier_bank_prompts.py",
            "sha256": file_sha256(Path(__file__)),
        },
    }
    manifest_path = output_dir / MANIFEST_NAME
    manifest_content = (
        json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode()

    if validate_only and not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    for path, content in expected_files.items():
        if path.is_file():
            if path.read_bytes() != content:
                raise ValueError(f"Existing prompt-view shard differs from deterministic selection: {path}")
        elif validate_only:
            raise FileNotFoundError(path)
        else:
            write_bytes_atomic(path, content)
    if manifest_path.is_file():
        if manifest_path.read_bytes() != manifest_content:
            raise ValueError(f"Existing prompt-view manifest differs from deterministic audit: {manifest_path}")
    elif not validate_only:
        write_bytes_atomic(manifest_path, manifest_content)
    return manifest


def main() -> None:
    args = parse_args()
    manifest = build_prompt_view(
        source_root=args.source_root.expanduser().resolve(),
        upstream_manifest=args.upstream_manifest.expanduser().resolve(),
        output_dir=args.output_dir.expanduser().resolve(),
        operations=tuple(args.operations),
        prompts_per_operation=args.prompts_per_operation,
        selection_seed=args.selection_seed,
        validate_only=args.validate_only,
    )
    print(json.dumps(manifest["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
