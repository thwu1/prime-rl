#!/usr/bin/env python3
"""Promote a complete oracle run into an approved, deterministic task manifest.

The command is a dry-run unless ``--apply`` is supplied. Its stdout contains
counts and digests only; task identifiers and oracle error details are never
printed. Existing manifest order is retained for tasks that remain valid and
replacement tasks are appended in the canonical dataset order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tomllib
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
TASKSET_ID = "terminal-bench-vmvm"
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
PROVENANCE_KEYS = {
    "host",
    "oracle_solution_network_mode",
    "prime_rl",
    "prime_rl_tree",
    "slurm_job_id",
    "verifiers",
    "vmvm_tb_v2",
}


class PromotionError(ValueError):
    """An oracle run or approval input failed a promotion invariant."""


def _read_bytes(path: Path, *, limit: int, error: str) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as cause:
        raise PromotionError(error) from cause
    if len(data) > limit:
        raise PromotionError(error)
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_file_with_sha256(path: Path, *, error: str) -> tuple[dict[str, Any], str]:
    raw = _read_bytes(path, limit=MAX_JSON_BYTES, error=error)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise PromotionError(error) from cause
    if not isinstance(value, dict):
        raise PromotionError(error)
    return value, _sha256(raw)


def _json_file(path: Path, *, error: str) -> dict[str, Any]:
    return _json_file_with_sha256(path, error=error)[0]


def _manifest_tasks(data: bytes, *, error: str) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as cause:
        raise PromotionError(error) from cause
    if not text.endswith("\n"):
        raise PromotionError(error)
    tasks = text.splitlines()
    if not tasks or any(not task or task.strip() != task or "\t" in task for task in tasks):
        raise PromotionError(error)
    if len(tasks) != len(set(tasks)):
        raise PromotionError(error)
    return tasks


def _git_output(dataset_dir: Path, *args: str, error: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(dataset_dir), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as cause:
        raise PromotionError(error) from cause


def _audit_provenance(
    oracle_dir: Path,
    project_root: Path,
    *,
    expected_prime_rl_commit: str,
    required_prime_rl_ancestor: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    trusted_reference_solution: str,
) -> str:
    if (
        REVISION_RE.fullmatch(expected_prime_rl_commit) is None
        or REVISION_RE.fullmatch(required_prime_rl_ancestor) is None
        or REVISION_RE.fullmatch(expected_verifiers_commit) is None
        or SHA256_RE.fullmatch(expected_vmvm_tb_v2_sha256) is None
    ):
        raise PromotionError("provenance_expectation_invalid")
    raw = _read_bytes(
        oracle_dir / "provenance.txt",
        limit=MAX_CONFIG_BYTES,
        error="oracle_provenance_unreadable",
    )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise PromotionError("oracle_provenance_invalid") from cause
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise PromotionError("oracle_provenance_invalid")
        records[key] = value
    if set(records) != PROVENANCE_KEYS:
        raise PromotionError("oracle_provenance_invalid")
    if (
        records["prime_rl"] != expected_prime_rl_commit
        or records["prime_rl_tree"] != CLEAN_TREE_SHA256
        or records["verifiers"] != expected_verifiers_commit
        or records["vmvm_tb_v2"] != expected_vmvm_tb_v2_sha256
        or records["oracle_solution_network_mode"] != trusted_reference_solution
        or not records["host"].strip()
        or not records["slurm_job_id"].isdigit()
    ):
        raise PromotionError("oracle_provenance_mismatch")

    try:
        root = project_root.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("project_root_unreadable") from cause
    try:
        ancestry = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                required_prime_rl_ancestor,
                expected_prime_rl_commit,
            ],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as cause:
        raise PromotionError("oracle_commit_ancestry_unverifiable") from cause
    if ancestry.returncode == 1:
        raise PromotionError("oracle_commit_before_required_ancestor")
    if ancestry.returncode != 0:
        raise PromotionError("oracle_commit_ancestry_unverifiable")
    gitlink = _git_output(
        root,
        "ls-tree",
        expected_prime_rl_commit,
        "deps/verifiers",
        error="oracle_verifier_gitlink_unverifiable",
    ).strip()
    expected_gitlink = f"160000 commit {expected_verifiers_commit}\tdeps/verifiers"
    if gitlink != expected_gitlink:
        raise PromotionError("oracle_verifier_gitlink_mismatch")
    return _sha256(raw)


def _dataset_tasks(dataset_dir: Path, revision: str, expected_total: int) -> list[str]:
    try:
        root = dataset_dir.resolve(strict=True)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("dataset_unreadable") from cause
    if not root.is_dir():
        raise PromotionError("dataset_unreadable")
    head = _git_output(root, "rev-parse", "HEAD", error="dataset_revision_unverifiable").strip()
    if head != revision:
        raise PromotionError("dataset_revision_mismatch")
    status = _git_output(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        error="dataset_cleanliness_unverifiable",
    )
    if status.strip():
        raise PromotionError("dataset_not_clean")
    try:
        tasks = [
            path.name
            for path in sorted(root.iterdir())
            if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
        ]
    except OSError as cause:
        raise PromotionError("dataset_unreadable") from cause
    if len(tasks) != expected_total or len(tasks) != len(set(tasks)):
        raise PromotionError("dataset_task_count_mismatch")
    if any(
        not task
        or task.strip() != task
        or task.startswith("#")
        or any(character in task for character in ("\r", "\n", "\t"))
        for task in tasks
    ):
        raise PromotionError("dataset_task_name_invalid")
    return tasks


def _results(oracle_dir: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _read_bytes(
        oracle_dir / "results.jsonl",
        limit=MAX_JSON_BYTES,
        error="oracle_results_unreadable",
    )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as cause:
        raise PromotionError("oracle_results_invalid") from cause
    if not lines:
        raise PromotionError("oracle_results_empty")
    parsed: list[dict[str, Any]] = []
    for line in lines:
        try:
            result = json.loads(line)
        except json.JSONDecodeError as cause:
            raise PromotionError("oracle_results_invalid") from cause
        if not isinstance(result, dict):
            raise PromotionError("oracle_results_invalid")
        parsed.append(result)
    return parsed, _sha256(raw)


def _expected_semantics(trusted_reference_solution: str) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "trusted_reference_solution": trusted_reference_solution,
        "verifier": "declared",
    }


def _audit_oracle(
    oracle_dir: Path,
    dataset_dir: Path,
    dataset_revision: str,
    *,
    expected_total: int,
    minimum_pass_rate: float,
    minimum_valid: int,
    trusted_reference_solution: str,
) -> tuple[list[str], set[str], int, float, str, str]:
    canonical = _dataset_tasks(dataset_dir, dataset_revision, expected_total)
    canonical_set = set(canonical)
    results, results_sha256 = _results(oracle_dir)
    if len(results) != expected_total:
        raise PromotionError("oracle_result_count_mismatch")

    expected_semantics = _expected_semantics(trusted_reference_solution)
    slugs: list[str] = []
    valid: set[str] = set()
    reasons: Counter[str] = Counter()
    for expected_index, result in enumerate(results):
        slug = result.get("slug")
        is_valid = result.get("valid")
        reason = result.get("reason")
        if (
            result.get("index") != expected_index
            or not isinstance(slug, str)
            or not slug
            or not isinstance(is_valid, bool)
            or not isinstance(reason, str)
            or (is_valid and reason != "valid")
            or (not is_valid and reason == "valid")
        ):
            raise PromotionError("oracle_result_schema_invalid")
        if result.get("oracle_network_semantics") != expected_semantics:
            raise PromotionError("oracle_result_semantics_mismatch")
        slugs.append(slug)
        reasons[reason] += 1
        if is_valid:
            valid.add(slug)
    if len(slugs) != len(set(slugs)):
        raise PromotionError("oracle_result_duplicates")
    if slugs != canonical:
        raise PromotionError("oracle_result_universe_or_order_mismatch")

    passed = len(valid)
    pass_rate = passed / expected_total
    if pass_rate < minimum_pass_rate:
        raise PromotionError("oracle_pass_rate_below_minimum")
    if passed < minimum_valid:
        raise PromotionError("oracle_valid_count_below_minimum")

    summary, summary_sha256 = _json_file_with_sha256(
        oracle_dir / "summary.json",
        error="oracle_summary_invalid",
    )
    finished_at = summary.get("finished_at")
    if (
        isinstance(finished_at, bool)
        or not isinstance(finished_at, (int, float))
        or not math.isfinite(float(finished_at))
    ):
        raise PromotionError("oracle_summary_not_final")
    if (
        summary.get("selected") != expected_total
        or summary.get("completed") != expected_total
        or summary.get("passed") != passed
        or summary.get("reasons") != dict(reasons)
        or summary.get("oracle_network_semantics") != expected_semantics
    ):
        raise PromotionError("oracle_summary_mismatch")
    summary_rate = summary.get("pass_rate")
    if (
        isinstance(summary_rate, bool)
        or not isinstance(summary_rate, (int, float))
        or not math.isfinite(float(summary_rate))
        or not math.isclose(float(summary_rate), pass_rate, rel_tol=0.0, abs_tol=1e-15)
    ):
        raise PromotionError("oracle_summary_mismatch")

    run_config = _json_file(oracle_dir / "run_config.json", error="oracle_run_config_invalid")
    try:
        configured_dataset = Path(run_config["dataset_dir"]).resolve(strict=True)
    except (KeyError, TypeError, OSError, RuntimeError) as cause:
        raise PromotionError("oracle_run_config_invalid") from cause
    if (
        configured_dataset != dataset_dir.resolve(strict=True)
        or run_config.get("selected_tasks") != expected_total
        or run_config.get("oracle_solution_network_mode") != trusted_reference_solution
        or run_config.get("oracle_network_semantics") != expected_semantics
    ):
        raise PromotionError("oracle_run_config_mismatch")
    if (
        _json_file(
            oracle_dir / "oracle_network_semantics.json",
            error="oracle_semantics_invalid",
        )
        != expected_semantics
    ):
        raise PromotionError("oracle_semantics_mismatch")

    status_dir = oracle_dir / "tasks"
    try:
        status_paths = sorted(status_dir.glob("*.json"))
    except OSError as cause:
        raise PromotionError("oracle_statuses_unreadable") from cause
    if len(status_paths) != expected_total:
        raise PromotionError("oracle_status_count_mismatch")
    expected_by_slug = {result["slug"]: result for result in results}
    observed_statuses: set[str] = set()
    for path in status_paths:
        status = _json_file(path, error="oracle_status_invalid")
        slug = status.get("slug")
        if not isinstance(slug, str) or slug in observed_statuses or slug not in expected_by_slug:
            raise PromotionError("oracle_status_set_mismatch")
        observed_statuses.add(slug)
        expected = expected_by_slug[slug]
        for key in ("index", "valid", "reason", "oracle_network_semantics"):
            if status.get(key) != expected.get(key):
                raise PromotionError("oracle_status_mismatch")
    if observed_statuses != canonical_set:
        raise PromotionError("oracle_status_set_mismatch")
    return canonical, valid, passed, pass_rate, results_sha256, summary_sha256


def _resolve_task_file(project_root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as cause:
        raise PromotionError("config_task_file_invalid") from cause


def _updated_config(
    path: Path,
    *,
    project_root: Path,
    output: Path,
    current_sha256: str,
    new_sha256: str,
    selected_count: int,
) -> bytes:
    raw = _read_bytes(path, limit=MAX_CONFIG_BYTES, error="config_unreadable")
    try:
        text = raw.decode("utf-8")
        config = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as cause:
        raise PromotionError("config_invalid") from cause
    taskset = config.get("taskset")
    if not isinstance(taskset, dict) or taskset.get("id") != TASKSET_ID or "tasks" in taskset:
        raise PromotionError("config_taskset_invalid")
    if config.get("num_tasks") != selected_count:
        raise PromotionError("config_task_count_mismatch")
    task_file = taskset.get("task_file")
    if not isinstance(task_file, str) or _resolve_task_file(project_root, task_file) != output.resolve():
        raise PromotionError("config_task_file_mismatch")
    if taskset.get("task_file_sha256") != current_sha256:
        raise PromotionError("config_current_hash_mismatch")

    lines = text.splitlines(keepends=True)
    section: str | None = None
    matches: list[int] = []
    pattern = re.compile(
        r'^(?P<prefix>[ \t]*task_file_sha256[ \t]*=[ \t]*")[0-9a-f]{64}'
        r'(?P<suffix>"[ \t]*(?:#.*)?(?:\r?\n)?$)'
    )
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
        if section == "taskset" and pattern.fullmatch(line):
            matches.append(index)
    if len(matches) != 1:
        raise PromotionError("config_task_hash_line_invalid")
    index = matches[0]
    lines[index] = pattern.sub(rf"\g<prefix>{new_sha256}\g<suffix>", lines[index])
    updated = "".join(lines).encode("utf-8")
    try:
        reparsed = tomllib.loads(updated.decode("utf-8"))
    except tomllib.TOMLDecodeError as cause:
        raise PromotionError("config_rewrite_invalid") from cause
    if reparsed["taskset"].get("task_file_sha256") != new_sha256:
        raise PromotionError("config_rewrite_invalid")
    return updated


def _replace_files(updates: list[tuple[Path, bytes]]) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, data in updates:
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, destination))
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def promote(
    oracle_dir: Path,
    output: Path,
    *,
    dataset_dir: Path,
    dataset_revision: str,
    expected_current_manifest_sha256: str,
    expected_prime_rl_commit: str,
    required_prime_rl_ancestor: str,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    configs: list[Path],
    project_root: Path,
    expected_total: int = 2_538,
    limit: int = 2_500,
    minimum_pass_rate: float = 0.9,
    trusted_reference_solution: str = "public",
    expected_config_count: int = 2,
    apply: bool = False,
) -> dict[str, Any]:
    if REVISION_RE.fullmatch(dataset_revision) is None:
        raise PromotionError("dataset_revision_invalid")
    if SHA256_RE.fullmatch(expected_current_manifest_sha256) is None:
        raise PromotionError("current_manifest_hash_invalid")
    if expected_total < 1 or limit < 1 or limit > expected_total:
        raise PromotionError("task_counts_invalid")
    if not 0.0 <= minimum_pass_rate <= 1.0:
        raise PromotionError("minimum_pass_rate_invalid")
    if trusted_reference_solution not in {"declared", "public"}:
        raise PromotionError("trusted_reference_solution_invalid")
    if expected_config_count < 1 or len(configs) != expected_config_count:
        raise PromotionError("config_count_mismatch")
    if len(configs) != len({path.resolve() for path in configs}):
        raise PromotionError("configs_invalid")

    output = output.resolve()
    current_bytes = _read_bytes(
        output,
        limit=MAX_MANIFEST_BYTES,
        error="current_manifest_unreadable",
    )
    current_sha256 = _sha256(current_bytes)
    if current_sha256 != expected_current_manifest_sha256:
        raise PromotionError("current_manifest_hash_mismatch")
    current_tasks = _manifest_tasks(current_bytes, error="current_manifest_invalid")
    if len(current_tasks) != limit:
        raise PromotionError("current_manifest_count_mismatch")

    oracle_provenance_sha256 = _audit_provenance(
        oracle_dir.resolve(),
        project_root,
        expected_prime_rl_commit=expected_prime_rl_commit,
        required_prime_rl_ancestor=required_prime_rl_ancestor,
        expected_verifiers_commit=expected_verifiers_commit,
        expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        trusted_reference_solution=trusted_reference_solution,
    )
    canonical, valid, passed, pass_rate, oracle_results_sha256, oracle_summary_sha256 = _audit_oracle(
        oracle_dir.resolve(),
        dataset_dir,
        dataset_revision,
        expected_total=expected_total,
        minimum_pass_rate=minimum_pass_rate,
        minimum_valid=limit,
        trusted_reference_solution=trusted_reference_solution,
    )
    canonical_set = set(canonical)
    if not set(current_tasks).issubset(canonical_set):
        raise PromotionError("current_manifest_not_in_dataset")

    preserved = [task for task in current_tasks if task in valid]
    replacements = [task for task in canonical if task in valid and task not in current_tasks]
    selected = (preserved + replacements)[:limit]
    if len(selected) != limit or len(selected) != len(set(selected)) or not set(selected).issubset(valid):
        raise PromotionError("selected_manifest_invariant_failed")
    selected_bytes = "".join(f"{task}\n" for task in selected).encode("utf-8")
    selected_sha256 = _sha256(selected_bytes)

    config_updates = [
        (
            path.resolve(),
            _updated_config(
                path.resolve(),
                project_root=project_root.resolve(),
                output=output,
                current_sha256=current_sha256,
                new_sha256=selected_sha256,
                selected_count=limit,
            ),
        )
        for path in configs
    ]
    if apply:
        _replace_files([(output, selected_bytes), *config_updates])
        applied = _read_bytes(
            output,
            limit=MAX_MANIFEST_BYTES,
            error="applied_manifest_unreadable",
        )
        if _sha256(applied) != selected_sha256:
            raise PromotionError("applied_manifest_hash_mismatch")
        for path, expected in config_updates:
            observed = _read_bytes(path, limit=MAX_CONFIG_BYTES, error="applied_config_unreadable")
            if observed != expected:
                raise PromotionError("applied_config_mismatch")

    return {
        "applied": apply,
        "completed": expected_total,
        "configured_files": len(configs),
        "current_manifest_sha256": current_sha256,
        "dataset_revision": dataset_revision,
        "oracle_pass_rate": pass_rate,
        "oracle_prime_rl_commit": expected_prime_rl_commit,
        "oracle_provenance_sha256": oracle_provenance_sha256,
        "oracle_results_sha256": oracle_results_sha256,
        "oracle_summary_sha256": oracle_summary_sha256,
        "oracle_verifiers_commit": expected_verifiers_commit,
        "oracle_vmvm_tb_v2_sha256": expected_vmvm_tb_v2_sha256,
        "passed": passed,
        "removed_invalid": limit - len(preserved),
        "selected": len(selected),
        "selected_manifest_sha256": selected_sha256,
        "selected_subset_valid": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--expected-current-manifest-sha256", required=True)
    parser.add_argument("--expected-prime-rl-commit", required=True)
    parser.add_argument("--required-prime-rl-ancestor", required=True)
    parser.add_argument("--expected-verifiers-commit", required=True)
    parser.add_argument("--expected-vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--config", type=Path, action="append", required=True)
    parser.add_argument("--expected-config-count", type=int, default=2)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-total", type=int, default=2_538)
    parser.add_argument("--limit", type=int, default=2_500)
    parser.add_argument("--minimum-pass-rate", type=float, default=0.9)
    parser.add_argument(
        "--trusted-reference-solution",
        choices=("declared", "public"),
        default="public",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = promote(
            args.oracle_dir,
            args.output,
            dataset_dir=args.dataset_dir,
            dataset_revision=args.dataset_revision,
            expected_current_manifest_sha256=args.expected_current_manifest_sha256,
            expected_prime_rl_commit=args.expected_prime_rl_commit,
            required_prime_rl_ancestor=args.required_prime_rl_ancestor,
            expected_verifiers_commit=args.expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=args.expected_vmvm_tb_v2_sha256,
            configs=args.config,
            project_root=args.project_root,
            expected_total=args.expected_total,
            limit=args.limit,
            minimum_pass_rate=args.minimum_pass_rate,
            trusted_reference_solution=args.trusted_reference_solution,
            expected_config_count=args.expected_config_count,
            apply=args.apply,
        )
    except PromotionError as error:
        print(f"oracle_promotion_error:{error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
