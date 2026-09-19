#!/usr/bin/env python3
"""Build a confidential oracle-repair canary manifest from one completed run.

Stdout and the receipt contain aggregate counts and hashes only. Task slugs are
written exclusively to the mode-0600 task file.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from export_oracle_tasks import (
    MAX_JSON_BYTES,
    ORACLE_REASONS,
    PromotionError,
    _audit_source_wheel_artifacts,
    _canonical_json_file,
    _canonical_json_sha256,
    _ordered_tasks_sha256,
    _read_bytes,
    _reject_json_constant,
    _sha256,
    _source_wheel_recovery,
    _unique_json_object,
)

DEFAULT_CONTROL_COUNT = 20
DEFAULT_SEED = "oracle-dependency-overlay-v1"
DEFAULT_EXPECTED_TOTAL = 2_538
RECEIPT_SCHEMA_VERSION = 1
RECEIPT_ARTIFACT_TYPE = "terminal_bench_vmvm_oracle_repair_canary_receipt"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RESULT_KEYS = {
    "attempts",
    "elapsed_sec",
    "error",
    "error_type",
    "image",
    "index",
    "infrastructure_failures",
    "name",
    "oracle_network_semantics",
    "reason",
    "run_identity_sha256",
    "slug",
    "valid",
}
SOURCE_WHEEL_RESULT_KEYS = RESULT_KEYS | {"source_wheel_attestation_sha256s"}
SUMMARY_KEYS = {
    "completed",
    "finished_at",
    "oracle_network_semantics",
    "pass_rate",
    "passed",
    "reasons",
    "run_identity_sha256",
    "selected",
}
SOURCE_WHEEL_SUMMARY_KEYS = SUMMARY_KEYS | {"source_wheel_attestation_sha256"}


class CanaryManifestError(ValueError):
    """A source or publication invariant failed without exposing row data."""


def _read_limited(path: Path, *, error: str) -> bytes:
    try:
        return _read_bytes(path, limit=MAX_JSON_BYTES, error=error)
    except PromotionError as cause:
        raise CanaryManifestError(error) from cause


def _strict_json(raw: bytes, *, error: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as cause:
        raise CanaryManifestError(error) from cause
    if not isinstance(value, dict):
        raise CanaryManifestError(error)
    return value


def _source_artifact(oracle_dir: Path, name: str, *, error: str) -> tuple[Path, bytes]:
    path = oracle_dir / name
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise CanaryManifestError(error) from cause
    if not stat.S_ISREG(metadata.st_mode) or resolved.parent != oracle_dir:
        raise CanaryManifestError(error)
    return resolved, _read_limited(resolved, error=error)


def _run_identity(oracle_dir: Path, expected_total: int) -> tuple[dict[str, Any], str, str, Path, bytes]:
    path, raw = _source_artifact(oracle_dir, "run_identity.json", error="oracle_run_identity_invalid")
    wrapper = _strict_json(raw, error="oracle_run_identity_invalid")
    if set(wrapper) != {"identity", "run_identity_sha256", "schema_version"}:
        raise CanaryManifestError("oracle_run_identity_invalid")
    if type(wrapper.get("schema_version")) is not int or wrapper["schema_version"] != 1:
        raise CanaryManifestError("oracle_run_identity_invalid")
    identity = wrapper.get("identity")
    identity_sha256 = wrapper.get("run_identity_sha256")
    if (
        not isinstance(identity, dict)
        or type(identity.get("schema_version")) is not int
        or identity["schema_version"] != 1
        or not isinstance(identity_sha256, str)
        or SHA256_RE.fullmatch(identity_sha256) is None
        or _canonical_json_sha256(identity) != identity_sha256
    ):
        raise CanaryManifestError("oracle_run_identity_invalid")
    try:
        _source_wheel_recovery(identity)
    except PromotionError as cause:
        raise CanaryManifestError("oracle_run_identity_invalid") from cause
    selection = identity.get("selection")
    if not isinstance(selection, dict) or set(selection) != {
        "count",
        "limit",
        "offset",
        "ordered_task_slugs_sha256",
        "task_file",
    }:
        raise CanaryManifestError("oracle_run_identity_invalid")
    task_file = selection.get("task_file")
    if (
        type(selection.get("count")) is not int
        or selection["count"] != expected_total
        or type(selection.get("offset")) is not int
        or selection["offset"] != 0
        or selection.get("limit") is not None
        or not isinstance(selection.get("ordered_task_slugs_sha256"), str)
        or SHA256_RE.fullmatch(selection["ordered_task_slugs_sha256"]) is None
        or task_file != {"path": None, "sha256": None}
    ):
        raise CanaryManifestError("oracle_universe_incomplete")
    network_semantics = identity.get("network_semantics")
    if not isinstance(network_semantics, dict):
        raise CanaryManifestError("oracle_run_identity_invalid")
    return identity, identity_sha256, _sha256(raw), path, raw


def _valid_slug(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and value not in {".", ".."}
        and not value.startswith("#")
        and "/" not in value
        and "\\" not in value
        and all(ord(character) >= 0x20 and ord(character) != 0x7F for character in value)
    )


def _results(
    oracle_dir: Path,
    *,
    expected_total: int,
    identity_sha256: str,
    network_semantics: dict[str, Any],
    ordered_slugs_sha256: str,
    source_wheel_attestation_sha256s: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], Counter[str], str, Path, bytes]:
    path, raw = _source_artifact(oracle_dir, "results.jsonl", error="oracle_results_invalid")
    if not raw or not raw.endswith(b"\n"):
        raise CanaryManifestError("oracle_results_invalid")
    lines = raw.splitlines()
    if len(lines) != expected_total or any(not line for line in lines):
        raise CanaryManifestError("oracle_universe_incomplete")
    rows: list[dict[str, Any]] = []
    slugs: list[str] = []
    referenced_source_attestations: set[str] = set()
    reasons: Counter[str] = Counter()
    for expected_index, line in enumerate(lines):
        row = _strict_json(line, error="oracle_result_schema_invalid")
        keys = set(row)
        expected_keys = RESULT_KEYS if source_wheel_attestation_sha256s is None else SOURCE_WHEEL_RESULT_KEYS
        if keys not in (expected_keys, expected_keys | {"last_attempt"}):
            raise CanaryManifestError("oracle_result_schema_invalid")
        valid = row.get("valid")
        reason = row.get("reason")
        elapsed_sec = row.get("elapsed_sec")
        attempts = row.get("attempts")
        infrastructure_failures = row.get("infrastructure_failures")
        if (
            type(row.get("index")) is not int
            or row["index"] != expected_index
            or not _valid_slug(row.get("slug"))
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or not isinstance(row.get("image"), str)
            or not row["image"]
            or not isinstance(valid, bool)
            or not isinstance(reason, str)
            or reason not in ORACLE_REASONS
            or (valid and reason != "valid")
            or (not valid and reason == "valid")
            or not (row.get("error") is None or isinstance(row["error"], str))
            or not (row.get("error_type") is None or isinstance(row["error_type"], str))
            or isinstance(elapsed_sec, bool)
            or not isinstance(elapsed_sec, (int, float))
            or not math.isfinite(elapsed_sec)
            or elapsed_sec < 0
            or type(attempts) is not int
            or attempts < 1
            or not isinstance(infrastructure_failures, list)
            or not all(isinstance(failure, dict) for failure in infrastructure_failures)
            or ("last_attempt" in row and not isinstance(row["last_attempt"], dict))
            or row.get("oracle_network_semantics") != network_semantics
            or row.get("run_identity_sha256") != identity_sha256
            or (
                source_wheel_attestation_sha256s is not None
                and (
                    not isinstance(row.get("source_wheel_attestation_sha256s"), list)
                    or not all(isinstance(digest, str) for digest in row["source_wheel_attestation_sha256s"])
                    or row["source_wheel_attestation_sha256s"] != sorted(set(row["source_wheel_attestation_sha256s"]))
                    or not all(
                        digest in source_wheel_attestation_sha256s for digest in row["source_wheel_attestation_sha256s"]
                    )
                )
            )
        ):
            raise CanaryManifestError("oracle_result_schema_invalid")
        rows.append(row)
        if source_wheel_attestation_sha256s is not None:
            referenced_source_attestations.update(row["source_wheel_attestation_sha256s"])
        slugs.append(row["slug"])
        reasons[reason] += 1
    if len(slugs) != len(set(slugs)):
        raise CanaryManifestError("oracle_result_duplicates")
    if _ordered_tasks_sha256(slugs) != ordered_slugs_sha256:
        raise CanaryManifestError("oracle_result_universe_mismatch")
    if source_wheel_attestation_sha256s is not None and (
        referenced_source_attestations != source_wheel_attestation_sha256s
    ):
        raise CanaryManifestError("oracle_source_wheel_recovery_not_exercised")
    return rows, reasons, _sha256(raw), path, raw


def _summary(
    oracle_dir: Path,
    *,
    expected_total: int,
    identity_sha256: str,
    network_semantics: dict[str, Any],
    reasons: Counter[str],
    passed: int,
    source_wheel_attestation_sha256: str | None = None,
) -> tuple[str, Path, bytes]:
    path, raw = _source_artifact(oracle_dir, "summary.json", error="oracle_summary_invalid")
    summary = _strict_json(raw, error="oracle_summary_invalid")
    pass_rate = summary.get("pass_rate")
    finished_at = summary.get("finished_at")
    if (
        set(summary) != (SUMMARY_KEYS if source_wheel_attestation_sha256 is None else SOURCE_WHEEL_SUMMARY_KEYS)
        or type(summary.get("selected")) is not int
        or summary["selected"] != expected_total
        or type(summary.get("completed")) is not int
        or summary["completed"] != expected_total
        or type(summary.get("passed")) is not int
        or summary["passed"] != passed
        or isinstance(pass_rate, bool)
        or not isinstance(pass_rate, (int, float))
        or not math.isfinite(pass_rate)
        or not math.isclose(pass_rate, passed / expected_total, rel_tol=0.0, abs_tol=1e-15)
        or summary.get("reasons") != dict(reasons)
        or summary.get("oracle_network_semantics") != network_semantics
        or summary.get("run_identity_sha256") != identity_sha256
        or (
            source_wheel_attestation_sha256 is not None
            and summary.get("source_wheel_attestation_sha256") != source_wheel_attestation_sha256
        )
        or isinstance(finished_at, bool)
        or not isinstance(finished_at, (int, float))
        or not math.isfinite(finished_at)
        or finished_at <= 0
    ):
        raise CanaryManifestError("oracle_summary_invalid")
    return _sha256(raw), path, raw


def _statuses(oracle_dir: Path, rows: list[dict[str, Any]]) -> int:
    directory = oracle_dir / "tasks"
    try:
        metadata = directory.lstat()
        resolved = directory.resolve(strict=True)
        paths = sorted(resolved.iterdir())
    except (OSError, RuntimeError) as cause:
        raise CanaryManifestError("oracle_statuses_invalid") from cause
    if not stat.S_ISDIR(metadata.st_mode) or resolved.parent != oracle_dir or len(paths) != len(rows):
        raise CanaryManifestError("oracle_statuses_invalid")
    expected = {row["slug"]: row for row in rows}
    observed: set[str] = set()
    for path in paths:
        try:
            path_metadata = path.lstat()
        except OSError as cause:
            raise CanaryManifestError("oracle_statuses_invalid") from cause
        if not stat.S_ISREG(path_metadata.st_mode) or path.suffix != ".json":
            raise CanaryManifestError("oracle_statuses_invalid")
        status = _strict_json(
            _read_limited(path, error="oracle_statuses_invalid"),
            error="oracle_statuses_invalid",
        )
        slug = status.get("slug")
        if not isinstance(slug, str) or slug in observed or path.name != f"{slug}.json":
            raise CanaryManifestError("oracle_statuses_invalid")
        if expected.get(slug) != status:
            raise CanaryManifestError("oracle_statuses_invalid")
        observed.add(slug)
    if observed != set(expected):
        raise CanaryManifestError("oracle_statuses_invalid")
    return len(observed)


@contextmanager
def _hold_oracle_lock(oracle_dir: Path) -> Iterator[None]:
    path = oracle_dir / ".writer.lock"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as cause:
        raise CanaryManifestError("oracle_writer_lock_invalid") from cause
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CanaryManifestError("oracle_writer_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as cause:
            raise CanaryManifestError("oracle_writer_active") from cause
        yield
    finally:
        os.close(descriptor)


def _target_path(path: Path) -> Path:
    try:
        parent = path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise CanaryManifestError("output_parent_invalid") from cause
    if not parent.is_dir() or not path.name or path.name in {".", ".."}:
        raise CanaryManifestError("output_parent_invalid")
    return parent / path.name


def _existing_output(path: Path) -> bytes | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as cause:
        raise CanaryManifestError("output_invalid") from cause
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise CanaryManifestError("output_invalid")
    return _read_limited(path, error="output_invalid")


def _stage_file(path: Path, data: bytes) -> Path:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
    except OSError as cause:
        temporary.unlink(missing_ok=True)
        raise CanaryManifestError("output_staging_failed") from cause
    return temporary


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _same_inode(left: Path, right: Path) -> bool:
    try:
        left_stat = left.stat()
        right_stat = right.lstat()
    except OSError:
        return False
    return (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)


def _publish_pair(task_file: Path, task_bytes: bytes, receipt: Path, receipt_bytes: bytes) -> bool:
    existing_task = _existing_output(task_file)
    existing_receipt = _existing_output(receipt)
    if existing_task is not None or existing_receipt is not None:
        if existing_task == task_bytes and existing_receipt == receipt_bytes:
            return False
        if (existing_task is None) != (existing_receipt is None):
            raise CanaryManifestError("output_pair_incomplete")
        raise CanaryManifestError("output_already_exists")

    task_temporary = _stage_file(task_file, task_bytes)
    receipt_temporary = _stage_file(receipt, receipt_bytes)
    task_linked = False
    receipt_linked = False
    try:
        try:
            os.link(task_temporary, task_file)
            task_linked = True
            os.link(receipt_temporary, receipt)
            receipt_linked = True
            _fsync_directory(task_file.parent)
            if receipt.parent != task_file.parent:
                _fsync_directory(receipt.parent)
        except OSError as cause:
            if task_linked and not receipt_linked and _same_inode(task_temporary, task_file):
                task_file.unlink(missing_ok=True)
            raise CanaryManifestError("output_publication_failed") from cause
    finally:
        task_temporary.unlink(missing_ok=True)
        receipt_temporary.unlink(missing_ok=True)
    return True


def _selection(rows: list[dict[str, Any]], control_count: int, seed: str, identity_sha256: str) -> tuple[bytes, int]:
    nonvalid = [row for row in rows if not row["valid"]]
    valid = [row for row in rows if row["valid"]]
    if not nonvalid:
        raise CanaryManifestError("oracle_has_no_nonvalid_rows")
    if control_count > len(valid):
        raise CanaryManifestError("control_count_exceeds_valid_rows")
    seed_bytes = seed.encode("utf-8")

    def rank(row: dict[str, Any]) -> tuple[bytes, int]:
        digest = hashlib.sha256(
            seed_bytes + b"\0" + identity_sha256.encode("ascii") + b"\0" + row["slug"].encode("utf-8")
        ).digest()
        return digest, row["index"]

    controls = {row["slug"] for row in sorted(valid, key=rank)[:control_count]}
    selected = [row["slug"] for row in rows if not row["valid"] or row["slug"] in controls]
    if len(selected) != len(nonvalid) + control_count or len(selected) != len(set(selected)):
        raise CanaryManifestError("canary_selection_invalid")
    return "".join(f"{slug}\n" for slug in selected).encode("utf-8"), len(nonvalid)


def build_canary_manifest(
    oracle_dir: Path,
    task_file: Path,
    receipt: Path,
    *,
    expected_total: int = DEFAULT_EXPECTED_TOTAL,
    control_count: int = DEFAULT_CONTROL_COUNT,
    seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    if type(expected_total) is not int or expected_total < 1:
        raise CanaryManifestError("expected_total_invalid")
    if type(control_count) is not int or control_count < 0:
        raise CanaryManifestError("control_count_invalid")
    if (
        not isinstance(seed, str)
        or not seed
        or len(seed.encode("utf-8")) > 256
        or seed.strip() != seed
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in seed)
    ):
        raise CanaryManifestError("seed_invalid")
    try:
        oracle_dir = oracle_dir.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise CanaryManifestError("oracle_directory_invalid") from cause
    if not oracle_dir.is_dir():
        raise CanaryManifestError("oracle_directory_invalid")
    task_file = _target_path(task_file)
    receipt = _target_path(receipt)
    if task_file == receipt or task_file.is_relative_to(oracle_dir) or receipt.is_relative_to(oracle_dir):
        raise CanaryManifestError("output_path_invalid")

    with _hold_oracle_lock(oracle_dir):
        identity, identity_sha256, identity_file_sha256, identity_path, identity_raw = _run_identity(
            oracle_dir,
            expected_total,
        )
        source_wheel_recovery = _source_wheel_recovery(identity)
        try:
            source_wheel_artifacts, source_wheel_entry_digests = _audit_source_wheel_artifacts(
                oracle_dir,
                source_wheel_recovery,
            )
        except PromotionError as cause:
            raise CanaryManifestError("oracle_source_wheel_artifacts_invalid") from cause
        selection = identity["selection"]
        network_semantics = identity["network_semantics"]
        rows, reasons, results_sha256, results_path, results_raw = _results(
            oracle_dir,
            expected_total=expected_total,
            identity_sha256=identity_sha256,
            network_semantics=network_semantics,
            ordered_slugs_sha256=selection["ordered_task_slugs_sha256"],
            source_wheel_attestation_sha256s=(
                source_wheel_entry_digests if source_wheel_recovery is not None else None
            ),
        )
        passed = sum(row["valid"] for row in rows)
        summary_sha256, summary_path, summary_raw = _summary(
            oracle_dir,
            expected_total=expected_total,
            identity_sha256=identity_sha256,
            network_semantics=network_semantics,
            reasons=reasons,
            passed=passed,
            source_wheel_attestation_sha256=(
                source_wheel_artifacts["attestation"]["sha256"] if source_wheel_artifacts is not None else None
            ),
        )
        status_count = _statuses(oracle_dir, rows)
        task_bytes, nonvalid_count = _selection(rows, control_count, seed, identity_sha256)
        task_file_sha256 = _sha256(task_bytes)
        selected_count = nonvalid_count + control_count
        payload = {
            "artifact_type": RECEIPT_ARTIFACT_TYPE,
            "counts": {
                "controls": control_count,
                "nonvalid": nonvalid_count,
                "oracle_reasons": dict(reasons),
                "selected": selected_count,
                "source_statuses": status_count,
                "source_total": expected_total,
                "source_valid": passed,
            },
            "selection": {
                "algorithm": "sha256-seed-run-identity-slug-v1/source-order-output",
                "seed_sha256": _sha256(seed.encode("utf-8")),
                "task_file": {
                    "count": selected_count,
                    "mode": "0600",
                    "sha256": task_file_sha256,
                },
            },
            "source_oracle": {
                "results": {"path": "results.jsonl", "sha256": results_sha256},
                "run_identity": {
                    "identity_sha256": identity_sha256,
                    "path": "run_identity.json",
                    "sha256": identity_file_sha256,
                },
                "summary": {"path": "summary.json", "sha256": summary_sha256},
            },
            "schema_version": RECEIPT_SCHEMA_VERSION,
        }
        if source_wheel_artifacts is not None:
            payload["source_oracle"]["source_wheel_recovery"] = source_wheel_artifacts
        receipt_sha256 = _canonical_json_sha256(payload)
        envelope = {
            "receipt": payload,
            "receipt_sha256": receipt_sha256,
            "schema_version": RECEIPT_SCHEMA_VERSION,
        }
        receipt_bytes = _canonical_json_file(envelope)
        try:
            current_source_wheel_artifacts, _ = _audit_source_wheel_artifacts(
                oracle_dir,
                source_wheel_recovery,
            )
        except PromotionError as cause:
            raise CanaryManifestError("oracle_source_changed") from cause
        if (
            _read_limited(identity_path, error="oracle_source_changed") != identity_raw
            or _read_limited(results_path, error="oracle_source_changed") != results_raw
            or _read_limited(summary_path, error="oracle_source_changed") != summary_raw
            or current_source_wheel_artifacts != source_wheel_artifacts
        ):
            raise CanaryManifestError("oracle_source_changed")
        published = _publish_pair(task_file, task_bytes, receipt, receipt_bytes)

    return {
        "control_count": control_count,
        "nonvalid_count": nonvalid_count,
        "published": published,
        "receipt_sha256": receipt_sha256,
        "selected_count": selected_count,
        "source_total": expected_total,
        "source_valid": passed,
        "task_file_sha256": task_file_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle_dir", type=Path)
    parser.add_argument("task_file", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expected-total", type=int, default=DEFAULT_EXPECTED_TOTAL)
    parser.add_argument("--controls", type=int, default=DEFAULT_CONTROL_COUNT)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    try:
        summary = build_canary_manifest(
            args.oracle_dir,
            args.task_file,
            args.receipt,
            expected_total=args.expected_total,
            control_count=args.controls,
            seed=args.seed,
        )
    except CanaryManifestError as error:
        print(f"oracle_repair_canary_error:{error}", file=sys.stderr)
        return 2
    except Exception:
        print("oracle_repair_canary_error:internal_failure", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
