#!/usr/bin/env python3
"""Durable, resumable oracle validation for Terminal-Bench tasks on VMVM."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import math
import os
import random
import re
import signal
import stat
import tarfile
import time
from pathlib import Path, PurePosixPath

from terminal_bench_vmvm.source_wheels import (
    SOURCE_BUILD_UMASK,
    SOURCE_WHEEL_RECOVERY_SCHEMA_VERSION,
    canonical_json,
    sha256_bytes,
    source_build_environment_variables,
)
from terminal_bench_vmvm.taskset import (
    OracleFailure,
    TerminalBenchTask,
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    UnsupportedTaskError,
)
from verifiers.v1.env import resolve_runtime_config
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import VMVMConfig, make_runtime

logger = logging.getLogger("terminal_bench_vmvm.oracle")

REVISION_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
RUN_IDENTITY_SCHEMA_VERSION = 1
RUNTIME_IMAGE = "python:3.12-slim"
RUNTIME_WORKDIR = "/app"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--dataset-revision")
    parser.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--dataset-archive-sha256")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image-prefix", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--image-manifest", type=Path)
    parser.add_argument("--image-manifest-sha256")
    parser.add_argument("--source-wheel-policy", type=Path)
    parser.add_argument("--source-wheel-policy-sha256")
    parser.add_argument("--source-wheel-attestation-sha256")
    parser.add_argument("--use-declared-images", action="store_true")
    parser.add_argument("--enable-compose", action="store_true")
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--task-file-sha256")
    parser.add_argument("--tasks", nargs="*")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-concurrent", type=int, default=64)
    parser.add_argument("--infra-retries", type=int, default=2)
    parser.add_argument("--setup-timeout", type=float, default=1800)
    parser.add_argument("--validate-timeout", type=float, default=10800)
    parser.add_argument("--session-timeout", type=float, default=10800)
    parser.add_argument("--tenant-id", default="async_2347641")
    parser.add_argument("--lease-ttl", default="60s")
    parser.add_argument("--max-session-buffer-size", type=int, default=67_108_864)
    parser.add_argument("--verifier-runtime-retries", type=int, default=2)
    parser.add_argument("--vacli-lease-retries", type=int, required=True)
    parser.add_argument("--vacli-max-concurrent-leases", type=int, required=True)
    parser.add_argument("--vacli-max-pull-retries", type=int, required=True)
    parser.add_argument("--vacli-image-pull-timeout-seconds", type=int, required=True)
    parser.add_argument("--vacli-container-privileged", type=int, choices=(0, 1), required=True)
    parser.add_argument("--timeout-multiplier", type=float, default=1.0)
    parser.add_argument("--resource-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--oracle-solution-network-mode",
        choices=("declared", "public"),
        default="declared",
        help="network policy for trusted solve.sh only; verifier policy remains declared",
    )
    parser.add_argument("--minimum-pass-rate", type=float, default=0.9)
    parser.add_argument("--minimum-valid", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rerun-invalid", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--prime-rl-commit", required=True)
    parser.add_argument("--prime-rl-tree-sha256", required=True)
    parser.add_argument("--verifiers-commit", required=True)
    parser.add_argument("--vmvm-tb-v2-sha256", required=True)
    parser.add_argument("--invocation-host", required=True)
    parser.add_argument("--slurm-job-id", required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    if args.max_concurrent < 1:
        parser.error("--max-concurrent must be positive")
    if args.infra_retries < 0:
        parser.error("--infra-retries cannot be negative")
    if args.vacli_lease_retries < 0 or args.vacli_max_pull_retries < 0:
        parser.error("VACLI retry counts cannot be negative")
    if args.vacli_max_concurrent_leases < 1 or args.vacli_image_pull_timeout_seconds < 1:
        parser.error("VACLI concurrency and pull timeout must be positive")
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate must be between 0 and 1")
    if args.minimum_valid < 0:
        parser.error("--minimum-valid cannot be negative")
    if args.timeout_multiplier <= 0 or args.resource_multiplier <= 0:
        parser.error("timeout and resource multipliers must be positive")
    if args.dataset_revision is not None and REVISION_RE.fullmatch(args.dataset_revision) is None:
        parser.error("--dataset-revision must be an exact lowercase 40-hex commit")
    if (args.dataset_archive is None) != (args.dataset_archive_sha256 is None):
        parser.error("--dataset-archive and --dataset-archive-sha256 must be supplied together")
    if args.dataset_archive_sha256 is not None and SHA256_RE.fullmatch(args.dataset_archive_sha256) is None:
        parser.error("--dataset-archive-sha256 must be a lowercase SHA-256")
    if (args.dataset_revision is None) == (args.dataset_archive is None):
        parser.error("supply exactly one of --dataset-revision or --dataset-archive")
    for option, value in (
        ("--prime-rl-commit", args.prime_rl_commit),
        ("--verifiers-commit", args.verifiers_commit),
    ):
        if REVISION_RE.fullmatch(value) is None:
            parser.error(f"{option} must be an exact lowercase 40-hex commit")
    for option, value in (
        ("--prime-rl-tree-sha256", args.prime_rl_tree_sha256),
        ("--vmvm-tb-v2-sha256", args.vmvm_tb_v2_sha256),
    ):
        if SHA256_RE.fullmatch(value) is None:
            parser.error(f"{option} must be a lowercase SHA-256")
    if args.prime_rl_tree_sha256 != CLEAN_TREE_SHA256:
        parser.error("--prime-rl-tree-sha256 must attest a clean source worktree")
    for path_option, path, digest_option, digest in (
        ("--task-file", args.task_file, "--task-file-sha256", args.task_file_sha256),
        (
            "--image-manifest",
            args.image_manifest,
            "--image-manifest-sha256",
            args.image_manifest_sha256,
        ),
        (
            "--source-wheel-policy",
            args.source_wheel_policy,
            "--source-wheel-policy-sha256",
            args.source_wheel_policy_sha256,
        ),
    ):
        if (path is None) != (digest is None):
            parser.error(f"{path_option} and {digest_option} must be supplied together")
        if digest is not None and SHA256_RE.fullmatch(digest) is None:
            parser.error(f"{digest_option} must be a lowercase SHA-256")
    if (
        args.source_wheel_attestation_sha256 is not None
        and SHA256_RE.fullmatch(args.source_wheel_attestation_sha256) is None
    ):
        parser.error("--source-wheel-attestation-sha256 must be a lowercase SHA-256")
    if args.source_wheel_attestation_sha256 is not None and args.source_wheel_policy is None:
        parser.error("--source-wheel-attestation-sha256 requires --source-wheel-policy")
    if not args.invocation_host.strip():
        parser.error("--invocation-host must be nonempty")
    if not args.slurm_job_id.isdigit():
        parser.error("--slurm-job-id must contain only decimal digits")
    return args


def _requested_tasks(args: argparse.Namespace) -> list[str] | None:
    names = list(args.tasks or [])
    if args.task_file:
        names.extend(
            line.strip().split("\t", 1)[0]
            for line in args.task_file.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return sorted(set(names)) or None


def _canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _ordered_task_slugs_sha256(tasks: list[TerminalBenchTask]) -> str:
    ordered = "".join(f"{task.slug}\n" for task in tasks).encode()
    return hashlib.sha256(ordered).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SystemExit(f"cannot hash pinned input: {path}") from error
    return digest.hexdigest()


def _tree_digest(entries: dict[str, dict]) -> str:
    digest = hashlib.sha256()
    for relative_path in sorted(entries):
        digest.update(_canonical_json(entries[relative_path]))
        digest.update(b"\n")
    return digest.hexdigest()


def _filesystem_tree_digest(root: Path) -> str:
    entries: dict[str, dict] = {}
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError as error:
        raise SystemExit(f"cannot enumerate dataset tree: {root}") from error
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            before = path.lstat()
            entry = {
                "path": relative,
                "mode": stat.S_IMODE(before.st_mode),
            }
            if stat.S_ISDIR(before.st_mode):
                entry["type"] = "directory"
            elif stat.S_ISREG(before.st_mode):
                entry.update(
                    {
                        "type": "file",
                        "size": before.st_size,
                        "sha256": _file_sha256(path),
                    }
                )
            elif stat.S_ISLNK(before.st_mode):
                entry.update({"type": "symlink", "target": os.readlink(path)})
            else:
                raise SystemExit(f"dataset tree contains unsupported filesystem entry: {path}")
            after = path.lstat()
        except OSError as error:
            raise SystemExit(f"cannot inspect dataset tree entry: {path}") from error
        if (
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
            before.st_dev,
        ) != (
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
            after.st_dev,
        ):
            raise SystemExit(f"dataset tree changed while it was being hashed: {path}")
        entries[relative] = entry
    if not entries:
        raise SystemExit(f"dataset tree is empty: {root}")
    try:
        observed_paths = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    except OSError as error:
        raise SystemExit(f"cannot revalidate dataset tree: {root}") from error
    if observed_paths != set(entries):
        raise SystemExit(f"dataset tree changed while it was being hashed: {root}")
    return _tree_digest(entries)


def _archive_tasks_tree_digest(path: Path) -> str:
    entries: dict[str, dict] = {}
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                member_path = PurePosixPath(member.name)
                if not member_path.parts or member_path.parts[0] != "tasks":
                    continue
                if len(member_path.parts) == 1:
                    continue
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise SystemExit(f"dataset archive contains an unsafe task path: {member.name}")
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative in entries:
                    raise SystemExit(f"dataset archive contains duplicate task path: {relative}")
                entry = {
                    "path": relative,
                    "mode": member.mode & 0o7777,
                }
                if member.isdir():
                    entry["type"] = "directory"
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise SystemExit(f"cannot read dataset archive member: {member.name}")
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                    if size != member.size:
                        raise SystemExit(f"dataset archive member has the wrong size: {member.name}")
                    entry.update({"type": "file", "size": size, "sha256": digest.hexdigest()})
                elif member.issym():
                    entry.update({"type": "symlink", "target": member.linkname})
                else:
                    raise SystemExit(f"dataset archive contains unsupported task entry: {member.name}")
                entries[relative] = entry
    except (OSError, tarfile.TarError) as error:
        raise SystemExit(f"cannot read dataset archive: {path}") from error
    if not entries:
        raise SystemExit(f"dataset archive has no tasks payload: {path}")
    return _tree_digest(entries)


def _validated_dataset_content_sha256(args: argparse.Namespace) -> str | None:
    if args.dataset_revision is not None:
        return None
    assert args.dataset_archive is not None
    assert args.dataset_archive_sha256 is not None
    archive_path = args.dataset_archive.resolve()
    try:
        archive_before = archive_path.stat()
    except OSError as error:
        raise SystemExit(f"cannot inspect dataset archive: {archive_path}") from error
    observed_archive_sha256 = _file_sha256(archive_path)
    if observed_archive_sha256 != args.dataset_archive_sha256:
        raise SystemExit(
            "dataset archive SHA-256 mismatch: "
            f"expected {args.dataset_archive_sha256}, observed {observed_archive_sha256}"
        )
    archive_content_sha256 = _archive_tasks_tree_digest(archive_path)
    try:
        archive_after = archive_path.stat()
    except OSError as error:
        raise SystemExit(f"cannot revalidate dataset archive: {archive_path}") from error
    if (
        archive_before.st_mode,
        archive_before.st_size,
        archive_before.st_mtime_ns,
        archive_before.st_ino,
        archive_before.st_dev,
    ) != (
        archive_after.st_mode,
        archive_after.st_size,
        archive_after.st_mtime_ns,
        archive_after.st_ino,
        archive_after.st_dev,
    ):
        raise SystemExit(f"dataset archive changed while it was being verified: {archive_path}")
    live_content_sha256 = _filesystem_tree_digest(args.dataset_dir.resolve())
    if live_content_sha256 != archive_content_sha256:
        raise SystemExit(
            "dataset tree does not match the pinned archive tasks payload: "
            f"archive={archive_content_sha256} live={live_content_sha256}"
        )
    return live_content_sha256


def _validate_identity_inputs(args: argparse.Namespace) -> None:
    if args.dataset_revision is not None and REVISION_RE.fullmatch(args.dataset_revision) is None:
        raise SystemExit("dataset revision must be an exact lowercase 40-hex commit")
    if (args.dataset_archive is None) != (args.dataset_archive_sha256 is None):
        raise SystemExit("dataset archive and its SHA-256 must be supplied together")
    if args.dataset_archive_sha256 is not None and SHA256_RE.fullmatch(args.dataset_archive_sha256) is None:
        raise SystemExit("dataset archive SHA-256 must be lowercase hexadecimal")
    if (args.dataset_revision is None) == (args.dataset_archive is None):
        raise SystemExit("exactly one dataset revision or archive must be supplied")
    if args.dataset_archive is not None and not args.use_declared_images:
        raise SystemExit("archive-pinned datasets require declared immutable task images")
    if REVISION_RE.fullmatch(args.prime_rl_commit) is None:
        raise SystemExit("Prime RL revision must be an exact lowercase 40-hex commit")
    if REVISION_RE.fullmatch(args.verifiers_commit) is None:
        raise SystemExit("Verifiers revision must be an exact lowercase 40-hex commit")
    if SHA256_RE.fullmatch(args.vmvm_tb_v2_sha256) is None:
        raise SystemExit("VMVM source pin must be a lowercase SHA-256")
    if args.prime_rl_tree_sha256 != CLEAN_TREE_SHA256:
        raise SystemExit("Prime RL source worktree must be clean")
    for path, digest, label in (
        (args.task_file, args.task_file_sha256, "task file"),
        (args.image_manifest, args.image_manifest_sha256, "image manifest"),
        (args.source_wheel_policy, args.source_wheel_policy_sha256, "source-wheel policy"),
    ):
        if (path is None) != (digest is None):
            raise SystemExit(f"{label} and its SHA-256 must be supplied together")
        if digest is not None and SHA256_RE.fullmatch(digest) is None:
            raise SystemExit(f"{label} SHA-256 must be lowercase hexadecimal")
    if (
        args.source_wheel_attestation_sha256 is not None
        and SHA256_RE.fullmatch(args.source_wheel_attestation_sha256) is None
    ):
        raise SystemExit("source-wheel attestation SHA-256 must be lowercase hexadecimal")
    if args.source_wheel_attestation_sha256 is not None and args.source_wheel_policy is None:
        raise SystemExit("source-wheel attestation SHA-256 requires a source-wheel policy")
    if not args.invocation_host.strip():
        raise SystemExit("invocation host must be nonempty")
    if not args.slurm_job_id.isdigit():
        raise SystemExit("Slurm job ID must contain only decimal digits")
    if args.vacli_lease_retries < 0 or args.vacli_max_pull_retries < 0:
        raise SystemExit("VACLI retry counts cannot be negative")
    if args.vacli_max_concurrent_leases < 1 or args.vacli_image_pull_timeout_seconds < 1:
        raise SystemExit("VACLI concurrency and pull timeout must be positive")
    if args.vacli_container_privileged not in {0, 1}:
        raise SystemExit("VACLI privileged mode must be zero or one")


def _run_identity(
    args: argparse.Namespace,
    tasks: list[TerminalBenchTask],
    dataset_content_sha256: str | None,
) -> dict:
    _validate_identity_inputs(args)
    if args.dataset_archive is None:
        if dataset_content_sha256 is not None:
            raise SystemExit("revision-pinned datasets cannot supply an archive content digest")
    elif dataset_content_sha256 is None or SHA256_RE.fullmatch(dataset_content_sha256) is None:
        raise SystemExit("archive-pinned datasets require a verified content SHA-256")
    identity = {
        "schema_version": RUN_IDENTITY_SCHEMA_VERSION,
        "dataset": {
            "path": str(args.dataset_dir.resolve()),
            "revision": args.dataset_revision,
            "archive": {
                "path": str(args.dataset_archive.resolve()) if args.dataset_archive is not None else None,
                "sha256": args.dataset_archive_sha256,
            },
            "content_sha256": dataset_content_sha256,
        },
        "selection": {
            "count": len(tasks),
            "ordered_task_slugs_sha256": _ordered_task_slugs_sha256(tasks),
            "offset": args.offset,
            "limit": args.limit,
            "task_file": {
                "path": str(args.task_file.resolve()) if args.task_file is not None else None,
                "sha256": args.task_file_sha256,
            },
        },
        "images": {
            "prefix": args.image_prefix,
            "tag": args.image_tag,
            "manifest": {
                "path": str(args.image_manifest.resolve()) if args.image_manifest is not None else None,
                "sha256": args.image_manifest_sha256,
            },
            "use_declared_images": args.use_declared_images,
            "enable_compose": args.enable_compose,
        },
        "source": {
            "prime_rl_commit": args.prime_rl_commit,
            "prime_rl_tree_sha256": args.prime_rl_tree_sha256,
            "verifiers_commit": args.verifiers_commit,
            "vmvm_tb_v2_sha256": args.vmvm_tb_v2_sha256,
        },
        "network_semantics": _oracle_network_semantics(args.oracle_solution_network_mode),
        "execution": {
            "max_concurrent": args.max_concurrent,
            "infra_retries": args.infra_retries,
            "setup_timeout_sec": args.setup_timeout,
            "validate_timeout_sec": args.validate_timeout,
            "session_timeout_sec": args.session_timeout,
            "tenant_id": args.tenant_id,
            "lease_ttl": args.lease_ttl,
            "max_session_buffer_size": args.max_session_buffer_size,
            "verifier_runtime_retries": args.verifier_runtime_retries,
            "vacli_lease_retries": args.vacli_lease_retries,
            "vacli_max_concurrent_leases": args.vacli_max_concurrent_leases,
            "vacli_max_pull_retries": args.vacli_max_pull_retries,
            "vacli_image_pull_timeout_seconds": args.vacli_image_pull_timeout_seconds,
            "vacli_container_privileged": bool(args.vacli_container_privileged),
            "timeout_multiplier": args.timeout_multiplier,
            "resource_multiplier": args.resource_multiplier,
            "runtime_image": RUNTIME_IMAGE,
            "runtime_workdir": RUNTIME_WORKDIR,
        },
        "acceptance": {
            "minimum_pass_rate": args.minimum_pass_rate,
            "minimum_valid": args.minimum_valid,
        },
    }
    if args.source_wheel_policy is not None:
        identity["source_wheel_recovery"] = {
            "schema_version": SOURCE_WHEEL_RECOVERY_SCHEMA_VERSION,
            "policy": {
                "path": str(args.source_wheel_policy.resolve()),
                "sha256": args.source_wheel_policy_sha256,
            },
            "attestation": "source_wheel_attestations.json",
            "artifact_download_network": "public-hash-pinned-https",
            "builder_lease_limit": 1,
            "build_dependency_install": "no-system-site-venv-offline-exact-wheel-closure",
            "build_dependency_resolution": "public-binary-only-exact-transitive-policy-closure",
            "build_network": "no-network",
            "build_isolation": True,
            "deterministic_environment_sha256": sha256_bytes(canonical_json(source_build_environment_variables())),
            "source_build_python": "venv-python-isolated-no-site-direct-static-setup",
            "source_build_umask": f"{SOURCE_BUILD_UMASK:04o}",
            "system_site_packages": False,
            "target_install": "offline-no-index-no-deps",
        }
    return identity


def _run_identity_envelope(identity: dict) -> dict:
    return {
        "schema_version": RUN_IDENTITY_SCHEMA_VERSION,
        "run_identity_sha256": hashlib.sha256(_canonical_json(identity)).hexdigest(),
        "identity": identity,
    }


def _has_prior_run_artifacts(output_dir: Path) -> bool:
    filenames = (
        "invocations.jsonl",
        "oracle_network_semantics.json",
        "provenance.txt",
        "results.jsonl",
        "run_config.json",
        "source_wheel_attestations.json",
        "summary.json",
    )
    return (
        any((output_dir / name).exists() for name in filenames)
        or any((output_dir / "tasks").glob("*.json"))
        or (output_dir / "source_wheel_cache").exists()
    )


def _bind_run_identity(output_dir: Path, identity: dict) -> tuple[str, bool]:
    """Create the immutable run identity or validate the exact saved envelope."""
    expected = _run_identity_envelope(identity)
    path = output_dir / "run_identity.json"
    if path.is_file():
        try:
            saved = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid oracle run identity file: {path}") from error
        if not isinstance(saved, dict) or not isinstance(saved.get("identity"), dict):
            raise SystemExit(f"invalid oracle run identity file: {path}")
        saved_digest = hashlib.sha256(_canonical_json(saved["identity"])).hexdigest()
        if saved.get("run_identity_sha256") != saved_digest:
            raise SystemExit(f"invalid oracle run identity digest: {path}")
        if saved != expected:
            raise SystemExit("oracle run identity mismatch; use a fresh output directory")
        return expected["run_identity_sha256"], False

    if _has_prior_run_artifacts(output_dir):
        raise SystemExit("existing oracle artifacts have no immutable run identity; use a fresh output directory")
    _atomic_json(path, expected)
    return expected["run_identity_sha256"], True


def _can_recover_initial_source_wheel_ledger(output_dir: Path) -> bool:
    """Allow only the crash window between identity and empty-ledger publication."""
    try:
        entries = list(output_dir.iterdir())
    except OSError:
        return False
    allowed = {".writer.lock", "run_identity.json"}
    if {entry.name for entry in entries} != allowed:
        return False
    try:
        identity_status = (output_dir / "run_identity.json").lstat()
        lock_status = (output_dir / ".writer.lock").lstat()
    except OSError:
        return False
    return stat.S_ISREG(identity_status.st_mode) and stat.S_ISREG(lock_status.st_mode)


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def _atomic_text(path: Path, data: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(data)
    os.replace(temporary, path)


def _read_result(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _oracle_network_semantics(mode: str) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "trusted_reference_solution": mode,
        "verifier": "declared",
    }


def _bind_oracle_network_semantics(output_dir: Path, mode: str) -> dict[str, str | int]:
    """Create or validate the immutable network-semantics label for a run."""
    expected = _oracle_network_semantics(mode)
    path = output_dir / "oracle_network_semantics.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid oracle network semantics file: {path}") from error
        if existing != expected:
            raise SystemExit(
                "oracle network semantics mismatch: "
                f"saved={existing!r} requested={expected!r}; use a fresh output directory"
            )
        return expected

    status_dir = output_dir / "tasks"
    if (
        (output_dir / "results.jsonl").exists()
        or (output_dir / "summary.json").exists()
        or any(status_dir.glob("*.json"))
    ):
        raise SystemExit(
            "existing oracle results have no immutable network-semantics label; use a fresh output directory"
        )
    _atomic_json(path, expected)
    return expected


def _parse_provenance(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise SystemExit(f"cannot read initial oracle provenance: {path}") from error
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise SystemExit(f"invalid initial oracle provenance: {path}")
        records[key] = value
    return records


def _bind_initial_provenance(
    output_dir: Path,
    identity: dict,
    run_identity_sha256: str,
    *,
    identity_created: bool,
    invocation_host: str,
    slurm_job_id: str,
) -> None:
    path = output_dir / "provenance.txt"
    source = identity["source"]
    network = identity["network_semantics"]
    stable = {
        "prime_rl": source["prime_rl_commit"],
        "prime_rl_tree": source["prime_rl_tree_sha256"],
        "verifiers": source["verifiers_commit"],
        "vmvm_tb_v2": source["vmvm_tb_v2_sha256"],
        "oracle_solution_network_mode": network["trusted_reference_solution"],
        "run_identity_sha256": run_identity_sha256,
    }
    source_wheel_recovery = identity.get("source_wheel_recovery")
    if source_wheel_recovery is not None:
        stable["source_wheel_policy_sha256"] = source_wheel_recovery["policy"]["sha256"]
    expected_keys = {*stable, "host", "slurm_job_id"}
    if path.is_file():
        saved = _parse_provenance(path)
        if (
            set(saved) != expected_keys
            or any(saved.get(key) != value for key, value in stable.items())
            or not saved.get("host", "").strip()
            or not saved.get("slurm_job_id", "").isdigit()
        ):
            raise SystemExit("initial oracle provenance does not match the immutable run identity")
        return
    if not identity_created:
        raise SystemExit("oracle run identity exists without immutable initial provenance")

    records = {
        "prime_rl": stable["prime_rl"],
        "prime_rl_tree": stable["prime_rl_tree"],
        "verifiers": stable["verifiers"],
        "vmvm_tb_v2": stable["vmvm_tb_v2"],
        "host": invocation_host,
        "slurm_job_id": slurm_job_id,
        "oracle_solution_network_mode": stable["oracle_solution_network_mode"],
        "run_identity_sha256": stable["run_identity_sha256"],
    }
    if "source_wheel_policy_sha256" in stable:
        records["source_wheel_policy_sha256"] = stable["source_wheel_policy_sha256"]
    _atomic_text(path, "".join(f"{key}={value}\n" for key, value in records.items()))


def _append_invocation(
    output_dir: Path,
    identity: dict,
    run_identity_sha256: str,
    args: argparse.Namespace,
    *,
    resumed: bool,
) -> None:
    path = output_dir / "invocations.jsonl"
    if path.is_file():
        try:
            records = [json.loads(line) for line in path.read_text().splitlines() if line]
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid oracle invocation history: {path}") from error
        if any(
            not isinstance(record, dict) or record.get("run_identity_sha256") != run_identity_sha256
            for record in records
        ):
            raise SystemExit("oracle invocation history does not match the immutable run identity")
    record = {
        "schema_version": 1,
        "run_identity_sha256": run_identity_sha256,
        "invoked_at": time.time(),
        "resume": resumed,
        "reuse_completed_rows": args.resume,
        "rerun_invalid": args.rerun_invalid,
        "host": args.invocation_host,
        "slurm_job_id": args.slurm_job_id,
        "source": identity["source"],
    }
    if args.source_wheel_policy is not None:
        record["source_wheel_policy_sha256"] = args.source_wheel_policy_sha256
        record["expected_source_wheel_attestation_sha256"] = args.source_wheel_attestation_sha256
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _bind_run_config(output_dir: Path, config: dict, *, identity_created: bool) -> None:
    path = output_dir / "run_config.json"
    if path.is_file():
        try:
            saved = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid oracle run config: {path}") from error
        if not isinstance(saved, dict):
            raise SystemExit(f"invalid oracle run config: {path}")
        saved_started_at = saved.pop("started_at", None)
        expected = dict(config)
        expected.pop("started_at", None)
        if isinstance(saved_started_at, bool) or not isinstance(saved_started_at, (int, float)) or saved != expected:
            raise SystemExit("oracle run config does not match the immutable run identity")
        return
    if not identity_created:
        raise SystemExit("oracle run identity exists without its initial run config")
    _atomic_json(path, config)


def _require_artifact_identity(data: object, run_identity_sha256: str, label: str) -> dict:
    if not isinstance(data, dict) or data.get("run_identity_sha256") != run_identity_sha256:
        raise SystemExit(f"{label} has a different or missing oracle run identity")
    return data


def _validate_existing_artifacts(
    output_dir: Path,
    tasks: list[TerminalBenchTask],
    run_identity_sha256: str,
    network_semantics: dict[str, str | int],
    *,
    source_wheel_policy_enabled: bool = False,
    source_wheel_attestation_sha256: str | None = None,
    known_source_wheel_attestation_sha256s: frozenset[str] = frozenset(),
) -> dict[str, dict]:
    """Validate every existing result before any completed row can be reused."""
    if source_wheel_policy_enabled and (
        not isinstance(source_wheel_attestation_sha256, str)
        or SHA256_RE.fullmatch(source_wheel_attestation_sha256) is None
    ):
        raise SystemExit("current source-wheel attestation is missing or invalid")
    summary_path = output_dir / "summary.json"
    if summary_path.is_file():
        saved_summary = _require_artifact_identity(_read_result(summary_path), run_identity_sha256, "saved summary")
        saved_attestation = saved_summary.get("source_wheel_attestation_sha256")
        if source_wheel_policy_enabled:
            # A preemption can land after a new cache attestation is published
            # but before the progress summary is refreshed. Completed rows are
            # validated independently below and the summary is regenerated
            # under the externally approved current manifest before promotion.
            if not isinstance(saved_attestation, str) or SHA256_RE.fullmatch(saved_attestation) is None:
                raise SystemExit("saved summary has an invalid source-wheel attestation")
        elif "source_wheel_attestation_sha256" in saved_summary:
            raise SystemExit("saved summary unexpectedly enables source-wheel recovery")

    results_path = output_dir / "results.jsonl"
    if results_path.is_file():
        try:
            result_lines = results_path.read_text().splitlines()
            results = [json.loads(line) for line in result_lines]
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid saved oracle results: {results_path}") from error
        if not result_lines:
            raise SystemExit(f"invalid saved oracle results: {results_path}")
        for index, result in enumerate(results, start=1):
            _require_artifact_identity(result, run_identity_sha256, f"saved result row {index}")

    selected = {task.slug: task for task in tasks}
    prior_by_slug: dict[str, dict] = {}
    status_dir = output_dir / "tasks"
    for path in sorted(status_dir.glob("*.json")):
        prior = _require_artifact_identity(_read_result(path), run_identity_sha256, str(path))
        slug = prior.get("slug")
        task = selected.get(slug) if isinstance(slug, str) else None
        if (
            task is None
            or path.name != f"{task.slug}.json"
            or isinstance(prior.get("index"), bool)
            or not isinstance(prior.get("index"), int)
            or prior.get("index") != task.idx
            or prior.get("name") != task.name
            or prior.get("image") != task.image
            or task.slug in prior_by_slug
        ):
            raise SystemExit(f"saved task result does not match the selected task: {path}")
        valid = prior.get("valid")
        reason = prior.get("reason")
        elapsed_sec = prior.get("elapsed_sec")
        attempts = prior.get("attempts")
        error = prior.get("error")
        error_type = prior.get("error_type")
        source_attestations = prior.get("source_wheel_attestation_sha256s")
        if (
            not isinstance(valid, bool)
            or not isinstance(reason, str)
            or reason
            not in {
                "valid",
                "invalid",
                "infrastructure_error",
                "timeout",
                "unsupported",
                "error",
            }
            or (valid and reason != "valid")
            or (not valid and reason == "valid")
            or prior.get("oracle_network_semantics") != network_semantics
            or isinstance(elapsed_sec, bool)
            or not isinstance(elapsed_sec, (int, float))
            or not math.isfinite(elapsed_sec)
            or elapsed_sec < 0
            or isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 1
            or not isinstance(prior.get("infrastructure_failures"), list)
            or not (error is None or isinstance(error, str))
            or not (error_type is None or isinstance(error_type, str))
            or ("last_attempt" in prior and not isinstance(prior["last_attempt"], dict))
            or (not source_wheel_policy_enabled and "source_wheel_attestation_sha256s" in prior)
            or (
                source_wheel_policy_enabled
                and (
                    not isinstance(source_attestations, list)
                    or not all(isinstance(digest, str) for digest in source_attestations)
                    or source_attestations != sorted(set(source_attestations))
                    or not all(digest in known_source_wheel_attestation_sha256s for digest in source_attestations)
                )
            )
        ):
            raise SystemExit(f"saved task result has an invalid terminal status: {path}")
        prior_by_slug[task.slug] = prior
    return prior_by_slug


async def _attempt(
    taskset: TerminalBenchVMVMTaskset,
    task: TerminalBenchTask,
    runtime_config: VMVMConfig,
    setup_timeout: float,
    validate_timeout: float,
    attempt: int,
) -> tuple[bool, dict]:
    runtime = make_runtime(
        resolve_runtime_config(runtime_config, task),
        name=f"tb-oracle-{task.idx}-{attempt}",
    )
    started = time.time()
    descriptor = None
    cleanup_error = None
    try:
        await asyncio.wait_for(runtime.start(), timeout=setup_timeout)
        descriptor = runtime.descriptor
        await asyncio.wait_for(taskset.setup_oracle(task, runtime), timeout=setup_timeout)
        valid = await asyncio.wait_for(taskset.validate(task, runtime), timeout=validate_timeout)
        return bool(valid), {
            "attempt": attempt,
            "runtime": descriptor,
            "elapsed_sec": round(time.time() - started, 3),
        }
    finally:
        try:
            try:
                await taskset.cleanup(task, None, runtime)
            except Exception as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                logger.warning("%s taskset cleanup failed: %s", task.name, cleanup_error)
        finally:
            try:
                await asyncio.shield(runtime.stop())
            except Exception as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                logger.warning("%s cleanup failed: %s", task.name, cleanup_error)


async def _validate_one(
    taskset: TerminalBenchVMVMTaskset,
    task: TerminalBenchTask,
    runtime_config: VMVMConfig,
    args: argparse.Namespace,
) -> dict:
    started = time.time()
    infrastructure_failures: list[dict] = []
    for attempt in range(1, args.infra_retries + 2):
        try:
            valid, detail = await _attempt(
                taskset,
                task,
                runtime_config,
                args.setup_timeout,
                args.validate_timeout,
                attempt,
            )
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": valid,
                "reason": "valid" if valid else "invalid",
                "error": None,
                "error_type": None,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "last_attempt": detail,
                "infrastructure_failures": infrastructure_failures,
            }
        except SandboxError as error:
            failure = {
                "attempt": attempt,
                "error_type": type(error).__name__,
                "error": str(error),
            }
            infrastructure_failures.append(failure)
            if attempt > args.infra_retries:
                return {
                    "index": task.idx,
                    "name": task.name,
                    "slug": task.slug,
                    "image": task.image,
                    "valid": False,
                    "reason": "infrastructure_error",
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "elapsed_sec": round(time.time() - started, 3),
                    "attempts": attempt,
                    "infrastructure_failures": infrastructure_failures,
                }
            delay = min(30.0, 2 ** (attempt - 1) + random.random())
            logger.warning(
                "%s VMVM failure; retrying entire oracle in %.1fs: %s",
                task.name,
                delay,
                error,
            )
            await asyncio.sleep(delay)
        except asyncio.TimeoutError as error:
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "timeout",
                "error": str(error) or "oracle stage timed out",
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
        except (OracleFailure, UnsupportedTaskError) as error:
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "unsupported" if isinstance(error, UnsupportedTaskError) else "invalid",
                "error": str(error),
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
        except Exception as error:
            logger.exception("%s oracle error", task.name)
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "error",
                "error": str(error),
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
    raise AssertionError("unreachable")


def _summary(
    results: list[dict],
    selected: int,
    network_semantics: dict[str, str | int],
    run_identity_sha256: str,
    source_wheel_attestation_sha256: str | None = None,
) -> dict:
    reasons: dict[str, int] = {}
    for result in results:
        reasons[result["reason"]] = reasons.get(result["reason"], 0) + 1
    passed = sum(result["valid"] for result in results)
    summary = {
        "selected": selected,
        "completed": len(results),
        "passed": passed,
        "pass_rate": passed / selected if selected else 0.0,
        "reasons": reasons,
        "oracle_network_semantics": network_semantics,
        "run_identity_sha256": run_identity_sha256,
    }
    if source_wheel_attestation_sha256 is not None:
        summary["source_wheel_attestation_sha256"] = source_wheel_attestation_sha256
    return summary


def _meets_acceptance(summary: dict, minimum_pass_rate: float, minimum_valid: int) -> bool:
    return summary["pass_rate"] >= minimum_pass_rate and summary["passed"] >= minimum_valid


async def _run(args: argparse.Namespace) -> int:
    _validate_identity_inputs(args)
    dataset_content_sha256 = _validated_dataset_content_sha256(args)
    requested = _requested_tasks(args)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = (output_dir / ".writer.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise SystemExit(f"another oracle runner owns {output_dir}") from error
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=args.dataset_dir,
            dataset_revision=args.dataset_revision,
            tasks=requested,
            task_file=args.task_file,
            task_file_sha256=args.task_file_sha256,
            image_prefix=args.image_prefix,
            image_tag=args.image_tag,
            image_manifest=args.image_manifest,
            image_manifest_sha256=args.image_manifest_sha256,
            use_declared_images=args.use_declared_images,
            enable_compose=args.enable_compose,
            verifier_runtime_retries=args.verifier_runtime_retries,
            timeout_multiplier=args.timeout_multiplier,
            resource_multiplier=args.resource_multiplier,
            oracle_solution_network_mode=args.oracle_solution_network_mode,
            oracle_source_wheel_policy=args.source_wheel_policy,
            oracle_source_wheel_policy_sha256=args.source_wheel_policy_sha256,
            oracle_source_wheel_attestation_path=(
                output_dir / "source_wheel_attestations.json" if args.source_wheel_policy is not None else None
            ),
            oracle_source_wheel_attestation_sha256=args.source_wheel_attestation_sha256,
            ignore_dockerfile=True,
        )
    )
    tasks = taskset.load_tasks()
    tasks = tasks[args.offset : args.offset + args.limit if args.limit is not None else None]
    if dataset_content_sha256 is not None:
        observed_content_sha256 = _filesystem_tree_digest(args.dataset_dir.resolve())
        if observed_content_sha256 != dataset_content_sha256:
            raise SystemExit("dataset tree changed while oracle inputs were being resolved")
    if not tasks:
        raise SystemExit("no tasks selected")
    if args.minimum_valid > len(tasks):
        raise SystemExit(f"--minimum-valid={args.minimum_valid} exceeds {len(tasks)} selected tasks")

    runtime_config = VMVMConfig(
        image=RUNTIME_IMAGE,
        workdir=RUNTIME_WORKDIR,
        session_timeout=args.session_timeout,
        tenant_id=args.tenant_id,
        lease_ttl=args.lease_ttl,
        max_session_buffer_size=args.max_session_buffer_size,
    )
    taskset.revalidate_source_wheel_attestations()

    identity = _run_identity(args, tasks, dataset_content_sha256)
    run_identity_sha256, identity_created = _bind_run_identity(output_dir, identity)
    taskset.initialize_source_wheel_attestations(
        allow_create=identity_created or _can_recover_initial_source_wheel_ledger(output_dir)
    )
    _bind_initial_provenance(
        output_dir,
        identity,
        run_identity_sha256,
        identity_created=identity_created,
        invocation_host=args.invocation_host,
        slurm_job_id=args.slurm_job_id,
    )
    network_semantics = _bind_oracle_network_semantics(output_dir, args.oracle_solution_network_mode)

    run_config = {
        "schema_version": 1,
        "run_identity_sha256": run_identity_sha256,
        "dataset_dir": str(args.dataset_dir.resolve()),
        "dataset_revision": args.dataset_revision,
        "dataset_archive": str(args.dataset_archive.resolve()) if args.dataset_archive is not None else None,
        "dataset_archive_sha256": args.dataset_archive_sha256,
        "dataset_content_sha256": dataset_content_sha256,
        "task_file": str(args.task_file.resolve()) if args.task_file is not None else None,
        "task_file_sha256": args.task_file_sha256,
        "image_prefix": args.image_prefix,
        "image_tag": args.image_tag,
        "image_manifest": str(args.image_manifest.resolve()) if args.image_manifest is not None else None,
        "image_manifest_sha256": args.image_manifest_sha256,
        "use_declared_images": args.use_declared_images,
        "enable_compose": args.enable_compose,
        "max_concurrent": args.max_concurrent,
        "infra_retries": args.infra_retries,
        "setup_timeout": args.setup_timeout,
        "validate_timeout": args.validate_timeout,
        "session_timeout": args.session_timeout,
        "tenant_id": args.tenant_id,
        "lease_ttl": args.lease_ttl,
        "max_session_buffer_size": args.max_session_buffer_size,
        "verifier_runtime_retries": args.verifier_runtime_retries,
        "vacli_lease_retries": args.vacli_lease_retries,
        "vacli_max_concurrent_leases": args.vacli_max_concurrent_leases,
        "vacli_max_pull_retries": args.vacli_max_pull_retries,
        "vacli_image_pull_timeout_seconds": args.vacli_image_pull_timeout_seconds,
        "vacli_container_privileged": bool(args.vacli_container_privileged),
        "timeout_multiplier": args.timeout_multiplier,
        "resource_multiplier": args.resource_multiplier,
        "minimum_pass_rate": args.minimum_pass_rate,
        "minimum_valid": args.minimum_valid,
        "oracle_solution_network_mode": args.oracle_solution_network_mode,
        "oracle_network_semantics": network_semantics,
        "selected_tasks": len(tasks),
        "started_at": time.time(),
    }
    if args.source_wheel_policy is not None:
        run_config["source_wheel_policy"] = str(args.source_wheel_policy.resolve())
        run_config["source_wheel_policy_sha256"] = args.source_wheel_policy_sha256
        run_config["source_wheel_attestation"] = str(output_dir / "source_wheel_attestations.json")
    _bind_run_config(output_dir, run_config, identity_created=identity_created)

    prior_by_slug = _validate_existing_artifacts(
        output_dir,
        tasks,
        run_identity_sha256,
        network_semantics,
        source_wheel_policy_enabled=args.source_wheel_policy is not None,
        source_wheel_attestation_sha256=taskset.source_wheel_attestation_sha256,
        known_source_wheel_attestation_sha256s=taskset.known_source_wheel_attestation_sha256s,
    )
    status_dir = output_dir / "tasks"
    status_dir.mkdir(exist_ok=True)

    pending: list[TerminalBenchTask] = []
    results_by_slug: dict[str, dict] = {}
    for task in tasks:
        prior = prior_by_slug.get(task.slug) if args.resume else None
        if prior is not None and prior.get("oracle_network_semantics") != network_semantics:
            raise SystemExit(
                f"{task.slug}: saved task result has different or missing oracle network semantics; "
                "use a fresh output directory"
            )
        if prior is not None and (prior.get("valid") or not args.rerun_invalid):
            results_by_slug[task.slug] = prior
        else:
            pending.append(task)

    _append_invocation(
        output_dir,
        identity,
        run_identity_sha256,
        args,
        resumed=not identity_created,
    )
    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def one(task: TerminalBenchTask) -> dict:
        async with semaphore:
            logger.info("start idx=%d task=%s", task.idx, task.name)
            source_wheel_attestations: list[str] = []
            if args.source_wheel_policy is not None:
                taskset.begin_task_dependency_attestations(task)
                try:
                    result = await _validate_one(taskset, task, runtime_config, args)
                finally:
                    source_wheel_attestations = taskset.finish_task_dependency_attestations(task)
            else:
                result = await _validate_one(taskset, task, runtime_config, args)
            result["oracle_network_semantics"] = network_semantics
            result["run_identity_sha256"] = run_identity_sha256
            if args.source_wheel_policy is not None:
                result["source_wheel_attestation_sha256s"] = source_wheel_attestations
            _atomic_json(status_dir / f"{task.slug}.json", result)
            logger.info(
                "done idx=%d task=%s reason=%s elapsed=%.1fs",
                task.idx,
                task.name,
                result["reason"],
                result["elapsed_sec"],
            )
            return result

    logger.info("selected=%d resumed=%d pending=%d", len(tasks), len(results_by_slug), len(pending))
    futures = [asyncio.create_task(one(task)) for task in pending]
    try:
        for future in asyncio.as_completed(futures):
            result = await future
            results_by_slug[result["slug"]] = result
            ordered = [results_by_slug[task.slug] for task in tasks if task.slug in results_by_slug]
            _atomic_json(
                output_dir / "summary.json",
                _summary(
                    ordered,
                    len(tasks),
                    network_semantics,
                    run_identity_sha256,
                    taskset.source_wheel_attestation_sha256,
                ),
            )

        results = [results_by_slug[task.slug] for task in tasks]
        with (output_dir / "results.jsonl.tmp").open("w") as handle:
            for result in results:
                handle.write(json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(output_dir / "results.jsonl.tmp", output_dir / "results.jsonl")
        summary = _summary(
            results,
            len(tasks),
            network_semantics,
            run_identity_sha256,
            taskset.source_wheel_attestation_sha256,
        )
        summary["finished_at"] = time.time()
        _atomic_json(output_dir / "summary.json", summary)
        logger.info("oracle summary: %s", json.dumps(summary, sort_keys=True))
        accepted = _meets_acceptance(summary, args.minimum_pass_rate, args.minimum_valid)
        return 0 if accepted else 2
    finally:
        for future in futures:
            future.cancel()
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
        await taskset.close()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        logger.warning("interrupted; completed per-task results remain resumable")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
