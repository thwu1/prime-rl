#!/usr/bin/env python3
"""Materialize an immutable SFT export whose rows fit the target renderer limit.

The source export is treated as immutable. Output contains byte-identical rows
except that rows whose exact target rendering exceeds the configured sequence
limit are omitted. Only aggregate counts and hashes are printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from renderers import Nemotron3RendererConfig, create_renderer

from prime_rl.trainer.sft import export_preflight as preflight


class FilterError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SplitSummary:
    source_rows: int
    retained_rows: int
    rejected_rows: int
    source_tasks: int
    retained_tasks: int
    max_retained_tokens: int
    min_rejected_tokens: int | None
    max_rejected_tokens: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "source_rows": self.source_rows,
            "retained_rows": self.retained_rows,
            "rejected_rows": self.rejected_rows,
            "source_tasks": self.source_tasks,
            "retained_tasks": self.retained_tasks,
            "max_retained_tokens": self.max_retained_tokens,
            "min_rejected_tokens": self.min_rejected_tokens,
            "max_rejected_tokens": self.max_rejected_tokens,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, int | str]:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise FilterError("output_artifact_invalid")
    return {"bytes": metadata.st_size, "sha256": _sha256_file(path)}


def _write_private(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _copy_private(source: Path, destination: Path) -> None:
    source_handle, before = preflight._open_regular(source, "source_artifact_invalid", required_mode=0o600)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with source_handle, os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            shutil.copyfileobj(source_handle, output, 1 << 20)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(source_handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not preflight._same_file(before, after):
        raise FilterError("source_artifact_changed")


def _filter_split(
    *,
    source: Path,
    destination: Path,
    expected: preflight.FileArtifact,
    tokenizer: Any,
    renderer: Any,
    max_tokens: int,
) -> SplitSummary:
    source_handle, before = preflight._open_regular(source, "source_split_invalid", required_mode=0o600)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    source_digest = hashlib.sha256()
    source_size = 0
    source_rows = 0
    retained_rows = 0
    rejected_rows = 0
    source_tasks: set[str] = set()
    retained_tasks: set[str] = set()
    max_retained_tokens = 0
    min_rejected_tokens: int | None = None
    max_rejected_tokens: int | None = None
    try:
        with source_handle, os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            while raw := source_handle.readline(preflight.MAX_JSONL_ROW_BYTES + 1):
                if len(raw) > preflight.MAX_JSONL_ROW_BYTES or not raw.endswith(b"\n") or not raw.strip():
                    raise FilterError("source_split_invalid")
                source_digest.update(raw)
                source_size += len(raw)
                source_rows += 1
                row = preflight._parse_json_object(raw, "source_row_invalid")
                task_id = row.get("task_id")
                target_index = row.get("target_assistant_message_index")
                if not preflight._valid_sha256(task_id) or not preflight._is_plain_int(target_index):
                    raise FilterError("source_row_invalid")
                messages, _ = preflight._validate_messages(row.get("messages"), target_index)
                tools = preflight._validate_tools(row.get("tools"))
                rendered = renderer.render(preflight._prepare_messages(messages), tools=tools)
                rendered_tokens = len(rendered.token_ids)
                if (
                    not rendered_tokens
                    or rendered_tokens != len(rendered.message_indices)
                    or rendered_tokens != len(rendered.sampled_mask)
                ):
                    raise FilterError("source_render_contract_invalid")
                source_tasks.add(task_id)
                if rendered_tokens > max_tokens:
                    rejected_rows += 1
                    min_rejected_tokens = (
                        rendered_tokens
                        if min_rejected_tokens is None
                        else min(min_rejected_tokens, rendered_tokens)
                    )
                    max_rejected_tokens = (
                        rendered_tokens
                        if max_rejected_tokens is None
                        else max(max_rejected_tokens, rendered_tokens)
                    )
                    continue
                output.write(raw)
                retained_rows += 1
                retained_tasks.add(task_id)
                max_retained_tokens = max(max_retained_tokens, rendered_tokens)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(source_handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not preflight._same_file(before, after)
        or preflight.FileArtifact(source_size, source_digest.hexdigest()) != expected
    ):
        raise FilterError("source_split_changed")
    if not source_tasks or retained_tasks != source_tasks:
        raise FilterError("task_coverage_lost")
    return SplitSummary(
        source_rows=source_rows,
        retained_rows=retained_rows,
        rejected_rows=rejected_rows,
        source_tasks=len(source_tasks),
        retained_tasks=len(retained_tasks),
        max_retained_tokens=max_retained_tokens,
        min_rejected_tokens=min_rejected_tokens,
        max_rejected_tokens=max_rejected_tokens,
    )


def materialize(
    *,
    source_root: Path,
    source_manifest_sha256: str,
    output_root: Path,
    project_dir: Path,
    expected_project_revision: str,
    tokenizer_snapshot: Path,
    tokenizer_sha256: str,
) -> dict[str, Any]:
    if (
        not output_root.is_absolute()
        or output_root != Path(os.path.normpath(output_root))
        or os.path.lexists(output_root)
    ):
        raise FilterError("output_path_invalid")
    output_parent = preflight._canonical_directory(output_root.parent, "output_parent_invalid")
    source = preflight._canonical_directory(source_root, "source_root_invalid")
    if output_root.is_relative_to(source) or source.is_relative_to(output_root):
        raise FilterError("path_boundaries_overlap")

    binding = preflight._load_export_binding(source, source_manifest_sha256)
    code = preflight._repository_provenance(project_dir, expected_project_revision)
    snapshot = preflight._bind_tokenizer_snapshot(tokenizer_snapshot, tokenizer_sha256)
    tokenizer = preflight._load_render_tokenizer(snapshot)
    renderer_contract = preflight.EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]
    renderer = create_renderer(
        tokenizer,
        Nemotron3RendererConfig.model_validate(renderer_contract["config"]),
    )
    max_tokens = preflight.EXPECTED_TARGET_RENDERING_CONTRACT["max_sequence_tokens"]

    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_parent))
    os.chmod(staging, 0o700)
    published = False
    try:
        for split in ("train", "validation"):
            (staging / split).mkdir(mode=0o700)
        summaries = {
            split: _filter_split(
                source=source / split / "train.jsonl",
                destination=staging / split / "train.jsonl",
                expected=binding.artifacts[f"{split}/train.jsonl"],
                tokenizer=tokenizer,
                renderer=renderer,
                max_tokens=max_tokens,
            )
            for split in ("train", "validation")
        }
        if sum(item.rejected_rows for item in summaries.values()) < 1:
            raise FilterError("no_overlength_rows")

        for name in sorted(binding.artifacts):
            if name in {"train/train.jsonl", "validation/train.jsonl"}:
                continue
            destination = staging / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _copy_private(source / name, destination)
            if _artifact(destination) != binding.artifacts[name].as_dict():
                raise FilterError("copied_artifact_mismatch")
        certificate_name = "source-continuation-pass-only-certificate.json"
        if (source / certificate_name).is_file():
            _copy_private(source / certificate_name, staging / certificate_name)

        manifest = dict(binding.manifest_value)
        counts = dict(manifest.get("counts", {}))
        if (
            counts.get("emitted_rows") != sum(item.source_rows for item in summaries.values())
            or counts.get("train_rows") != summaries["train"].source_rows
            or counts.get("validation_rows") != summaries["validation"].source_rows
            or counts.get("train_traces") != summaries["train"].source_tasks
            or counts.get("validation_traces") != summaries["validation"].source_tasks
            or counts.get("selected_sft_tasks") != sum(item.source_tasks for item in summaries.values())
        ):
            raise FilterError("source_count_mismatch")
        counts["emitted_rows"] = sum(item.retained_rows for item in summaries.values())
        counts["train_rows"] = summaries["train"].retained_rows
        counts["validation_rows"] = summaries["validation"].retained_rows
        manifest["counts"] = counts
        artifacts = dict(manifest["artifacts"])
        artifacts["train/train.jsonl"] = _artifact(staging / "train" / "train.jsonl")
        artifacts["validation/train.jsonl"] = _artifact(staging / "validation" / "train.jsonl")
        manifest["artifacts"] = artifacts
        manifest["render_length_filter"] = {
            "code": {
                "file_sha256": _sha256_file(Path(__file__).resolve(strict=True)),
                "project_revision": expected_project_revision,
                "repository": code,
            },
            "kind": "exact-target-render-length-filter",
            "max_sequence_tokens": max_tokens,
            "policy": "omit-only-rows-whose-exact-target-rendering-exceeds-max-sequence-tokens",
            "schema_version": 1,
            "source_manifest_sha256": source_manifest_sha256,
            "splits": {name: item.as_dict() for name, item in summaries.items()},
            "task_coverage_preserved": True,
            "tokenizer_snapshot": snapshot.as_dict() if snapshot is not None else None,
        }
        manifest_body = (
            json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode() + b"\n"
        )
        _write_private(staging / "manifest.json", manifest_body)

        preflight._assert_tokenizer_snapshot(snapshot)
        if preflight._repository_provenance(project_dir, expected_project_revision) != code:
            raise FilterError("project_changed_during_filter")
        rebound = preflight._load_export_binding(source, source_manifest_sha256)
        if rebound.manifest != binding.manifest or rebound.artifacts != binding.artifacts:
            raise FilterError("source_changed_during_filter")
        os.replace(staging, output_root)
        published = True
        result = {
            "manifest_sha256": hashlib.sha256(manifest_body).hexdigest(),
            "output": str(output_root),
            "rejected_rows": sum(item.rejected_rows for item in summaries.values()),
            "retained_rows": sum(item.retained_rows for item in summaries.values()),
            "splits": {name: item.as_dict() for name, item in summaries.items()},
            "state": "materialized",
        }
        return result
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument("--tokenizer-snapshot", type=Path, required=True)
    parser.add_argument("--tokenizer-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        result = materialize(
            source_root=args.source_root,
            source_manifest_sha256=args.source_manifest_sha256,
            output_root=args.output_root,
            project_dir=args.project_dir,
            expected_project_revision=args.expected_project_revision,
            tokenizer_snapshot=args.tokenizer_snapshot,
            tokenizer_sha256=args.tokenizer_sha256,
        )
    except (FilterError, preflight.SFTPreflightError) as error:
        print(json.dumps({"code": str(error), "state": "error"}, sort_keys=True))
        return 2
    except Exception as error:
        frames = [
            {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
        print(
            json.dumps(
                {
                    "code": "internal_error",
                    "exception_type": type(error).__name__,
                    "frames": frames,
                    "state": "error",
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
