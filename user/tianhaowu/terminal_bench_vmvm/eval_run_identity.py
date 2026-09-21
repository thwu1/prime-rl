#!/usr/bin/env python3
"""Resolve and bind immutable, credential-free metadata for VMVM eval runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import stat
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit

import tomli_w
from deployment_endpoint import (
    EndpointBindingError,
    load_deployment_endpoint,
    validate_endpoint_binding,
)
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    request_timeout_for_model,
    revalidate_deployment_proxy_policy,
    validate_deployment_proxy_policy_snapshot,
    validate_proxy_policy_binding,
)
from guard_success_receipt import (
    GuardReceiptError,
    load_guard_success_receipt,
    validate_guard_success_linkage,
)
from inference_route_generation import (
    RouteGenerationError,
    validate_readiness_route_generation,
    validate_route_generation,
)
from pydantic_config import cli
from smoke_qualification import (
    SmokeQualificationError,
    validate_smoke_qualification,
    validate_target_evaluator_compatibility,
)
from verifiers.v1.cli.resolve import narrow_config
from verifiers.v1.configs.eval import EvalConfig

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
METADATA_ID_RE = re.compile(r"[A-Za-z0-9._:-]+")
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
EXPECTED_DENYLIST = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
EXPECTED_MODEL_IO_CONTRACT = {
    "provider_route": "/chat/completions",
    "request_model": "Kimi-K3",
    "response_model": "Kimi-K3",
    "request_reasoning_effort": "max",
    "request_chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
}
MAX_METADATA_BYTES = 64 * 1024 * 1024
KIMI_REQUEST_TIMEOUT_SECONDS = 43_200
KIMI_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS = 15_000
KIMI_DIRECT_SCORED_SMOKE_REQUEST_TIMEOUT_SECONDS = 10_800
KIMI_DIRECT_SCORED_SMOKE_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS = 9_600
KIMI_CONNECT_TIMEOUT_SECONDS = 120
KIMI_SETUP_TIMEOUT_SECONDS = 3_600
KIMI_FINALIZE_TIMEOUT_SECONDS = 3_600
KIMI_SCORING_TIMEOUT_SECONDS = 21_600
KIMI_TIMEOUT_PROFILES = {
    "smoke": {"rollout_timeout": 28_800, "session_timeout": 32_400},
    "full": {"rollout_timeout": 36_000, "session_timeout": 43_200},
    "quick": {"rollout_timeout": 900, "session_timeout": 2_400},
    "diagnostic": {"rollout_timeout": 300, "session_timeout": 600},
    "reward_diagnostic": {"rollout_timeout": 600, "session_timeout": 600},
    "direct_scored_smoke": {"rollout_timeout": 9_000, "session_timeout": 10_800},
}
KIMI_FULL_RETRY_EXCEPTIONS = frozenset({"ProviderError", "SandboxError", "TunnelError", "InterceptionError"})
VMVM_HOST_CLEANUP_CONTRACT = {
    "kind": "vacli-release-on-exit-v1",
    "receipt": "private-aggregate-jsonl",
    "release_on_exit_completed": True,
    "remote_deletion_verified": False,
}
SANDOQ_VENDOR_RELATIVE = Path("extensions/sandoq")
SANDOQ_UPSTREAM_COMMIT = "4890302104d76220cef791c86d2009168597d35f"
SANDOQ_UPSTREAM_TREE = "33f092a3982916660e12f472588e6ce34a906fc2"
SANDOQ_UPSTREAM_SUBTREE = "10b5bd9bbc76eba1b8253637e1869d6b63b7fc42"
SANDOQ_UPSTREAM_INVENTORY_SHA256 = "5db69d90ddd34cfbfdcffdacab09353e8be22e917f894e33ddafb5020ca43e73"
DIRECT_KIMI_ROLES = frozenset({"kimi-direct-smoke", "kimi-direct-tb4"})
DIRECT_ROLES = frozenset({"qwen-direct", *DIRECT_KIMI_ROLES})


class EvalIdentityError(ValueError):
    """The proposed evaluation cannot be bound to immutable provenance."""


def validate_kimi_timeout_contract(
    config: dict[str, Any],
    *,
    required_profile: str | None = None,
) -> dict[str, int | float]:
    """Validate one exact, reviewed timeout envelope for Kimi generations."""

    if required_profile is not None and required_profile not in KIMI_TIMEOUT_PROFILES:
        raise EvalIdentityError("kimi_timeout_profile_invalid")

    client = config.get("client")
    harness = config.get("harness")
    timeouts = config.get("timeout")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    overrides = harness.get("config_overrides") if isinstance(harness, dict) else None
    if not all(isinstance(value, dict) for value in (client, harness, timeouts, runtime)):
        raise EvalIdentityError("kimi_timeout_contract_invalid")
    assert isinstance(client, dict) and isinstance(timeouts, dict) and isinstance(runtime, dict)
    assert isinstance(harness, dict)
    direct_scored_smoke = required_profile == "direct_scored_smoke"
    expected_request_timeout = (
        KIMI_DIRECT_SCORED_SMOKE_REQUEST_TIMEOUT_SECONDS if direct_scored_smoke else KIMI_REQUEST_TIMEOUT_SECONDS
    )
    expected_host_harness_request_timeout = (
        KIMI_DIRECT_SCORED_SMOKE_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
        if direct_scored_smoke
        else KIMI_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
    )
    host_harness = harness.get("id") == "terminal-bench-sandoq-host"
    if host_harness:
        harness_timeout_valid = overrides is None and (
            harness.get("request_timeout_seconds") == expected_host_harness_request_timeout
        )
        harness_request_timeout = expected_host_harness_request_timeout
    else:
        if not isinstance(overrides, list) or any(not isinstance(value, str) for value in overrides):
            raise EvalIdentityError("kimi_timeout_contract_invalid")
        harness_timeout_override = f"model.model_kwargs.timeout={expected_request_timeout}"
        harness_timeout_entries = [
            value for value in overrides if value.startswith("model.model_kwargs.timeout=")
        ]
        harness_timeout_valid = harness_timeout_entries == [harness_timeout_override]
        harness_request_timeout = KIMI_REQUEST_TIMEOUT_SECONDS
    request_timeout = client.get("timeout")
    connect_timeout = client.get("connect_timeout")
    setup_timeout = timeouts.get("setup")
    rollout_timeout = timeouts.get("rollout")
    finalize_timeout = timeouts.get("finalize")
    scoring_timeout = timeouts.get("scoring")
    session_timeout = runtime.get("session_timeout")
    observed_profile = {
        "rollout_timeout": rollout_timeout,
        "session_timeout": session_timeout,
    }
    allowed_profiles = (
        {required_profile: KIMI_TIMEOUT_PROFILES[required_profile]}
        if required_profile is not None
        else {key: KIMI_TIMEOUT_PROFILES[key] for key in ("smoke", "full")}
    )

    bounded_smoke = required_profile in {
        "quick",
        "diagnostic",
        "reward_diagnostic",
        "direct_scored_smoke",
    }
    tight_diagnostic = required_profile in {"diagnostic", "reward_diagnostic"}
    setup_timeout_seconds = 180 if tight_diagnostic else 600 if bounded_smoke else KIMI_SETUP_TIMEOUT_SECONDS
    finalize_timeout_seconds = 60 if tight_diagnostic else 300 if bounded_smoke else KIMI_FINALIZE_TIMEOUT_SECONDS
    if direct_scored_smoke:
        scoring_timeout_seconds = 900
    else:
        scoring_timeout_seconds = 120 if tight_diagnostic else 600 if bounded_smoke else KIMI_SCORING_TIMEOUT_SECONDS

    def exact_number(value: object, expected: int) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value == expected
        )

    if (
        not exact_number(request_timeout, expected_request_timeout)
        or not harness_timeout_valid
        or not exact_number(connect_timeout, KIMI_CONNECT_TIMEOUT_SECONDS)
        or not exact_number(setup_timeout, setup_timeout_seconds)
        or not any(exact_number(rollout_timeout, profile["rollout_timeout"]) for profile in allowed_profiles.values())
        or not exact_number(finalize_timeout, finalize_timeout_seconds)
        or not exact_number(scoring_timeout, scoring_timeout_seconds)
        or not any(exact_number(session_timeout, profile["session_timeout"]) for profile in allowed_profiles.values())
        or observed_profile not in allowed_profiles.values()
    ):
        raise EvalIdentityError("kimi_timeout_contract_invalid")
    return {
        "request_timeout": request_timeout,
        "harness_request_timeout": harness_request_timeout,
        "connect_timeout": connect_timeout,
        "setup_timeout": setup_timeout,
        "rollout_timeout": rollout_timeout,
        "finalize_timeout": finalize_timeout,
        "scoring_timeout": scoring_timeout,
        "session_timeout": session_timeout,
    }


def validate_kimi_retry_contract(config: dict[str, Any]) -> dict[str, Any]:
    """Require the narrow, bounded whole-rollout retry policy reviewed for Kimi."""

    retries = config.get("retries")
    rollout = retries.get("rollout") if isinstance(retries, dict) else None
    expected = KIMI_FULL_RETRY_EXCEPTIONS
    include = rollout.get("include") if isinstance(rollout, dict) else None
    exclude = rollout.get("exclude") if isinstance(rollout, dict) else None
    harness = config.get("harness")
    host_harness = isinstance(harness, dict) and harness.get("id") == "terminal-bench-sandoq-host"
    expected_retries = 0 if host_harness else 2
    if (
        not isinstance(retries, dict)
        or set(retries) != {"rollout"}
        or not isinstance(rollout, dict)
        or not {"max_retries", "include"}.issubset(rollout)
        or not set(rollout).issubset({"max_retries", "include", "exclude"})
        or type(rollout.get("max_retries")) is not int
        or rollout["max_retries"] != expected_retries
        or not isinstance(include, list)
        or any(not isinstance(value, str) for value in include)
        or len(include) != len(expected)
        or len(set(include)) != len(include)
        or set(include) != expected
        or exclude not in (None, [])
    ):
        raise EvalIdentityError("kimi_retry_contract_invalid")
    return {
        "max_retries": expected_retries,
        "include": sorted(expected),
        "exclude": [],
    }


def validate_kimi_steady_state_concurrency_contract(config: dict[str, Any]) -> dict[str, int]:
    """Require aligned rollout, multiplex, and HTTP capacity for Mobius Kimi runs."""

    client = config.get("client")
    if not isinstance(client, dict):
        raise EvalIdentityError("kimi_steady_state_concurrency_invalid")
    execution = {
        "http_max_connections": client.get("max_connections"),
        "http_max_keepalive_connections": client.get("max_keepalive_connections"),
        "multiplex": config.get("multiplex"),
        "rollout_concurrency": config.get("max_concurrent"),
    }
    if any(type(value) is not int or value < 1 for value in execution.values()):
        raise EvalIdentityError("kimi_steady_state_concurrency_invalid")
    if len(set(execution.values())) != 1:
        raise EvalIdentityError("kimi_steady_state_concurrency_mismatch")
    return execution


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path, *, label: str, limit: int = MAX_METADATA_BYTES) -> bytes:
    try:
        with path.open("rb") as handle:
            value = handle.read(limit + 1)
    except OSError as error:
        raise EvalIdentityError(f"{label}_unreadable") from error
    if len(value) > limit:
        raise EvalIdentityError(f"{label}_too_large")
    return value


def _sha256_file(path: Path, *, label: str) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise EvalIdentityError(f"{label}_unreadable")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        raise EvalIdentityError(f"{label}_unreadable") from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise EvalIdentityError(f"{label}_changed")
    return digest.hexdigest()


def _resolved_file(path: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise EvalIdentityError(f"{label}_unreadable") from error
    if not resolved.is_file():
        raise EvalIdentityError(f"{label}_unreadable")
    return resolved


def _artifact(path: Path, expected_sha256: str, *, label: str) -> dict[str, str]:
    if not isinstance(expected_sha256, str) or SHA256_RE.fullmatch(expected_sha256) is None:
        raise EvalIdentityError(f"{label}_sha256_invalid")
    resolved = _resolved_file(path, label=label)
    if _sha256_file(resolved, label=label) != expected_sha256:
        raise EvalIdentityError(f"{label}_sha256_mismatch")
    return {"path": str(resolved), "sha256": expected_sha256}


def _json_artifact(record: dict[str, str], *, label: str) -> dict[str, Any]:
    raw = _read_bytes(Path(record["path"]), label=label)
    if _sha256_bytes(raw) != record["sha256"]:
        raise EvalIdentityError(f"{label}_sha256_mismatch")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvalIdentityError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise EvalIdentityError(f"{label}_invalid")
    return value


def _git_output(root: Path, *args: str, label: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise EvalIdentityError(f"{label}_unverifiable") from error


def _vmvm_source_sha256(project_root: Path) -> str:
    source_root = project_root / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    paths = sorted(source_root.glob("*.py"))
    if not paths:
        raise EvalIdentityError("vmvm_source_unreadable")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(project_root).as_posix()
        digest.update(f"{_sha256_file(path, label='vmvm_source')}  {relative}\n".encode())
    return digest.hexdigest()


def _sandoq_site_sha256(root: Path) -> str:
    if not root.is_dir():
        raise EvalIdentityError("sandoq_site_unreadable")
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix != ".pyc" and not path.name.startswith(".")
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise EvalIdentityError("sandoq_site_empty")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(f"{_sha256_file(path, label='sandoq_site')}  {relative}\n".encode())
    return digest.hexdigest()


def _sandoq_host_harness_sha256(project_root: Path) -> str:
    path = (
        project_root
        / "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_host_harness.py"
    )
    return _sha256_file(path, label="sandoq_host_harness")


def _validate_vendored_sandoq_provider(
    project_root: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> None:
    if expected_commit != SANDOQ_UPSTREAM_COMMIT or expected_tree != SANDOQ_UPSTREAM_TREE:
        raise EvalIdentityError("sandoq_provider_mismatch")
    vendor_root = project_root / SANDOQ_VENDOR_RELATIVE
    upstream = vendor_root / "UPSTREAM.md"
    try:
        metadata = upstream.lstat()
        body = upstream.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EvalIdentityError("sandoq_provider_mismatch") from error
    expected_markers = (
        SANDOQ_UPSTREAM_COMMIT,
        SANDOQ_UPSTREAM_TREE,
        SANDOQ_UPSTREAM_SUBTREE,
        SANDOQ_UPSTREAM_INVENTORY_SHA256,
    )
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or any(body.count(marker) != 1 for marker in expected_markers)
    ):
        raise EvalIdentityError("sandoq_provider_mismatch")
    listing = _git_output(
        project_root,
        "ls-tree",
        "-r",
        "HEAD",
        "--",
        SANDOQ_VENDOR_RELATIVE.as_posix(),
        label="sandoq_provider",
    ).splitlines()
    inventory = [line for line in listing if not line.endswith("\textensions/sandoq/UPSTREAM.md")]
    if (
        len(inventory) != 43
        or _sha256_bytes(("\n".join(inventory) + "\n").encode()) != SANDOQ_UPSTREAM_INVENTORY_SHA256
    ):
        raise EvalIdentityError("sandoq_provider_mismatch")


def _source_identity(args: argparse.Namespace) -> dict[str, str]:
    root = args.project_root.resolve(strict=True)
    revisions = {
        "prime_rl_commit": (root, args.prime_rl_commit),
        "verifiers_commit": (root / "deps/verifiers", args.verifiers_commit),
        "renderers_commit": (root / "deps/renderers", args.renderers_commit),
    }
    for label, (repository, expected) in revisions.items():
        if REVISION_RE.fullmatch(expected) is None:
            raise EvalIdentityError(f"{label}_invalid")
        if _git_output(repository, "rev-parse", "--verify", "HEAD", label=label).strip() != expected:
            raise EvalIdentityError(f"{label}_mismatch")
        if _git_output(
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label=label,
        ).strip():
            raise EvalIdentityError(f"{label}_worktree_not_clean")
    for label, value in (
        ("prime_rl_tree_sha256", args.prime_rl_tree_sha256),
        ("verifiers_tree_sha256", args.verifiers_tree_sha256),
        ("renderers_tree_sha256", args.renderers_tree_sha256),
    ):
        if value != CLEAN_TREE_SHA256:
            raise EvalIdentityError(f"{label}_not_clean")
    identity = {
        "project_root": str(root),
        "prime_rl_commit": args.prime_rl_commit,
        "prime_rl_tree_sha256": args.prime_rl_tree_sha256,
        "verifiers_commit": args.verifiers_commit,
        "verifiers_tree_sha256": args.verifiers_tree_sha256,
        "renderers_commit": args.renderers_commit,
        "renderers_tree_sha256": args.renderers_tree_sha256,
    }
    if args.sandbox_provider == "vmvm":
        observed_vmvm = _vmvm_source_sha256(root)
        if args.vmvm_tb_v2_sha256 != observed_vmvm:
            raise EvalIdentityError("vmvm_source_sha256_mismatch")
        return {**identity, "vmvm_tb_v2_sha256": args.vmvm_tb_v2_sha256}

    if REVISION_RE.fullmatch(args.sandoq_provider_commit or "") is None:
        raise EvalIdentityError("sandoq_provider_commit_invalid")
    _validate_vendored_sandoq_provider(
        root,
        expected_commit=args.sandoq_provider_commit,
        expected_tree=args.sandoq_provider_tree,
    )
    if not args.sandoq_client_version or any(character in args.sandoq_client_version for character in "\r\n="):
        raise EvalIdentityError("sandoq_client_version_invalid")
    try:
        observed_client_version = importlib.metadata.version("sandoq-client")
    except importlib.metadata.PackageNotFoundError as error:
        raise EvalIdentityError("sandoq_client_unavailable") from error
    if args.sandoq_client_version != observed_client_version:
        raise EvalIdentityError("sandoq_client_version_mismatch")
    observed_site_sha256 = _sandoq_site_sha256(args.sandoq_site)
    if args.sandoq_site_sha256 != observed_site_sha256:
        raise EvalIdentityError("sandoq_site_sha256_mismatch")
    if SHA256_RE.fullmatch(args.derived_image_manifest_sha256 or "") is None:
        raise EvalIdentityError("derived_image_manifest_sha256_invalid")
    return {
        **identity,
        "sandbox_provider": "sandoq",
        "sandoq_provider_commit": args.sandoq_provider_commit,
        "sandoq_provider_tree": args.sandoq_provider_tree,
        "sandoq_client_version": args.sandoq_client_version,
        "sandoq_site": str(args.sandoq_site.resolve(strict=True)),
        "sandoq_site_sha256": args.sandoq_site_sha256,
        "sandoq_host_harness_sha256": _sandoq_host_harness_sha256(root),
        "derived_image_manifest_sha256": args.derived_image_manifest_sha256,
    }


def _tree_digest(root: Path) -> str:
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError as error:
        raise EvalIdentityError("dataset_tree_unreadable") from error
    if not paths:
        raise EvalIdentityError("dataset_tree_empty")
    entries: dict[str, dict[str, Any]] = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            before = path.lstat()
            entry: dict[str, Any] = {"path": relative, "mode": stat.S_IMODE(before.st_mode)}
            if stat.S_ISDIR(before.st_mode):
                entry["type"] = "directory"
            elif stat.S_ISREG(before.st_mode):
                entry.update(
                    {
                        "type": "file",
                        "size": before.st_size,
                        "sha256": _sha256_file(path, label="dataset_tree"),
                    }
                )
            elif stat.S_ISLNK(before.st_mode):
                entry.update({"type": "symlink", "target": os.readlink(path)})
            else:
                raise EvalIdentityError("dataset_tree_entry_unsupported")
            after = path.lstat()
        except OSError as error:
            raise EvalIdentityError("dataset_tree_unreadable") from error
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
            raise EvalIdentityError("dataset_tree_changed")
        entries[relative] = entry
    try:
        final_paths = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    except OSError as error:
        raise EvalIdentityError("dataset_tree_unreadable") from error
    if final_paths != set(entries):
        raise EvalIdentityError("dataset_tree_changed")
    digest = hashlib.sha256()
    for relative in sorted(entries):
        digest.update(canonical_json(entries[relative]))
        digest.update(b"\n")
    return digest.hexdigest()


def _archive_tasks_tree_digest(path: Path) -> str:
    entries: dict[str, dict[str, Any]] = {}
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                member_path = PurePosixPath(member.name)
                if not member_path.parts or member_path.parts[0] != "tasks":
                    continue
                if len(member_path.parts) == 1:
                    continue
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise EvalIdentityError("dataset_archive_task_path_unsafe")
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative in entries:
                    raise EvalIdentityError("dataset_archive_task_path_duplicate")
                entry: dict[str, Any] = {
                    "path": relative,
                    "mode": member.mode & 0o7777,
                }
                if member.isdir():
                    entry["type"] = "directory"
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise EvalIdentityError("dataset_archive_member_unreadable")
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                    if size != member.size:
                        raise EvalIdentityError("dataset_archive_member_size_mismatch")
                    entry.update({"type": "file", "size": size, "sha256": digest.hexdigest()})
                elif member.issym():
                    entry.update({"type": "symlink", "target": member.linkname})
                else:
                    raise EvalIdentityError("dataset_archive_task_entry_unsupported")
                entries[relative] = entry
    except (OSError, tarfile.TarError) as error:
        raise EvalIdentityError("dataset_archive_unreadable") from error
    if not entries:
        raise EvalIdentityError("dataset_archive_tasks_payload_empty")
    digest = hashlib.sha256()
    for relative in sorted(entries):
        digest.update(canonical_json(entries[relative]))
        digest.update(b"\n")
    return digest.hexdigest()


def _verified_archive_content(
    archive_path: Path,
    archive_sha256: str,
    content_sha256: str,
) -> dict[str, str]:
    try:
        before = archive_path.resolve(strict=True).stat()
    except (OSError, RuntimeError) as error:
        raise EvalIdentityError("dataset_archive_unreadable") from error
    archive = _artifact(archive_path, archive_sha256, label="dataset_archive")
    observed_content_sha256 = _archive_tasks_tree_digest(Path(archive["path"]))
    try:
        after = Path(archive["path"]).stat()
    except OSError as error:
        raise EvalIdentityError("dataset_archive_unreadable") from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise EvalIdentityError("dataset_archive_changed")
    if observed_content_sha256 != content_sha256:
        raise EvalIdentityError("dataset_archive_content_sha256_mismatch")
    return archive


def _dataset_identity(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        raise EvalIdentityError("resolved_taskset_invalid")
    dataset_value = taskset.get("dataset_dir")
    if not isinstance(dataset_value, str) or not dataset_value:
        raise EvalIdentityError("resolved_dataset_path_invalid")
    dataset_path = Path(dataset_value).resolve(strict=True)
    revision_mode = args.dataset_revision is not None
    archive_values = (args.dataset_archive, args.dataset_archive_sha256, args.dataset_content_sha256)
    if revision_mode:
        if any(value is not None for value in archive_values):
            raise EvalIdentityError("dataset_authority_conflict")
        if REVISION_RE.fullmatch(args.dataset_revision) is None:
            raise EvalIdentityError("dataset_revision_invalid")
        if taskset.get("dataset_revision") != args.dataset_revision:
            raise EvalIdentityError("dataset_revision_config_mismatch")
        if (
            _git_output(dataset_path, "rev-parse", "--verify", "HEAD", label="dataset_revision").strip()
            != args.dataset_revision
        ):
            raise EvalIdentityError("dataset_revision_mismatch")
        if _git_output(
            dataset_path,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label="dataset_revision",
        ).strip():
            raise EvalIdentityError("dataset_worktree_not_clean")
        return {
            "kind": "git_revision",
            "path": str(dataset_path),
            "revision": args.dataset_revision,
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
        }

    if any(value is None for value in archive_values):
        raise EvalIdentityError("dataset_archive_authority_incomplete")
    if taskset.get("dataset_revision") is not None or taskset.get("use_declared_images") is not True:
        raise EvalIdentityError("dataset_archive_config_invalid")
    assert args.dataset_archive is not None
    assert args.dataset_archive_sha256 is not None
    assert args.dataset_content_sha256 is not None
    if SHA256_RE.fullmatch(args.dataset_content_sha256) is None:
        raise EvalIdentityError("dataset_content_sha256_invalid")
    archive = _verified_archive_content(
        args.dataset_archive,
        args.dataset_archive_sha256,
        args.dataset_content_sha256,
    )
    if _tree_digest(dataset_path) != args.dataset_content_sha256:
        raise EvalIdentityError("dataset_content_sha256_mismatch")
    return {
        "kind": "archive",
        "path": str(dataset_path),
        "revision": None,
        "archive": archive,
        "content_sha256": args.dataset_content_sha256,
    }


def _input_identity(
    inputs_dir: Path,
    config: dict[str, Any],
    approved_sha256: str,
    approved_count: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    if SHA256_RE.fullmatch(approved_sha256) is None or approved_count < 1:
        raise EvalIdentityError("approval_metadata_invalid")
    inputs_dir = inputs_dir.resolve(strict=True)
    manifest_path = _resolved_file(inputs_dir / "manifest.json", label="inputs_manifest")
    manifest_raw = _read_bytes(manifest_path, label="inputs_manifest")
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvalIdentityError("inputs_manifest_invalid") from error
    if not isinstance(manifest, dict) or not {"config", "task_file"}.issubset(manifest):
        raise EvalIdentityError("inputs_manifest_invalid")

    records: dict[str, dict[str, str] | None] = {}
    for name, filename in (
        ("config", "source_config.toml"),
        ("task_file", "task_file.txt"),
        ("image_manifest", "image_manifest.json"),
    ):
        raw_record = manifest.get(name)
        if raw_record is None and name == "image_manifest":
            records[name] = None
            continue
        if not isinstance(raw_record, dict) or set(raw_record) != {"source", "snapshot", "sha256"}:
            raise EvalIdentityError(f"inputs_{name}_record_invalid")
        snapshot = _resolved_file(inputs_dir / filename, label=f"inputs_{name}")
        if Path(str(raw_record["snapshot"])).resolve() != snapshot:
            raise EvalIdentityError(f"inputs_{name}_path_mismatch")
        digest = raw_record.get("sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise EvalIdentityError(f"inputs_{name}_sha256_invalid")
        if _sha256_file(snapshot, label=f"inputs_{name}") != digest:
            raise EvalIdentityError(f"inputs_{name}_sha256_mismatch")
        records[name] = {"path": str(snapshot), "sha256": digest}

    task_record = records["task_file"]
    assert task_record is not None
    if task_record["sha256"] != approved_sha256:
        raise EvalIdentityError("approved_task_file_sha256_mismatch")
    taskset = config.get("taskset")
    if not isinstance(taskset, dict):
        raise EvalIdentityError("resolved_taskset_invalid")
    if Path(str(taskset.get("task_file"))).resolve() != Path(task_record["path"]):
        raise EvalIdentityError("resolved_task_file_path_mismatch")
    if taskset.get("task_file_sha256") != approved_sha256 or config.get("num_tasks") != approved_count:
        raise EvalIdentityError("resolved_task_selection_mismatch")
    image_record = records["image_manifest"]
    if image_record is None:
        if taskset.get("image_manifest") is not None or taskset.get("image_manifest_sha256") is not None:
            raise EvalIdentityError("resolved_image_manifest_mismatch")
    elif (
        Path(str(taskset.get("image_manifest"))).resolve() != Path(image_record["path"])
        or taskset.get("image_manifest_sha256") != image_record["sha256"]
    ):
        raise EvalIdentityError("resolved_image_manifest_mismatch")

    config_record = records.pop("config")
    assert config_record is not None
    return {
        "manifest": {"path": str(manifest_path), "sha256": _sha256_bytes(manifest_raw)},
        "task_file": {**task_record, "count": approved_count},
        "image_manifest": image_record,
    }, config_record


def _routing_identity(routing_deployment_id: str | None) -> dict[str, Any]:
    if routing_deployment_id is None:
        return {"deployment_id": None, "headers": {}}
    if METADATA_ID_RE.fullmatch(routing_deployment_id) is None:
        raise EvalIdentityError("routing_deployment_id_invalid")
    return {
        "deployment_id": routing_deployment_id,
        "headers": {"X-Deployment-Id": routing_deployment_id},
    }


def _contract(
    config: dict[str, Any],
    expected_model: str,
    routing_deployment_id: str | None = None,
    *,
    role: str | None = None,
    sandbox_provider: str = "vmvm",
    _allow_legacy_direct_scored_smoke: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    client = config.get("client")
    sampling = config.get("sampling")
    harness = config.get("harness")
    if not all(isinstance(value, dict) for value in (client, sampling, harness)):
        raise EvalIdentityError("resolved_contract_invalid")
    assert isinstance(client, dict) and isinstance(sampling, dict) and isinstance(harness, dict)
    model = config.get("model")
    if not expected_model or model != expected_model:
        raise EvalIdentityError("model_contract_mismatch")
    taskset = config.get("taskset")
    direct_kimi_diagnostic = (
        model == "Kimi-K3"
        and role == "kimi-direct-smoke"
        and isinstance(taskset, dict)
        and taskset.get("dataset_revision") is not None
    )
    direct_kimi_archive_smoke = (
        model == "Kimi-K3"
        and role == "kimi-direct-smoke"
        and isinstance(taskset, dict)
        and taskset.get("dataset_revision") is None
    )
    if _allow_legacy_direct_scored_smoke and not direct_kimi_archive_smoke:
        raise EvalIdentityError("resolved_contract_invalid")
    direct_kimi_scored_smoke = (
        direct_kimi_archive_smoke and not _allow_legacy_direct_scored_smoke
    )
    require_kimi_steady_state_concurrency = role == "mobius"
    if model == "Kimi-K3":
        required_profile: str | None = None
        if role in {"tb4", "mobius", "kimi-direct-tb4"}:
            required_profile = "full"
        elif role == "kimi-direct-smoke":
            if not isinstance(taskset, dict):
                raise EvalIdentityError("resolved_contract_invalid")
            if taskset.get("dataset_revision") is not None:
                timeout = config.get("timeout")
                reward_diagnostic = isinstance(timeout, dict) and timeout.get("rollout") == 600
                required_profile = "reward_diagnostic" if reward_diagnostic else "diagnostic"
            else:
                required_profile = (
                    "quick" if _allow_legacy_direct_scored_smoke else "direct_scored_smoke"
                )
        elif role == "smoke":
            if not isinstance(taskset, dict):
                raise EvalIdentityError("resolved_contract_invalid")
            require_kimi_steady_state_concurrency = taskset.get("dataset_revision") is not None
            required_profile = "full" if require_kimi_steady_state_concurrency else "smoke"
        validate_kimi_timeout_contract(config, required_profile=required_profile)
        validate_kimi_retry_contract(config)
    if config.get("num_rollouts") != 1:
        raise EvalIdentityError("pass_at_1_required")
    thinking = sampling.get("chat_template_kwargs")
    expected_thinking = {"enable_thinking": True, "preserve_thinking": True}
    expected_reasoning_effort = "medium" if model == "Qwen3.8-2.4T-A95B" else "max"
    if sampling.get("reasoning_effort") != expected_reasoning_effort or canonical_json(
        thinking
    ) != canonical_json(expected_thinking):
        raise EvalIdentityError("reasoning_contract_required")
    limits = {
        "max_input_tokens": config.get("max_input_tokens"),
        "max_output_tokens": config.get("max_output_tokens"),
        "max_total_tokens": config.get("max_total_tokens"),
    }
    if set(limits.values()) != {262_144}:
        raise EvalIdentityError("context_256k_contract_required")
    denylist = client.get("outbound_body_denylist")
    if not isinstance(denylist, list) or set(denylist) != EXPECTED_DENYLIST or len(denylist) != len(EXPECTED_DENYLIST):
        raise EvalIdentityError("outbound_body_denylist_contract_mismatch")
    if client.get("type") != "eval" or client.get("capture_model_io") is not True:
        raise EvalIdentityError("model_io_capture_contract_required")
    if direct_kimi_scored_smoke and client.get("max_retries") != 0:
        raise EvalIdentityError("kimi_retry_contract_invalid")
    if config.get("retain_traces") is not False or config.get("rich") is not False:
        raise EvalIdentityError("durable_trace_contract_required")
    parsed_url = urlsplit(str(client.get("base_url", "")))
    if not parsed_url.scheme or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise EvalIdentityError("model_endpoint_url_invalid")
    if parsed_url.query or parsed_url.fragment:
        raise EvalIdentityError("model_endpoint_must_not_embed_credentials")
    if client.get("headers") != _routing_identity(routing_deployment_id)["headers"]:
        raise EvalIdentityError("model_endpoint_routing_headers_mismatch")
    if client.get("api_key_var") != "OPENAI_API_KEY":
        raise EvalIdentityError("model_api_key_variable_mismatch")

    rollout_concurrency = config.get("max_concurrent")
    multiplex = config.get("multiplex")
    http_connections = client.get("max_connections")
    http_keepalive = client.get("max_keepalive_connections")
    for label, value in (
        ("rollout_concurrency", rollout_concurrency),
        ("multiplex", multiplex),
        ("http_max_connections", http_connections),
        ("http_max_keepalive_connections", http_keepalive),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise EvalIdentityError(f"{label}_invalid")
    if model == "Kimi-K3" and require_kimi_steady_state_concurrency:
        validate_kimi_steady_state_concurrency_contract(config)
    if sandbox_provider not in {"vmvm", "sandoq"}:
        raise EvalIdentityError("sandbox_provider_invalid")
    runtime = harness.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("type") != sandbox_provider:
        error = "vmvm_runtime_required" if sandbox_provider == "vmvm" else "sandbox_runtime_mismatch"
        raise EvalIdentityError(error)
    if sandbox_provider == "sandoq" and (
        runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "none"
        or runtime.get("expected_environment") != "oci-runner"
        or not isinstance(runtime.get("ecr_token_file"), str)
        or not Path(runtime["ecr_token_file"]).is_absolute()
    ):
        raise EvalIdentityError("sandoq_runtime_contract_invalid")
    if sandbox_provider == "sandoq" and any(
        key in runtime
        for key in ("guest_tunnel_url", "tunnel_pool_size", "tunnel_ready_timeout")
    ):
        raise EvalIdentityError("sandoq_inactive_tunnel_fields_present")
    host_harness = harness.get("id") == "terminal-bench-sandoq-host"
    if sandbox_provider == "sandoq" and not host_harness:
        raise EvalIdentityError("sandoq_host_harness_contract_invalid")
    if host_harness:
        retries = config.get("retries")
        rollout_retries = retries.get("rollout") if isinstance(retries, dict) else None
        taskset = config.get("taskset")
        if (
            not isinstance(rollout_retries, dict)
            or rollout_retries.get("max_retries") != 0
            or not isinstance(taskset, dict)
            or taskset.get("verifier_runtime_retries") != 0
        ):
            raise EvalIdentityError(f"{sandbox_provider}_cleanup_retry_contract_invalid")
    expected_host_command_timeout = 60 if direct_kimi_diagnostic else 240
    expected_host_request_timeout = (
        KIMI_DIRECT_SCORED_SMOKE_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
        if direct_kimi_scored_smoke
        else KIMI_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
    )
    if host_harness and (
        harness.get("command_timeout_seconds") != expected_host_command_timeout
        or harness.get("command_kill_grace_seconds") != 10
        or harness.get("max_command_output_chars") != 100_000
        or harness.get("request_timeout_seconds") != expected_host_request_timeout
        or "config_overrides" in harness
    ):
        raise EvalIdentityError("sandoq_host_harness_contract_invalid")
    sampling_max_tokens = sampling.get("max_tokens")
    if (
        not isinstance(sampling_max_tokens, int)
        or isinstance(sampling_max_tokens, bool)
        or not 0 < sampling_max_tokens <= 262_144
    ):
        raise EvalIdentityError("sampling_max_tokens_invalid")
    contract = {
        "model": model,
        "pass_at_1": True,
        "num_rollouts": 1,
        "reasoning_effort": expected_reasoning_effort,
        "thinking": {"enable_thinking": True, "preserve_thinking": True},
        "context_tokens": limits,
        "sampling_max_tokens": sampling_max_tokens,
        "capture_model_io": True,
        "outbound_body_denylist": sorted(EXPECTED_DENYLIST),
        "retain_traces": False,
    }
    if host_harness:
        contract["harness"] = {
            "id": "terminal-bench-sandoq-host",
            "placement": "host",
            "tool": "bash",
            "command_timeout_seconds": expected_host_command_timeout,
            "command_kill_grace_seconds": 10,
            "max_command_output_chars": 100_000,
            "request_timeout_seconds": expected_host_request_timeout,
            "request_max_retries": 0,
            "stream": False,
        }
    identity_runtime = dict(runtime)
    if sandbox_provider == "sandoq":
        for inactive_field in ("guest_tunnel_url", "tunnel_pool_size", "tunnel_ready_timeout"):
            identity_runtime.pop(inactive_field, None)
    execution = {
        "rollout_concurrency": rollout_concurrency,
        "multiplex": multiplex,
        "http_max_connections": http_connections,
        "http_max_keepalive_connections": http_keepalive,
        "runtime": identity_runtime,
    }
    if sandbox_provider == "sandoq":
        execution["cleanup_must_succeed"] = True
    elif host_harness:
        execution["cleanup_must_succeed"] = True
        execution["cleanup_receipt_contract"] = dict(VMVM_HOST_CLEANUP_CONTRACT)
    return contract, execution


def _checkpoint_artifact(payload: dict[str, Any], name: str) -> dict[str, str]:
    artifacts = payload.get("artifacts")
    record = artifacts.get(name) if isinstance(artifacts, dict) else None
    if (
        not isinstance(record, dict)
        or set(record) != {"path", "sha256"}
        or not isinstance(record.get("path"), str)
        or not isinstance(record.get("sha256"), str)
    ):
        raise EvalIdentityError("smoke_checkpoint_artifacts_invalid")
    return _artifact(Path(record["path"]), record["sha256"], label=f"smoke_{name}")


def _validate_smoke_checkpoint_payload(
    payload: dict[str, Any],
    *,
    deployment_id: str,
    deployment_spec_sha256: str,
    readiness: dict[str, str],
    endpoint: dict[str, Any],
    serving_route_generation: dict[str, Any],
    proxy_policy: dict[str, Any],
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> None:
    self_digest = payload.get("smoke_checkpoint_sha256")
    body = {key: value for key, value in payload.items() if key != "smoke_checkpoint_sha256"}
    deployment = payload.get("deployment")
    try:
        smoke_endpoint = validate_endpoint_binding(payload.get("endpoint"))
        smoke_generation = validate_route_generation(payload.get("serving_route_generation"))
        smoke_proxy_policy = validate_proxy_policy_binding(payload.get("proxy_policy"))
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise EvalIdentityError("smoke_checkpoint_endpoint_invalid") from error
    policy = payload.get("audit_policy")
    counts = payload.get("counts")
    if (
        payload.get("schema_version") != 1
        or payload.get("state") != "passed"
        or payload.get("ok") is not True
        or not isinstance(self_digest, str)
        or self_digest != _sha256_bytes(canonical_json(body))
        or not isinstance(deployment, dict)
        or deployment.get("id") != deployment_id
        or deployment.get("spec_sha256") != deployment_spec_sha256
        or smoke_endpoint != endpoint
        or smoke_generation != serving_route_generation
        or smoke_proxy_policy != proxy_policy
        or not isinstance(policy, dict)
        or policy.get("rollouts_per_task") != 1
        or policy.get("require_reasoning") is not True
        or policy.get("require_model_io") is not True
        or policy.get("require_request_graph_match") is not True
        or canonical_json(policy.get("model_io_contract")) != canonical_json(EXPECTED_MODEL_IO_CONTRACT)
        or policy.get("require_token_data") is not False
        or policy.get("require_logprobs") is not False
        or policy.get("max_sequence_tokens") != 262_144
        or not isinstance(counts, dict)
        or counts.get("trace_failures") != 0
        or counts.get("global_problems") != 0
    ):
        raise EvalIdentityError("smoke_checkpoint_not_passed")
    expected_traces = policy.get("expected_traces")
    positive_counts = (counts.get("traces"), counts.get("tasks"), counts.get("model_io_turns"))
    if (
        not isinstance(expected_traces, int)
        or isinstance(expected_traces, bool)
        or expected_traces < 1
        or counts.get("traces") != expected_traces
        or counts.get("tasks") != expected_traces
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in positive_counts)
    ):
        raise EvalIdentityError("smoke_checkpoint_counts_invalid")

    for name in (
        "results",
        "eval_invocations",
        "route_guard_success",
        "config",
        "inputs_manifest",
        "provenance",
    ):
        _checkpoint_artifact(payload, name)
    certificate_proxy = _checkpoint_artifact(payload, "proxy_info")
    if certificate_proxy != endpoint["proxy_info"]:
        raise EvalIdentityError("smoke_checkpoint_endpoint_mismatch")
    certificate_readiness = _checkpoint_artifact(payload, "readiness_checkpoint")
    if certificate_readiness != readiness:
        raise EvalIdentityError("smoke_checkpoint_readiness_mismatch")
    identity_artifact = _checkpoint_artifact(payload, "eval_run_identity")
    preliminary = load_eval_run_identity(Path(identity_artifact["path"]), verify_references=False)
    smoke_identity = preliminary["identity"]
    if smoke_identity.get("role") != "smoke":
        raise EvalIdentityError("smoke_checkpoint_identity_role_invalid")
    if deployment_spec_snapshot is None:
        envelope = load_eval_run_identity(
            Path(identity_artifact["path"]),
            verify_references=True,
        )
    else:
        envelope = load_eval_run_identity(
            Path(identity_artifact["path"]),
            verify_references=True,
            deployment_spec_snapshot=deployment_spec_snapshot,
            proxy_policy_snapshot=proxy_policy_snapshot,
        )
    smoke_identity = envelope["identity"]
    smoke_deployment = smoke_identity.get("deployment")
    smoke_readiness = smoke_deployment.get("readiness_checkpoint") if isinstance(smoke_deployment, dict) else None
    if (
        payload.get("eval_run_identity_sha256") != envelope.get("eval_run_identity_sha256")
        or not isinstance(smoke_deployment, dict)
        or smoke_deployment.get("id") != deployment_id
        or smoke_deployment.get("endpoint") != endpoint
        or smoke_deployment.get("serving_route_generation") != serving_route_generation
        or smoke_deployment.get("proxy_policy") != proxy_policy
        or not isinstance(smoke_deployment.get("spec"), dict)
        or smoke_deployment["spec"].get("sha256") != deployment_spec_sha256
        or not isinstance(smoke_readiness, dict)
        or smoke_readiness != readiness
        or smoke_identity.get("inputs", {}).get("task_file", {}).get("count") != expected_traces
    ):
        raise EvalIdentityError("smoke_checkpoint_identity_mismatch")
    results_artifact = _checkpoint_artifact(payload, "results")
    invocations_artifact = _checkpoint_artifact(payload, "eval_invocations")
    guard_artifact = _checkpoint_artifact(payload, "route_guard_success")
    run_dir = Path(identity_artifact["path"]).parent
    if guard_artifact["path"] != str(run_dir / "route_guard_success.json"):
        raise EvalIdentityError("smoke_checkpoint_guard_receipt_invalid")
    try:
        guard_receipt = load_guard_success_receipt(Path(guard_artifact["path"]))
        guard_artifacts = validate_guard_success_linkage(
            guard_receipt,
            run_dir=run_dir,
            eval_run_identity_sha256=envelope["eval_run_identity_sha256"],
            eval_run_role="smoke",
            eval_run_identity_file_sha256=identity_artifact["sha256"],
            results_sha256=results_artifact["sha256"],
            deployment_id=deployment_id,
            deployment_spec_sha256=deployment_spec_sha256,
            readiness_checkpoint=readiness,
            endpoint=endpoint,
            serving_route_generation=serving_route_generation,
            proxy_policy=proxy_policy,
        )
    except (OSError, GuardReceiptError) as error:
        raise EvalIdentityError("smoke_checkpoint_guard_receipt_invalid") from error
    if guard_artifacts["eval_invocations"] != invocations_artifact:
        raise EvalIdentityError("smoke_checkpoint_guard_receipt_invalid")


def _checkpoint_identity(
    args: argparse.Namespace,
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    spec = _artifact(args.deployment_spec, args.deployment_spec_sha256, label="deployment_spec")
    readiness = _artifact(
        args.readiness_checkpoint,
        args.readiness_checkpoint_sha256,
        label="readiness_checkpoint",
    )
    readiness_payload = _json_artifact(readiness, label="readiness_checkpoint")
    probe = readiness_payload.get("probe")
    try:
        readiness_endpoint = validate_endpoint_binding(readiness_payload.get("endpoint"))
        serving_route_generation = validate_readiness_route_generation(
            readiness_payload,
            deployment_id=args.deployment_id,
            deployment_spec_sha256=spec["sha256"],
        )
        expected_request_timeout = request_timeout_for_model(args.expected_model)
        proxy_policy = validate_proxy_policy_binding(
            readiness_payload.get("proxy_policy"),
            expected_request_timeout=expected_request_timeout,
        )
        revalidate_deployment_proxy_policy(
            Path(spec["path"]),
            expected_spec_sha256=spec["sha256"],
            expected_binding=proxy_policy,
            expected_request_timeout=expected_request_timeout,
        )
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise EvalIdentityError("readiness_checkpoint_endpoint_invalid") from error
    if (
        readiness_payload.get("schema_version") != 1
        or readiness_payload.get("state") != "passed"
        or readiness_payload.get("deployment") != args.deployment_id
        or readiness_payload.get("observed_spec_sha256") != spec["sha256"]
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
        or readiness_endpoint != endpoint
    ):
        raise EvalIdentityError("readiness_checkpoint_not_passed")

    smoke: dict[str, str] | None = None
    if args.role == "smoke":
        if args.smoke_checkpoint is not None or args.smoke_checkpoint_sha256 is not None:
            raise EvalIdentityError("smoke_role_cannot_use_prior_smoke_checkpoint")
    else:
        if args.smoke_checkpoint is None or args.smoke_checkpoint_sha256 is None:
            raise EvalIdentityError("smoke_checkpoint_required")
        smoke = _artifact(args.smoke_checkpoint, args.smoke_checkpoint_sha256, label="smoke_checkpoint")
        smoke_payload = _json_artifact(smoke, label="smoke_checkpoint")
        if smoke_payload.get("schema_version") == 1:
            _validate_smoke_checkpoint_payload(
                smoke_payload,
                deployment_id=args.deployment_id,
                deployment_spec_sha256=spec["sha256"],
                readiness=readiness,
                endpoint=endpoint,
                serving_route_generation=serving_route_generation,
                proxy_policy=proxy_policy,
            )
        else:
            try:
                validate_smoke_qualification(
                    Path(smoke["path"]),
                    smoke["sha256"],
                    deployment_id=args.deployment_id,
                    deployment_spec_path=Path(spec["path"]),
                    deployment_spec_sha256=spec["sha256"],
                    readiness_path=Path(readiness["path"]),
                    readiness_sha256=readiness["sha256"],
                    proxy_info_path=Path(endpoint["proxy_info"]["path"]),
                    proxy_info_sha256=endpoint["proxy_info"]["sha256"],
                    model=args.expected_model,
                    identity_loader=load_eval_run_identity,
                )
            except SmokeQualificationError as error:
                raise EvalIdentityError("smoke_checkpoint_not_passed") from error
    promotion: dict[str, str] | None = None
    if args.role == "mobius":
        if args.promotion_certificate is None or args.promotion_certificate_sha256 is None:
            raise EvalIdentityError("promotion_certificate_required")
        promotion = _artifact(
            args.promotion_certificate,
            args.promotion_certificate_sha256,
            label="promotion_certificate",
        )
        promotion_payload = _json_artifact(promotion, label="promotion_certificate")
        promotion_deployment = promotion_payload.get("deployment")
        try:
            promotion_endpoint = validate_endpoint_binding(
                promotion_deployment.get("endpoint") if isinstance(promotion_deployment, dict) else None
            )
            promotion_generation = validate_route_generation(
                promotion_deployment.get("serving_route_generation") if isinstance(promotion_deployment, dict) else None
            )
            promotion_proxy_policy = validate_proxy_policy_binding(
                promotion_deployment.get("proxy_policy") if isinstance(promotion_deployment, dict) else None
            )
        except (
            EndpointBindingError,
            RouteGenerationError,
            DeploymentProxyPolicyError,
        ) as error:
            raise EvalIdentityError("promotion_certificate_endpoint_invalid") from error
        if (
            promotion_endpoint != endpoint
            or promotion_generation != serving_route_generation
            or promotion_proxy_policy != proxy_policy
        ):
            raise EvalIdentityError("promotion_certificate_endpoint_mismatch")
    elif args.promotion_certificate is not None or args.promotion_certificate_sha256 is not None:
        raise EvalIdentityError("promotion_certificate_role_invalid")
    return {
        "id": args.deployment_id,
        "endpoint": endpoint,
        "serving_route_generation": serving_route_generation,
        "proxy_policy": proxy_policy,
        "routing": _routing_identity(args.routing_deployment_id),
        "spec": spec,
        "readiness_checkpoint": readiness,
        "smoke_checkpoint": smoke,
        "promotion_certificate": promotion,
    }


def _positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise EvalIdentityError(f"{label}_invalid") from error
    if parsed < 1:
        raise EvalIdentityError(f"{label}_invalid")
    return parsed


def _effective_vmvm_environment(args: argparse.Namespace, rollout_concurrency: int) -> dict[str, Any]:
    lease_limit = _positive_int(args.vacli_max_concurrent_leases, "vacli_max_concurrent_leases")
    privileged = args.vacli_container_privileged
    if privileged not in {"0", "1"}:
        raise EvalIdentityError("vacli_container_privileged_invalid")
    return {
        "vacli_bin": args.vacli_bin,
        "lease_start_concurrency": min(lease_limit, rollout_concurrency),
        "lease_retries": _positive_int(args.vacli_lease_retries, "vacli_lease_retries"),
        "max_pull_retries": _positive_int(args.vacli_max_pull_retries, "vacli_max_pull_retries"),
        "image_pull_timeout_sec": _positive_int(
            args.vacli_image_pull_timeout_seconds,
            "vacli_image_pull_timeout_seconds",
        ),
        "container_privileged": privileged == "1",
    }


def _effective_sandoq_environment(
    args: argparse.Namespace, rollout_concurrency: int, output_dir: Path
) -> dict[str, Any]:
    pool_size = _positive_int(args.sandoq_pool_size, "sandoq_pool_size")
    try:
        pool_min_size = int(args.sandoq_pool_min_size)
    except ValueError as error:
        raise EvalIdentityError("sandoq_pool_min_size_invalid") from error
    if pool_min_size != 0:
        raise EvalIdentityError("sandoq_pool_min_size_invalid")
    if pool_size < rollout_concurrency:
        raise EvalIdentityError("sandoq_pool_size_below_rollout_concurrency")
    if args.sandoq_environment != "oci-runner":
        raise EvalIdentityError("sandoq_environment_invalid")
    if args.sandoq_task_network != "public":
        raise EvalIdentityError("sandoq_task_network_invalid")
    if args.sandoq_tunnel_policy != "host-interception-no-tunnel":
        raise EvalIdentityError("sandoq_tunnel_policy_invalid")
    proxy_policy = args.sandoq_transport_proxy_policy
    proxy_environment = {
        name: os.environ.get(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "SANDOQ_TUNNEL_HTTPS_PROXY",
        )
    }
    if proxy_policy == "official-client-auto":
        proxy_valid = not any(proxy_environment.values())
    elif proxy_policy == "official-client-supervised-loopback-connect-proxy":
        https_proxy = proxy_environment["HTTPS_PROXY"]
        try:
            parsed_proxy = urlsplit(https_proxy or "")
            proxy_port = parsed_proxy.port
        except ValueError:
            proxy_valid = False
        else:
            proxy_valid = (
                https_proxy == proxy_environment["https_proxy"]
                and parsed_proxy.scheme == "http"
                and parsed_proxy.hostname == "127.0.0.1"
                and proxy_port is not None
                and 1 <= proxy_port <= 65_535
                and parsed_proxy.username is None
                and parsed_proxy.password is None
                and parsed_proxy.path in ("", "/")
                and not parsed_proxy.query
                and not parsed_proxy.fragment
                and not any(
                    proxy_environment[name]
                    for name in (
                        "HTTP_PROXY",
                        "http_proxy",
                        "ALL_PROXY",
                        "all_proxy",
                        "SANDOQ_TUNNEL_HTTPS_PROXY",
                    )
                )
            )
    else:
        proxy_valid = False
    if (
        args.sandoq_base_url != "https://sandoq.eks-prod.cf.aws.metafb.cloud"
        or not re.fullmatch(r"[A-Za-z0-9._-]+", args.sandoq_owner or "")
        or not proxy_valid
    ):
        raise EvalIdentityError("sandoq_transport_policy_invalid")
    if (
        args.sandoq_use_ecr != "1"
        or args.sandoq_ecr_registry != "168653207203.dkr.ecr.us-east-2.amazonaws.com"
        or args.sandoq_ecr_region != "us-east-2"
        or args.sandoq_ecr_pull_through_prefix != "pt_dockerio"
        or args.sandoq_allow_dockerhub_fallback != "1"
    ):
        raise EvalIdentityError("sandoq_ecr_policy_invalid")
    ecr_token_file = Path(args.sandoq_ecr_token_file)
    if not ecr_token_file.is_absolute() or os.environ.get("OCI_RUNNER_ECR_TOKEN_FILE") != str(ecr_token_file):
        raise EvalIdentityError("sandoq_ecr_token_file_invalid")
    try:
        token_stat = ecr_token_file.lstat()
    except OSError as error:
        raise EvalIdentityError("sandoq_ecr_token_file_unavailable") from error
    if not stat.S_ISREG(token_stat.st_mode) or ecr_token_file.is_symlink() or stat.S_IMODE(token_stat.st_mode) != 0o600:
        raise EvalIdentityError("sandoq_ecr_token_file_permissions_invalid")
    pool_socket = Path(args.sandoq_pool_socket)
    expected_socket = (
        Path(os.environ.get("SLURM_TMPDIR", "/tmp")) / f"oci-runner-pool-{os.getuid()}" / f"{args.slurm_job_id}.sock"
    )
    pool_wal = Path(args.sandoq_pool_wal)
    pool_event_log = Path(args.sandoq_pool_event_log)
    if (
        pool_socket != expected_socket
        or os.environ.get("OCI_RUNNER_POOL_SOCKET") != str(pool_socket)
        or pool_wal != output_dir / "control/sandoq-pool.wal.jsonl"
        or pool_event_log != output_dir / "pool_events.jsonl"
        or os.environ.get("OCI_RUNNER_POOL_WAL") != str(pool_wal)
        or os.environ.get("OCI_RUNNER_POOL_EVENT_LOG") != str(pool_event_log)
        or os.environ.get("PRIME_RL_OUTPUT_DIR") != str(output_dir)
        or any(
            os.environ.get(name)
            for name in (
                "OCI_RUNNER_DOCKERHUB_USERNAME",
                "OCI_RUNNER_DOCKERHUB_TOKEN_FILE",
                "OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH",
            )
        )
    ):
        raise EvalIdentityError("sandoq_storage_or_auth_policy_invalid")
    exact_policy = {
        "create_deadline": "30m",
        "pull_timeout": "3600s",
        "pull_poll_max_errors": "20",
        "gateway_retry_attempts": "15",
        "gateway_retry_interval": "2s",
        "podman_ignore_chown_errors": "1",
        "require_resource_limits": "1",
        "exec_timeout_ceiling": "270",
        "task_pids_limit": "512",
        "observability": "1",
        "pool_heartbeat_timeout": "45s",
        "pool_create_workers": str(min(pool_size, 4)),
        "pool_bootstrap_workers": str(min(pool_size, 64)),
        "pool_bootstrap_per_image": str(min(pool_size, 8)),
        "pool_drain_workers": str(min(pool_size, 32)),
        "pool_drain_timeout": "240",
        "pool_renew_workers": str(min(pool_size, 16)),
        "session_reuse": "1",
        "pool_max_reuse_count": "1",
        "pool_reuse_jitter": "0",
        "image_cache_max_entries": "0",
        "secret_cache_ttl": "5s",
        "lease_duration": "1h",
        "pool_renew_interval": "5m",
    }
    for field, expected in exact_policy.items():
        if getattr(args, f"sandoq_{field}") != expected:
            raise EvalIdentityError(f"sandoq_{field}_invalid")
    return {
        "environment": args.sandoq_environment,
        "task_network": args.sandoq_task_network,
        "pool_size": pool_size,
        "pool_min_size": pool_min_size,
        "tunnel_policy": args.sandoq_tunnel_policy,
        "base_url": args.sandoq_base_url,
        "owner": args.sandoq_owner,
        "transport_proxy_policy": args.sandoq_transport_proxy_policy,
        "pool_socket_scope": "job-node-local",
        "pool_wal": str(pool_wal),
        "pool_event_log": str(pool_event_log),
        "use_ecr": True,
        "ecr_registry": args.sandoq_ecr_registry,
        "ecr_region": args.sandoq_ecr_region,
        "ecr_pull_through_prefix": args.sandoq_ecr_pull_through_prefix,
        "ecr_token_file": str(ecr_token_file),
        "ecr_auth_policy": "private-token-file-mode-0600",
        "allow_dockerhub_fallback": True,
        **exact_policy,
    }


def _load_resolved_config(path: Path) -> dict[str, Any]:
    raw = _read_bytes(path, label="resolved_config")
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
        config = EvalConfig.model_validate(parsed)
    except Exception as error:
        raise EvalIdentityError("resolved_config_invalid") from error
    return _resolved_config_data(config, explicit=parsed)


def _resolved_config_data(
    config: EvalConfig,
    *,
    explicit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = config.model_dump(mode="json", exclude_none=True)
    harness = data.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    inactive_tunnel_fields = {
        "guest_tunnel_url",
        "tunnel_pool_size",
        "tunnel_ready_timeout",
    }
    if (
        isinstance(harness, dict)
        and harness.get("id") == "terminal-bench-sandoq-host"
        and isinstance(runtime, dict)
        and runtime.get("type") == "sandoq"
    ):
        explicit_harness = explicit.get("harness") if isinstance(explicit, Mapping) else None
        explicit_runtime = (
            explicit_harness.get("runtime") if isinstance(explicit_harness, Mapping) else None
        )
        if isinstance(explicit_runtime, Mapping) and inactive_tunnel_fields.intersection(
            explicit_runtime
        ):
            raise EvalIdentityError("sandoq_inactive_tunnel_fields_present")
        for field in inactive_tunnel_fields:
            runtime.pop(field, None)
    return data


def _write_resolved_config(
    output_dir: Path,
    inputs_dir: Path,
    client_base_url: str,
    model_override: str | None,
    approved_task_file_sha256: str,
    routing_deployment_id: str | None = None,
) -> dict[str, Any]:
    config_path = output_dir / "config.toml"
    results_path = output_dir / "results.jsonl"
    if config_path.exists() or results_path.exists():
        raise EvalIdentityError("fresh_eval_output_not_empty")
    argv = [
        "@",
        str(inputs_dir / "source_config.toml"),
        "--client.base-url",
        client_base_url,
        "--output-dir",
        str(output_dir),
        "--taskset.task-file",
        str(inputs_dir / "task_file.txt"),
        "--taskset.task-file-sha256",
        approved_task_file_sha256,
    ]
    image_manifest = inputs_dir / "image_manifest.json"
    if image_manifest.is_file():
        argv.extend(["--taskset.image-manifest", str(image_manifest)])
    if model_override:
        argv.extend(["--model", model_override])
    if routing_deployment_id is not None:
        argv.extend(
            [
                "--client.headers",
                json.dumps(_routing_identity(routing_deployment_id)["headers"], sort_keys=True),
            ]
        )
    config_type = narrow_config(EvalConfig, argv)
    try:
        config = cli(config_type, args=argv, plain=True)
    except SystemExit:
        raise
    except Exception as error:
        raise EvalIdentityError("resolved_config_invalid") from error
    data = _resolved_config_data(config)
    config_path.write_text(tomli_w.dumps(data), encoding="utf-8")
    results_path.open("x").close()
    return data


def _identity_envelope(identity: dict[str, Any]) -> dict[str, Any]:
    identity = _validate_identity_shape(identity)
    return {
        "schema_version": SCHEMA_VERSION,
        "eval_run_identity_sha256": _sha256_bytes(canonical_json(identity)),
        "identity": identity,
    }


def _validate_artifact_shape(record: object, *, keys: set[str] | None = None) -> dict[str, Any]:
    expected_keys = keys or {"path", "sha256"}
    if not isinstance(record, dict) or set(record) != expected_keys:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    path = record.get("path")
    digest = record.get("sha256")
    if (
        not isinstance(path, str)
        or not path
        or not Path(path).is_absolute()
        or not isinstance(digest, str)
        or SHA256_RE.fullmatch(digest) is None
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    return record


def _validate_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_identity_shape(identity: object) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "role",
        "source",
        "config",
        "inputs",
        "dataset",
        "deployment",
        "contract",
        "execution",
    }
    if not isinstance(identity, dict) or set(identity) != expected_keys or identity.get("schema_version") != 1:
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    role = identity.get("role")
    if role not in {"smoke", "tb4", "mobius", *DIRECT_ROLES}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    source = identity.get("source")
    common_source_keys = {
        "project_root",
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
    }
    if not isinstance(source, dict):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    sandbox_provider = source.get("sandbox_provider", "vmvm")
    source_keys = (
        common_source_keys | {"vmvm_tb_v2_sha256"}
        if sandbox_provider == "vmvm"
        else common_source_keys
        | {
            "sandbox_provider",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
            "sandoq_client_version",
            "sandoq_site",
            "sandoq_site_sha256",
            "sandoq_host_harness_sha256",
            "derived_image_manifest_sha256",
        }
    )
    if sandbox_provider not in {"vmvm", "sandoq"} or set(source) != source_keys:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    project_root = source.get("project_root")
    if not isinstance(project_root, str) or not project_root or not Path(project_root).is_absolute():
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if sandbox_provider == "sandoq" and (
        not isinstance(source.get("sandoq_site"), str) or not Path(source["sandoq_site"]).is_absolute()
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    revision_keys = (
        "prime_rl_commit",
        "verifiers_commit",
        "renderers_commit",
    )
    if sandbox_provider == "sandoq":
        revision_keys += ("sandoq_provider_commit", "sandoq_provider_tree")
    for key in revision_keys:
        value = source.get(key)
        if not isinstance(value, str) or REVISION_RE.fullmatch(value) is None:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
    digest_keys = (
        "prime_rl_tree_sha256",
        "verifiers_tree_sha256",
        "renderers_tree_sha256",
    )
    digest_keys += (
        ("vmvm_tb_v2_sha256",)
        if sandbox_provider == "vmvm"
        else (
            "derived_image_manifest_sha256",
            "sandoq_site_sha256",
            "sandoq_host_harness_sha256",
        )
    )
    for key in digest_keys:
        value = source.get(key)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
    if any(source[key] != CLEAN_TREE_SHA256 for key in source_keys if key.endswith("tree_sha256")):
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    config = identity.get("config")
    if not isinstance(config, dict) or set(config) != {"source", "resolved"}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    _validate_artifact_shape(config["source"])
    _validate_artifact_shape(config["resolved"])

    inputs = identity.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"manifest", "task_file", "image_manifest"}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    _validate_artifact_shape(inputs["manifest"])
    task_file = _validate_artifact_shape(inputs["task_file"], keys={"path", "sha256", "count"})
    if not _validate_positive_integer(task_file.get("count")):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if inputs["image_manifest"] is not None:
        _validate_artifact_shape(inputs["image_manifest"])
    if sandbox_provider == "sandoq" and (
        inputs["image_manifest"] is None
        or inputs["image_manifest"]["sha256"] != source["derived_image_manifest_sha256"]
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    dataset = identity.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {
        "kind",
        "path",
        "revision",
        "archive",
        "content_sha256",
    }:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    dataset_path = dataset.get("path")
    archive = dataset.get("archive")
    if not isinstance(dataset_path, str) or not dataset_path or not Path(dataset_path).is_absolute():
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if not isinstance(archive, dict) or set(archive) != {"path", "sha256"}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if dataset.get("kind") == "git_revision":
        revision = dataset.get("revision")
        if (
            not isinstance(revision, str)
            or REVISION_RE.fullmatch(revision) is None
            or archive != {"path": None, "sha256": None}
            or dataset.get("content_sha256") is not None
        ):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
    elif dataset.get("kind") == "archive":
        content_sha256 = dataset.get("content_sha256")
        _validate_artifact_shape(archive)
        if (
            dataset.get("revision") is not None
            or not isinstance(content_sha256, str)
            or SHA256_RE.fullmatch(content_sha256) is None
        ):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
    else:
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    deployment = identity.get("deployment")
    direct_role = role in DIRECT_ROLES
    if role == "qwen-direct":
        if not isinstance(deployment, dict) or set(deployment) != {
            "kind",
            "worker_manifest",
            "spec_sha256",
            "endpoint_bundle_sha256",
            "base_url",
            "router",
        }:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        _validate_artifact_shape(deployment["worker_manifest"])
        router = deployment.get("router")
        if (
            deployment.get("kind") != "direct_qwen"
            or SHA256_RE.fullmatch(str(deployment.get("spec_sha256", ""))) is None
            or SHA256_RE.fullmatch(str(deployment.get("endpoint_bundle_sha256", ""))) is None
            or not isinstance(deployment.get("base_url"), str)
            or not isinstance(router, dict)
            or set(router) != {"policy", "request_id_headers", "provider_concurrency"}
            or router.get("policy") != "consistent_hash"
            or router.get("request_id_headers") != ["x-session-id"]
            or not _validate_positive_integer(router.get("provider_concurrency"))
        ):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        proxy_policy = None
    elif role in DIRECT_KIMI_ROLES:
        if not isinstance(deployment, dict) or set(deployment) != {
            "kind",
            "worker_manifest",
            "spec_sha256",
            "endpoint_bundle_sha256",
            "base_url",
            "router",
            "smoke_checkpoint",
        }:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        _validate_artifact_shape(deployment["worker_manifest"])
        smoke_checkpoint = deployment.get("smoke_checkpoint")
        router = deployment.get("router")
        try:
            parsed_base_url = urlsplit(str(deployment.get("base_url", "")))
            base_url_port = parsed_base_url.port
        except ValueError as error:
            raise EvalIdentityError("eval_run_identity_schema_invalid") from error
        if (
            deployment.get("kind") != "direct_kimi"
            or SHA256_RE.fullmatch(str(deployment.get("spec_sha256", ""))) is None
            or SHA256_RE.fullmatch(str(deployment.get("endpoint_bundle_sha256", ""))) is None
            or parsed_base_url.scheme != "http"
            or parsed_base_url.hostname != "127.0.0.1"
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or base_url_port is None
            or not 1 <= base_url_port <= 65_535
            or parsed_base_url.netloc != f"127.0.0.1:{base_url_port}"
            or parsed_base_url.path != "/v1"
            or parsed_base_url.query
            or parsed_base_url.fragment
            or not isinstance(router, dict)
            or router
            != {
                "implementation": "direct-kimi-transparent-v1",
                "implementation_sha256": router.get("implementation_sha256"),
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "provider_concurrency": 24,
                "request_timeout_seconds": KIMI_REQUEST_TIMEOUT_SECONDS,
                "retries": 0,
                "worker_count": 24,
            }
            or SHA256_RE.fullmatch(str(router.get("implementation_sha256", ""))) is None
            or (role == "kimi-direct-smoke" and smoke_checkpoint is not None)
        ):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        if role == "kimi-direct-tb4":
            _validate_artifact_shape(smoke_checkpoint)
        proxy_policy = None
    elif not isinstance(deployment, dict) or set(deployment) != {
        "id",
        "endpoint",
        "serving_route_generation",
        "proxy_policy",
        "routing",
        "spec",
        "readiness_checkpoint",
        "smoke_checkpoint",
        "promotion_certificate",
    }:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if not direct_role:
        deployment_id = deployment.get("id")
    if not direct_role and (
        not isinstance(deployment_id, str) or METADATA_ID_RE.fullmatch(deployment_id) is None
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    try:
        if direct_role:
            raise StopIteration
        validate_endpoint_binding(deployment.get("endpoint"))
        validate_route_generation(deployment.get("serving_route_generation"))
        proxy_policy = validate_proxy_policy_binding(deployment.get("proxy_policy"))
    except StopIteration:
        pass
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise EvalIdentityError("eval_run_identity_schema_invalid") from error
    routing = deployment.get("routing") if not direct_role else None
    routing_id = routing.get("deployment_id") if isinstance(routing, dict) else None
    if not direct_role and (
        not isinstance(routing, dict)
        or set(routing) != {"deployment_id", "headers"}
        or (routing_id is not None and not isinstance(routing_id, str))
        or routing != _routing_identity(routing_id)
        or (routing_id is not None and routing_id != deployment_id)
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if not direct_role:
        _validate_artifact_shape(deployment["spec"])
        _validate_artifact_shape(deployment["readiness_checkpoint"])
    if not direct_role and role == "smoke":
        if deployment["smoke_checkpoint"] is not None:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
    elif not direct_role:
        _validate_artifact_shape(deployment["smoke_checkpoint"])
    if role == "mobius":
        _validate_artifact_shape(deployment["promotion_certificate"])
    elif not direct_role and deployment["promotion_certificate"] is not None:
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    contract = identity.get("contract")
    if not isinstance(contract, dict):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    expected_contract_keys = {
        "model",
        "pass_at_1",
        "num_rollouts",
        "reasoning_effort",
        "thinking",
        "context_tokens",
        "sampling_max_tokens",
        "capture_model_io",
        "outbound_body_denylist",
        "retain_traces",
    }
    if "harness" in contract:
        expected_contract_keys.add("harness")
    if set(contract) != expected_contract_keys:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    model = contract.get("model")
    context = contract.get("context_tokens")
    if (
        not isinstance(model, str)
        or not model
        or any(character in model for character in "\r\n")
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort")
        != ("medium" if model == "Qwen3.8-2.4T-A95B" else "max")
        or canonical_json(contract.get("thinking"))
        != canonical_json({"enable_thinking": True, "preserve_thinking": True})
        or not isinstance(context, dict)
        or set(context) != {"max_input_tokens", "max_output_tokens", "max_total_tokens"}
        or any(value != 262_144 for value in context.values())
        or not _validate_positive_integer(contract.get("sampling_max_tokens"))
        or contract["sampling_max_tokens"] > 262_144
        or contract.get("capture_model_io") is not True
        or contract.get("outbound_body_denylist") != sorted(EXPECTED_DENYLIST)
        or contract.get("retain_traces") is not False
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if role in DIRECT_KIMI_ROLES and model != "Kimi-K3":
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    expected_harness_command_timeout = (
        60 if role == "kimi-direct-smoke" and dataset.get("kind") == "git_revision" else 240
    )
    allowed_harness_request_timeouts = {KIMI_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS}
    if role == "kimi-direct-smoke" and dataset.get("kind") == "archive":
        # Schema-v1 scored-smoke identities written before the bounded profile used
        # the generic Kimi harness timeout. Keep those immutable records auditable.
        allowed_harness_request_timeouts.add(
            KIMI_DIRECT_SCORED_SMOKE_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
        )
    observed_harness = contract.get("harness")
    if "harness" in contract and (
        not isinstance(observed_harness, dict)
        or observed_harness.get("request_timeout_seconds")
        not in allowed_harness_request_timeouts
        or observed_harness
        != {
            "id": "terminal-bench-sandoq-host",
            "placement": "host",
            "tool": "bash",
            "command_timeout_seconds": expected_harness_command_timeout,
            "command_kill_grace_seconds": 10,
            "max_command_output_chars": 100_000,
            "request_timeout_seconds": observed_harness.get("request_timeout_seconds"),
            "request_max_retries": 0,
            "stream": False,
        }
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if sandbox_provider == "sandoq" and "harness" not in contract:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if not direct_role and proxy_policy["request_timeout"] != request_timeout_for_model(model):
        raise EvalIdentityError("eval_run_identity_schema_invalid")

    execution = identity.get("execution")
    common_execution_keys = {
        "rollout_concurrency",
        "multiplex",
        "http_max_connections",
        "http_max_keepalive_connections",
        "runtime",
    }
    if sandbox_provider == "sandoq" or (
        sandbox_provider == "vmvm" and isinstance(contract, dict) and "harness" in contract
    ):
        common_execution_keys.add("cleanup_must_succeed")
    if sandbox_provider == "vmvm" and isinstance(contract, dict) and "harness" in contract:
        common_execution_keys.add("cleanup_receipt_contract")
    environment_key = f"{sandbox_provider}_environment"
    if not isinstance(execution, dict) or set(execution) != common_execution_keys | {environment_key}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if any(
        not _validate_positive_integer(execution.get(key))
        for key in (
            "rollout_concurrency",
            "multiplex",
            "http_max_connections",
            "http_max_keepalive_connections",
        )
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    runtime = execution.get("runtime")
    environment = execution.get(environment_key)
    if not isinstance(runtime, dict) or runtime.get("type") != sandbox_provider:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if sandbox_provider == "sandoq":
        if execution.get("cleanup_must_succeed") is not True:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        if not isinstance(environment, dict) or set(environment) != {
            "environment",
            "task_network",
            "pool_size",
            "pool_min_size",
            "tunnel_policy",
            "base_url",
            "owner",
            "transport_proxy_policy",
            "pool_socket_scope",
            "pool_wal",
            "pool_event_log",
            "use_ecr",
            "ecr_registry",
            "ecr_region",
            "ecr_pull_through_prefix",
            "ecr_token_file",
            "ecr_auth_policy",
            "allow_dockerhub_fallback",
            "create_deadline",
            "pull_timeout",
            "pull_poll_max_errors",
            "gateway_retry_attempts",
            "gateway_retry_interval",
            "podman_ignore_chown_errors",
            "require_resource_limits",
            "exec_timeout_ceiling",
            "task_pids_limit",
            "observability",
            "pool_heartbeat_timeout",
            "pool_create_workers",
            "pool_bootstrap_workers",
            "pool_bootstrap_per_image",
            "pool_drain_workers",
            "pool_drain_timeout",
            "pool_renew_workers",
            "session_reuse",
            "pool_max_reuse_count",
            "pool_reuse_jitter",
            "image_cache_max_entries",
            "secret_cache_ttl",
            "lease_duration",
            "pool_renew_interval",
        }:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        if (
            environment.get("environment") != "oci-runner"
            or environment.get("task_network") != "public"
            or environment.get("tunnel_policy") != "host-interception-no-tunnel"
            or environment.get("use_ecr") is not True
            or environment.get("ecr_registry") != "168653207203.dkr.ecr.us-east-2.amazonaws.com"
            or environment.get("ecr_region") != "us-east-2"
            or environment.get("ecr_pull_through_prefix") != "pt_dockerio"
            or not isinstance(environment.get("ecr_token_file"), str)
            or not Path(environment["ecr_token_file"]).is_absolute()
            or environment.get("ecr_auth_policy") != "private-token-file-mode-0600"
            or environment.get("base_url") != "https://sandoq.eks-prod.cf.aws.metafb.cloud"
            or not re.fullmatch(r"[A-Za-z0-9._-]+", str(environment.get("owner", "")))
            or environment.get("transport_proxy_policy")
            not in {
                "official-client-auto",
                "official-client-supervised-loopback-connect-proxy",
            }
            or environment.get("pool_socket_scope") != "job-node-local"
            or not isinstance(environment.get("pool_wal"), str)
            or not isinstance(environment.get("pool_event_log"), str)
            or environment.get("allow_dockerhub_fallback") is not True
            or runtime.get("mode") != "oci-runner"
            or runtime.get("network_access") is not True
            or runtime.get("host_tunnel") != "none"
            or runtime.get("expected_environment") != "oci-runner"
            or any(
                key in runtime
                for key in ("guest_tunnel_url", "tunnel_pool_size", "tunnel_ready_timeout")
            )
            or runtime.get("ecr_token_file") != environment.get("ecr_token_file")
            or not _validate_positive_integer(environment.get("pool_size"))
            or not isinstance(environment.get("pool_min_size"), int)
            or environment["pool_min_size"] < 0
            or environment["pool_min_size"] > environment["pool_size"]
            or environment["pool_size"] < execution["rollout_concurrency"]
        ):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        expected_policy = {
            "create_deadline": "30m",
            "pull_timeout": "3600s",
            "pull_poll_max_errors": "20",
            "gateway_retry_attempts": "15",
            "gateway_retry_interval": "2s",
            "podman_ignore_chown_errors": "1",
            "require_resource_limits": "1",
            "exec_timeout_ceiling": "270",
            "task_pids_limit": "512",
            "observability": "1",
            "pool_heartbeat_timeout": "45s",
            "pool_create_workers": str(min(environment["pool_size"], 4)),
            "pool_bootstrap_workers": str(min(environment["pool_size"], 64)),
            "pool_bootstrap_per_image": str(min(environment["pool_size"], 8)),
            "pool_drain_workers": str(min(environment["pool_size"], 32)),
            "pool_drain_timeout": "240",
            "pool_renew_workers": str(min(environment["pool_size"], 16)),
            "session_reuse": "1",
            "pool_max_reuse_count": "1",
            "pool_reuse_jitter": "0",
            "image_cache_max_entries": "0",
            "secret_cache_ttl": "5s",
            "lease_duration": "1h",
            "pool_renew_interval": "5m",
        }
        if any(environment.get(key) != value for key, value in expected_policy.items()):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        return identity
    if not isinstance(environment, dict) or set(environment) != {
        "vacli_bin",
        "lease_start_concurrency",
        "lease_retries",
        "max_pull_retries",
        "image_pull_timeout_sec",
        "container_privileged",
    }:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if (
        not isinstance(environment.get("vacli_bin"), str)
        or not environment["vacli_bin"]
        or any(
            not _validate_positive_integer(environment.get(key))
            for key in (
                "lease_start_concurrency",
                "lease_retries",
                "max_pull_retries",
                "image_pull_timeout_sec",
            )
        )
        or environment["lease_start_concurrency"] > execution["rollout_concurrency"]
        or not isinstance(environment.get("container_privileged"), bool)
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if "harness" in contract and (
        execution.get("cleanup_must_succeed") is not True
        or execution.get("cleanup_receipt_contract") != VMVM_HOST_CLEANUP_CONTRACT
    ):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    return identity


def _load_bound_endpoint(identity: dict[str, Any]) -> Any:
    deployment = identity["deployment"]
    try:
        endpoint = validate_endpoint_binding(deployment["endpoint"])
        observed = load_deployment_endpoint(
            Path(endpoint["proxy_info"]["path"]),
            deployment_id=deployment["id"],
            expected_model=identity["contract"]["model"],
            deployment_spec=Path(deployment["spec"]["path"]),
            expected_proxy_info_sha256=endpoint["proxy_info"]["sha256"],
        )
    except EndpointBindingError as error:
        raise EvalIdentityError("deployment_endpoint_invalid") from error
    if observed.binding != endpoint:
        raise EvalIdentityError("deployment_endpoint_mismatch")
    return observed


def _verify_checkpoint_records(
    identity: dict[str, Any],
    endpoint: dict[str, Any],
    *,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> None:
    deployment = identity["deployment"]
    if not isinstance(deployment, dict):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    spec = deployment.get("spec")
    readiness = deployment.get("readiness_checkpoint")
    smoke = deployment.get("smoke_checkpoint")
    promotion = deployment.get("promotion_certificate")
    if (deployment_spec_snapshot is None) != (proxy_policy_snapshot is None):
        raise EvalIdentityError("deployment_snapshot_incomplete")
    for label, record in (("deployment_spec", spec), ("readiness_checkpoint", readiness)):
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        if label != "deployment_spec" or deployment_spec_snapshot is None:
            _artifact(Path(record["path"]), record["sha256"], label=label)
    readiness_payload = _json_artifact(readiness, label="readiness_checkpoint")
    try:
        readiness_endpoint = validate_endpoint_binding(readiness_payload.get("endpoint"))
        readiness_generation = validate_readiness_route_generation(
            readiness_payload,
            deployment_id=deployment.get("id"),
            deployment_spec_sha256=spec["sha256"],
        )
        expected_request_timeout = request_timeout_for_model(identity["contract"]["model"])
        readiness_proxy_policy = validate_proxy_policy_binding(
            readiness_payload.get("proxy_policy"),
            expected_request_timeout=expected_request_timeout,
        )
        if deployment_spec_snapshot is not None and proxy_policy_snapshot is not None:
            validate_deployment_proxy_policy_snapshot(
                deployment_spec_snapshot,
                proxy_policy_snapshot,
                expected_spec_sha256=spec["sha256"],
                expected_binding=readiness_proxy_policy,
            )
    except (
        EndpointBindingError,
        RouteGenerationError,
        DeploymentProxyPolicyError,
    ) as error:
        raise EvalIdentityError("readiness_checkpoint_endpoint_invalid") from error
    if (
        readiness_payload.get("schema_version") != 1
        or readiness_payload.get("state") != "passed"
        or readiness_payload.get("deployment") != deployment.get("id")
        or readiness_payload.get("observed_spec_sha256") != spec["sha256"]
        or not isinstance(readiness_payload.get("probe"), dict)
        or readiness_payload["probe"].get("ok") is not True
        or readiness_endpoint != endpoint
        or readiness_generation != deployment.get("serving_route_generation")
        or readiness_proxy_policy != deployment.get("proxy_policy")
    ):
        raise EvalIdentityError("readiness_checkpoint_not_passed")
    if identity["role"] == "smoke":
        if smoke is not None:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        return
    if not isinstance(smoke, dict) or set(smoke) != {"path", "sha256"}:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    _artifact(Path(smoke["path"]), smoke["sha256"], label="smoke_checkpoint")
    smoke_payload = _json_artifact(smoke, label="smoke_checkpoint")
    if smoke_payload.get("schema_version") == 1:
        _validate_smoke_checkpoint_payload(
            smoke_payload,
            deployment_id=deployment["id"],
            deployment_spec_sha256=spec["sha256"],
            readiness=readiness,
            endpoint=endpoint,
            serving_route_generation=readiness_generation,
            proxy_policy=readiness_proxy_policy,
            deployment_spec_snapshot=deployment_spec_snapshot,
            proxy_policy_snapshot=proxy_policy_snapshot,
        )
    else:
        try:

            def identity_loader(path: Path, *, verify_references: bool) -> dict[str, Any]:
                return load_eval_run_identity(
                    path,
                    verify_references=verify_references,
                    deployment_spec_snapshot=deployment_spec_snapshot,
                    proxy_policy_snapshot=proxy_policy_snapshot,
                )

            evidence = validate_smoke_qualification(
                Path(smoke["path"]),
                smoke["sha256"],
                deployment_id=deployment["id"],
                deployment_spec_path=Path(spec["path"]),
                deployment_spec_sha256=spec["sha256"],
                readiness_path=Path(readiness["path"]),
                readiness_sha256=readiness["sha256"],
                proxy_info_path=Path(endpoint["proxy_info"]["path"]),
                proxy_info_sha256=endpoint["proxy_info"]["sha256"],
                model=identity["contract"]["model"],
                identity_loader=identity_loader,
                deployment_spec_snapshot=deployment_spec_snapshot,
                proxy_policy_snapshot=proxy_policy_snapshot,
            )
            validate_target_evaluator_compatibility(identity, evidence.evaluator_evidence)
        except SmokeQualificationError as error:
            raise EvalIdentityError("smoke_checkpoint_not_passed") from error
    if identity["role"] == "mobius":
        assert isinstance(promotion, dict)
        _artifact(Path(promotion["path"]), promotion["sha256"], label="promotion_certificate")
        promotion_payload = _json_artifact(promotion, label="promotion_certificate")
        promotion_deployment = promotion_payload.get("deployment")
        try:
            promotion_endpoint = validate_endpoint_binding(
                promotion_deployment.get("endpoint") if isinstance(promotion_deployment, dict) else None
            )
            promotion_generation = validate_route_generation(
                promotion_deployment.get("serving_route_generation") if isinstance(promotion_deployment, dict) else None
            )
            promotion_proxy_policy = validate_proxy_policy_binding(
                promotion_deployment.get("proxy_policy") if isinstance(promotion_deployment, dict) else None
            )
        except (
            EndpointBindingError,
            RouteGenerationError,
            DeploymentProxyPolicyError,
        ) as error:
            raise EvalIdentityError("promotion_certificate_endpoint_invalid") from error
        if (
            promotion_endpoint != endpoint
            or promotion_generation != readiness_generation
            or promotion_proxy_policy != readiness_proxy_policy
        ):
            raise EvalIdentityError("promotion_certificate_endpoint_mismatch")


def _verify_source_record(source: object) -> None:
    common_keys = {
        "project_root",
        "prime_rl_commit",
        "prime_rl_tree_sha256",
        "verifiers_commit",
        "verifiers_tree_sha256",
        "renderers_commit",
        "renderers_tree_sha256",
    }
    if not isinstance(source, dict):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    sandbox_provider = source.get("sandbox_provider", "vmvm")
    expected_keys = (
        common_keys | {"vmvm_tb_v2_sha256"}
        if sandbox_provider == "vmvm"
        else common_keys
        | {
            "sandbox_provider",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
            "sandoq_client_version",
            "sandoq_site",
            "sandoq_site_sha256",
            "sandoq_host_harness_sha256",
            "derived_image_manifest_sha256",
        }
    )
    if sandbox_provider not in {"vmvm", "sandoq"} or set(source) != expected_keys:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    root = Path(source["project_root"]).resolve(strict=True)
    for label, repository, revision_key, tree_key in (
        ("prime_rl", root, "prime_rl_commit", "prime_rl_tree_sha256"),
        ("verifiers", root / "deps/verifiers", "verifiers_commit", "verifiers_tree_sha256"),
        ("renderers", root / "deps/renderers", "renderers_commit", "renderers_tree_sha256"),
    ):
        revision = source[revision_key]
        if not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        if _git_output(repository, "rev-parse", "--verify", "HEAD", label=label).strip() != revision:
            raise EvalIdentityError(f"{label}_commit_mismatch")
        status = _git_output(
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            label=label,
        )
        if source[tree_key] != _sha256_bytes(status.encode()) or status.strip():
            raise EvalIdentityError(f"{label}_worktree_not_clean")
    if sandbox_provider == "vmvm" and source["vmvm_tb_v2_sha256"] != _vmvm_source_sha256(root):
        raise EvalIdentityError("vmvm_source_sha256_mismatch")
    if sandbox_provider == "sandoq":
        _validate_vendored_sandoq_provider(
            root,
            expected_commit=source["sandoq_provider_commit"],
            expected_tree=source["sandoq_provider_tree"],
        )
        if source["sandoq_site_sha256"] != _sandoq_site_sha256(Path(source["sandoq_site"])):
            raise EvalIdentityError("sandoq_site_sha256_mismatch")
        if source["sandoq_host_harness_sha256"] != _sandoq_host_harness_sha256(root):
            raise EvalIdentityError("sandoq_host_harness_sha256_mismatch")


def _verify_config_and_inputs(
    identity: dict[str, Any],
    output_dir: Path,
    endpoint_client_base_url: str,
) -> dict[str, Any]:
    config_section = identity["config"]
    inputs = identity["inputs"]
    expected_local_paths = {
        config_section["source"]["path"]: output_dir / "inputs/source_config.toml",
        config_section["resolved"]["path"]: output_dir / "config.toml",
        inputs["manifest"]["path"]: output_dir / "inputs/manifest.json",
        inputs["task_file"]["path"]: output_dir / "inputs/task_file.txt",
    }
    if inputs["image_manifest"] is not None:
        expected_local_paths[inputs["image_manifest"]["path"]] = output_dir / "inputs/image_manifest.json"
    for recorded, expected in expected_local_paths.items():
        if Path(recorded).resolve(strict=True) != expected.resolve(strict=True):
            raise EvalIdentityError("eval_run_identity_artifact_path_mismatch")

    config = _load_resolved_config(Path(config_section["resolved"]["path"]))
    output_value = config.get("output_dir")
    if not isinstance(output_value, str) or Path(output_value).resolve() != output_dir.resolve():
        raise EvalIdentityError("resolved_output_dir_mismatch")
    observed_inputs, observed_source = _input_identity(
        output_dir / "inputs",
        config,
        inputs["task_file"]["sha256"],
        inputs["task_file"]["count"],
    )
    if observed_inputs != inputs or observed_source != config_section["source"]:
        raise EvalIdentityError("eval_inputs_identity_mismatch")

    direct_role = identity["role"] in DIRECT_ROLES
    identity_harness = identity["contract"].get("harness")
    legacy_direct_kimi_scored_smoke = (
        identity["role"] == "kimi-direct-smoke"
        and identity["dataset"].get("kind") == "archive"
        and isinstance(identity_harness, dict)
        and identity_harness.get("request_timeout_seconds")
        == KIMI_HOST_HARNESS_REQUEST_TIMEOUT_SECONDS
    )
    observed_contract, observed_execution = _contract(
        config,
        identity["contract"]["model"],
        (None if direct_role else identity["deployment"]["routing"]["deployment_id"]),
        role=identity["role"],
        sandbox_provider=identity["source"].get("sandbox_provider", "vmvm"),
        _allow_legacy_direct_scored_smoke=legacy_direct_kimi_scored_smoke,
    )
    client = config.get("client")
    if not isinstance(client, dict) or client.get("base_url") != endpoint_client_base_url:
        raise EvalIdentityError("model_endpoint_binding_mismatch")
    if observed_contract != identity["contract"] or any(
        identity["execution"].get(key) != value for key, value in observed_execution.items()
    ):
        raise EvalIdentityError("eval_config_contract_mismatch")
    direct_kimi_scored_smoke = (
        identity["role"] == "kimi-direct-smoke"
        and identity["dataset"].get("kind") == "archive"
    )
    expected_request_timeout = (
        KIMI_DIRECT_SCORED_SMOKE_REQUEST_TIMEOUT_SECONDS
        if direct_kimi_scored_smoke and not legacy_direct_kimi_scored_smoke
        else request_timeout_for_model(observed_contract["model"])
    )
    if config["client"].get("timeout") != expected_request_timeout or (
        not direct_role
        and identity["deployment"]["proxy_policy"]["request_timeout"] != expected_request_timeout
    ):
        raise EvalIdentityError("deployment_proxy_timeout_mismatch")

    taskset = config.get("taskset")
    dataset = identity["dataset"]
    if (
        not isinstance(taskset, dict)
        or not isinstance(taskset.get("dataset_dir"), str)
        or Path(taskset["dataset_dir"]).resolve() != Path(dataset["path"]).resolve()
    ):
        raise EvalIdentityError("resolved_dataset_path_mismatch")
    if dataset["kind"] == "git_revision":
        if taskset.get("dataset_revision") != dataset["revision"]:
            raise EvalIdentityError("dataset_revision_config_mismatch")
    elif taskset.get("dataset_revision") is not None or taskset.get("use_declared_images") is not True:
        raise EvalIdentityError("dataset_archive_config_invalid")
    return config


def _verify_saved_provenance(output_dir: Path, identity: dict[str, Any], identity_sha256: str) -> None:
    source = identity["source"]
    sandbox_provider = source.get("sandbox_provider", "vmvm")
    stable = {
        "prime_rl": source["prime_rl_commit"],
        "prime_rl_tree": source["prime_rl_tree_sha256"],
        "verifiers": source["verifiers_commit"],
        "verifiers_tree": source["verifiers_tree_sha256"],
        "renderers": source["renderers_commit"],
        "renderers_tree": source["renderers_tree_sha256"],
        "eval_run_role": identity["role"],
        "eval_run_identity_sha256": identity_sha256,
        "approval_task_file_sha256": identity["inputs"]["task_file"]["sha256"],
        "approval_task_count": str(identity["inputs"]["task_file"]["count"]),
    }
    if identity["role"] in DIRECT_ROLES:
        stable.update(
            {
                "direct_worker_manifest_sha256": identity["deployment"]["worker_manifest"]["sha256"],
                "direct_spec_sha256": identity["deployment"]["spec_sha256"],
                "direct_endpoint_bundle_sha256": identity["deployment"]["endpoint_bundle_sha256"],
            }
        )
        if identity["role"] == "kimi-direct-tb4":
            stable["direct_kimi_smoke_checkpoint_sha256"] = identity["deployment"]["smoke_checkpoint"]["sha256"]
    else:
        stable.update(
            {
                "deployment_id": identity["deployment"]["id"],
                "deployment_endpoint_authority_sha256": identity["deployment"]["endpoint"]["authority_sha256"],
                "deployment_proxy_info_sha256": identity["deployment"]["endpoint"]["proxy_info"]["sha256"],
            }
        )
    if sandbox_provider == "vmvm":
        stable["vmvm_tb_v2"] = source["vmvm_tb_v2_sha256"]
    else:
        environment = identity["execution"]["sandoq_environment"]
        stable.update(
            {
                "sandbox_provider": "sandoq",
                "sandoq_provider_commit": source["sandoq_provider_commit"],
                "sandoq_provider_tree": source["sandoq_provider_tree"],
                "sandoq_client_version": source["sandoq_client_version"],
                "sandoq_site_sha256": source["sandoq_site_sha256"],
                "sandoq_host_harness_sha256": source["sandoq_host_harness_sha256"],
                "derived_image_manifest_sha256": source["derived_image_manifest_sha256"],
                "sandoq_environment": environment["environment"],
                "sandoq_task_network": environment["task_network"],
                "sandoq_pool_size": str(environment["pool_size"]),
                "sandoq_pool_min_size": str(environment["pool_min_size"]),
                "sandoq_tunnel_policy": environment["tunnel_policy"],
                "sandoq_base_url": environment["base_url"],
                "sandoq_owner": environment["owner"],
                "sandoq_transport_proxy_policy": environment["transport_proxy_policy"],
                "sandoq_pool_socket_scope": environment["pool_socket_scope"],
                "sandoq_pool_wal": environment["pool_wal"],
                "sandoq_pool_event_log": environment["pool_event_log"],
                "sandoq_use_ecr": str(environment["use_ecr"]).lower(),
                "sandoq_ecr_registry": environment["ecr_registry"],
                "sandoq_ecr_region": environment["ecr_region"],
                "sandoq_ecr_pull_through_prefix": environment["ecr_pull_through_prefix"],
                "sandoq_ecr_token_file": environment["ecr_token_file"],
                "sandoq_ecr_auth_policy": environment["ecr_auth_policy"],
                "sandoq_allow_dockerhub_fallback": str(environment["allow_dockerhub_fallback"]).lower(),
            }
        )
        stable.update(
            {
                f"sandoq_{key}": str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in environment.items()
                if key
                in {
                    "create_deadline",
                    "pull_timeout",
                    "pull_poll_max_errors",
                    "gateway_retry_attempts",
                    "gateway_retry_interval",
                    "podman_ignore_chown_errors",
                    "require_resource_limits",
                    "exec_timeout_ceiling",
                    "task_pids_limit",
                    "observability",
                    "pool_heartbeat_timeout",
                    "pool_create_workers",
                    "pool_bootstrap_workers",
                    "pool_bootstrap_per_image",
                    "pool_drain_workers",
                    "pool_drain_timeout",
                    "pool_renew_workers",
                    "session_reuse",
                    "pool_max_reuse_count",
                    "pool_reuse_jitter",
                    "image_cache_max_entries",
                    "secret_cache_ttl",
                    "lease_duration",
                    "pool_renew_interval",
                }
            }
        )
    saved = _parse_provenance(output_dir / "provenance.txt")
    if (
        set(saved) != {*stable, "host", "slurm_job_id"}
        or any(saved.get(key) != value for key, value in stable.items())
        or not saved.get("host", "").strip()
        or not saved.get("slurm_job_id", "").isdigit()
    ):
        raise EvalIdentityError("eval_provenance_mismatch")


def load_eval_run_identity(
    path: Path,
    *,
    verify_references: bool = True,
    deployment_spec_snapshot: Path | None = None,
    proxy_policy_snapshot: Path | None = None,
) -> dict[str, Any]:
    raw = _read_bytes(path, label="eval_run_identity")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvalIdentityError("eval_run_identity_invalid") from error
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "eval_run_identity_sha256",
        "identity",
    }:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    identity = _validate_identity_shape(envelope.get("identity"))
    digest = envelope.get("eval_run_identity_sha256")
    if envelope.get("schema_version") != 1 or digest != _sha256_bytes(canonical_json(identity)):
        raise EvalIdentityError("eval_run_identity_digest_mismatch")
    if not verify_references:
        return envelope
    _verify_source_record(identity["source"])
    for section, label in (
        (identity["config"], "config"),
        (identity["inputs"], "inputs"),
    ):
        if not isinstance(section, dict):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        records = section.values()
        for record in records:
            if record is None:
                continue
            if not isinstance(record, dict) or not {"path", "sha256"}.issubset(record):
                raise EvalIdentityError("eval_run_identity_schema_invalid")
            if not isinstance(record["path"], str) or not isinstance(record["sha256"], str):
                raise EvalIdentityError("eval_run_identity_schema_invalid")
            _artifact(Path(record["path"]), record["sha256"], label=label)
    direct_role = identity["role"] in DIRECT_ROLES
    if direct_role:
        deployment = identity["deployment"]
        _artifact(
            Path(deployment["worker_manifest"]["path"]),
            deployment["worker_manifest"]["sha256"],
            label="direct_worker_manifest",
        )
        if identity["role"] == "kimi-direct-tb4":
            smoke = deployment["smoke_checkpoint"]
            _artifact(Path(smoke["path"]), smoke["sha256"], label="direct_kimi_smoke_checkpoint")
        endpoint_client_base_url = deployment["base_url"]
        endpoint_info = None
    else:
        endpoint_info = _load_bound_endpoint(identity)
        endpoint_client_base_url = endpoint_info.client_base_url
    _verify_config_and_inputs(identity, path.resolve().parent, endpoint_client_base_url)
    dataset = identity["dataset"]
    if not isinstance(dataset, dict):
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if dataset.get("kind") == "archive":
        archive = dataset.get("archive")
        if not isinstance(archive, dict):
            raise EvalIdentityError("eval_run_identity_schema_invalid")
        _verified_archive_content(
            Path(archive["path"]),
            archive["sha256"],
            dataset.get("content_sha256"),
        )
        if _tree_digest(Path(dataset["path"])) != dataset.get("content_sha256"):
            raise EvalIdentityError("dataset_content_sha256_mismatch")
    elif dataset.get("kind") == "git_revision":
        root = Path(dataset["path"])
        if _git_output(root, "rev-parse", "--verify", "HEAD", label="dataset_revision").strip() != dataset.get(
            "revision"
        ):
            raise EvalIdentityError("dataset_revision_mismatch")
        if _git_output(root, "status", "--porcelain=v1", "--untracked-files=all", label="dataset_revision").strip():
            raise EvalIdentityError("dataset_worktree_not_clean")
    else:
        raise EvalIdentityError("eval_run_identity_schema_invalid")
    if not direct_role:
        assert endpoint_info is not None
        _verify_checkpoint_records(
            identity,
            endpoint_info.binding,
            deployment_spec_snapshot=deployment_spec_snapshot,
            proxy_policy_snapshot=proxy_policy_snapshot,
        )
    assert isinstance(digest, str)
    _verify_saved_provenance(path.resolve().parent, identity, digest)
    return envelope


def _bind_identity(output_dir: Path, identity: dict[str, Any], *, resume: bool) -> str:
    expected = _identity_envelope(identity)
    path = output_dir / "eval_run_identity.json"
    if resume:
        if not path.is_file():
            raise EvalIdentityError("legacy_resume_missing_eval_run_identity")
        saved = load_eval_run_identity(path, verify_references=False)
        if saved != expected:
            raise EvalIdentityError("eval_run_identity_mismatch")
        return expected["eval_run_identity_sha256"]
    if path.exists() or path.is_symlink():
        raise EvalIdentityError("fresh_eval_run_identity_already_exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(expected, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise EvalIdentityError("fresh_eval_run_identity_already_exists") from error
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return expected["eval_run_identity_sha256"]


def _parse_provenance(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvalIdentityError("eval_provenance_unreadable") from error
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise EvalIdentityError("eval_provenance_invalid")
        records[key] = value
    return records


def _bind_provenance(
    output_dir: Path,
    identity: dict[str, Any],
    identity_sha256: str,
    args: argparse.Namespace,
) -> None:
    source = identity["source"]
    sandbox_provider = source.get("sandbox_provider", "vmvm")
    stable = {
        "prime_rl": source["prime_rl_commit"],
        "prime_rl_tree": source["prime_rl_tree_sha256"],
        "verifiers": source["verifiers_commit"],
        "verifiers_tree": source["verifiers_tree_sha256"],
        "renderers": source["renderers_commit"],
        "renderers_tree": source["renderers_tree_sha256"],
        "eval_run_role": identity["role"],
        "eval_run_identity_sha256": identity_sha256,
        "approval_task_file_sha256": identity["inputs"]["task_file"]["sha256"],
        "approval_task_count": str(identity["inputs"]["task_file"]["count"]),
    }
    if identity["role"] in DIRECT_ROLES:
        stable.update(
            {
                "direct_worker_manifest_sha256": identity["deployment"]["worker_manifest"]["sha256"],
                "direct_spec_sha256": identity["deployment"]["spec_sha256"],
                "direct_endpoint_bundle_sha256": identity["deployment"]["endpoint_bundle_sha256"],
            }
        )
        if identity["role"] == "kimi-direct-tb4":
            stable["direct_kimi_smoke_checkpoint_sha256"] = identity["deployment"]["smoke_checkpoint"]["sha256"]
    else:
        stable.update(
            {
                "deployment_id": identity["deployment"]["id"],
                "deployment_endpoint_authority_sha256": identity["deployment"]["endpoint"]["authority_sha256"],
                "deployment_proxy_info_sha256": identity["deployment"]["endpoint"]["proxy_info"]["sha256"],
            }
        )
    if sandbox_provider == "vmvm":
        stable["vmvm_tb_v2"] = source["vmvm_tb_v2_sha256"]
    else:
        environment = identity["execution"]["sandoq_environment"]
        stable.update(
            {
                "sandbox_provider": sandbox_provider,
                "sandoq_provider_commit": source["sandoq_provider_commit"],
                "sandoq_provider_tree": source["sandoq_provider_tree"],
                "sandoq_client_version": source["sandoq_client_version"],
                "sandoq_site_sha256": source["sandoq_site_sha256"],
                "sandoq_host_harness_sha256": source["sandoq_host_harness_sha256"],
                "derived_image_manifest_sha256": source["derived_image_manifest_sha256"],
                "sandoq_environment": environment["environment"],
                "sandoq_task_network": environment["task_network"],
                "sandoq_pool_size": str(environment["pool_size"]),
                "sandoq_pool_min_size": str(environment["pool_min_size"]),
                "sandoq_tunnel_policy": environment["tunnel_policy"],
                "sandoq_base_url": environment["base_url"],
                "sandoq_owner": environment["owner"],
                "sandoq_transport_proxy_policy": environment["transport_proxy_policy"],
                "sandoq_pool_socket_scope": environment["pool_socket_scope"],
                "sandoq_pool_wal": environment["pool_wal"],
                "sandoq_pool_event_log": environment["pool_event_log"],
                "sandoq_use_ecr": str(environment["use_ecr"]).lower(),
                "sandoq_ecr_registry": environment["ecr_registry"],
                "sandoq_ecr_region": environment["ecr_region"],
                "sandoq_ecr_pull_through_prefix": environment["ecr_pull_through_prefix"],
                "sandoq_ecr_token_file": environment["ecr_token_file"],
                "sandoq_ecr_auth_policy": environment["ecr_auth_policy"],
                "sandoq_allow_dockerhub_fallback": str(environment["allow_dockerhub_fallback"]).lower(),
            }
        )
        stable.update(
            {
                f"sandoq_{key}": str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in environment.items()
                if key
                in {
                    "create_deadline",
                    "pull_timeout",
                    "pull_poll_max_errors",
                    "gateway_retry_attempts",
                    "gateway_retry_interval",
                    "podman_ignore_chown_errors",
                    "require_resource_limits",
                    "exec_timeout_ceiling",
                    "task_pids_limit",
                    "observability",
                    "pool_heartbeat_timeout",
                    "pool_create_workers",
                    "pool_bootstrap_workers",
                    "pool_bootstrap_per_image",
                    "pool_drain_workers",
                    "pool_drain_timeout",
                    "pool_renew_workers",
                    "session_reuse",
                    "pool_max_reuse_count",
                    "pool_reuse_jitter",
                    "image_cache_max_entries",
                    "secret_cache_ttl",
                    "lease_duration",
                    "pool_renew_interval",
                }
            }
        )
    expected_keys = {*stable, "host", "slurm_job_id"}
    path = output_dir / "provenance.txt"
    if args.mode == "resume":
        saved = _parse_provenance(path)
        if (
            set(saved) != expected_keys
            or any(saved.get(key) != value for key, value in stable.items())
            or not saved.get("host", "").strip()
            or not saved.get("slurm_job_id", "").isdigit()
        ):
            raise EvalIdentityError("eval_provenance_mismatch")
    else:
        records = {
            **stable,
            "host": args.invocation_host,
            "slurm_job_id": args.slurm_job_id,
        }
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write("".join(f"{key}={value}\n" for key, value in records.items()))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise EvalIdentityError("eval_provenance_write_failed") from error

    invocation_path = output_dir / "eval_invocations.jsonl"
    if invocation_path.is_file():
        try:
            prior = [json.loads(line) for line in invocation_path.read_text().splitlines() if line]
        except (OSError, json.JSONDecodeError) as error:
            raise EvalIdentityError("eval_invocation_history_invalid") from error
        if any(
            not isinstance(record, dict) or record.get("eval_run_identity_sha256") != identity_sha256
            for record in prior
        ):
            raise EvalIdentityError("eval_invocation_history_mismatch")
    invocation = {
        "schema_version": 1,
        "eval_run_identity_sha256": identity_sha256,
        "role": identity["role"],
        "resume": args.mode == "resume",
        "host": args.invocation_host,
        "slurm_job_id": args.slurm_job_id,
    }
    with invocation_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(invocation, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def prepare(args: argparse.Namespace) -> str:
    if args.role == "qwen-direct":
        return _prepare_direct_qwen(args)
    if args.role in DIRECT_KIMI_ROLES:
        return _prepare_direct_kimi(args)
    if not isinstance(args.deployment_id, str) or METADATA_ID_RE.fullmatch(args.deployment_id) is None:
        raise EvalIdentityError("deployment_id_invalid")
    if args.routing_deployment_id is not None:
        if METADATA_ID_RE.fullmatch(args.routing_deployment_id) is None:
            raise EvalIdentityError("routing_deployment_id_invalid")
        if args.routing_deployment_id != args.deployment_id:
            raise EvalIdentityError("routing_deployment_id_mismatch")
    if not args.expected_model.strip() or any(character in args.expected_model for character in "\r\n"):
        raise EvalIdentityError("expected_model_invalid")
    if not args.invocation_host.strip() or any(character in args.invocation_host for character in "\r\n="):
        raise EvalIdentityError("invocation_host_invalid")
    if not args.slurm_job_id.isdigit():
        raise EvalIdentityError("slurm_job_id_invalid")
    if args.sandbox_provider == "vmvm" and not args.vacli_bin.strip():
        raise EvalIdentityError("vacli_bin_invalid")
    try:
        endpoint_info = load_deployment_endpoint(
            args.deployment_proxy_info,
            deployment_id=args.deployment_id,
            expected_model=args.expected_model,
            deployment_spec=args.deployment_spec,
            expected_proxy_info_sha256=args.deployment_proxy_info_sha256,
        )
    except EndpointBindingError as error:
        raise EvalIdentityError("deployment_endpoint_invalid") from error
    output_dir = args.output_dir.resolve()
    inputs_dir = args.inputs_dir.resolve(strict=True)
    config_path = output_dir / "config.toml"
    if args.mode == "resume" and not (output_dir / "eval_run_identity.json").is_file():
        raise EvalIdentityError("legacy_resume_missing_eval_run_identity")
    if args.mode == "fresh":
        if args.client_base_url is None:
            raise EvalIdentityError("client_base_url_required")
        config = _write_resolved_config(
            output_dir,
            inputs_dir,
            args.client_base_url,
            args.model_override,
            args.approved_task_file_sha256,
            args.routing_deployment_id,
        )
    else:
        config = _load_resolved_config(config_path)

    inputs, source_config = _input_identity(
        inputs_dir,
        config,
        args.approved_task_file_sha256,
        args.approved_task_count,
    )
    contract, execution = _contract(
        config,
        args.expected_model,
        args.routing_deployment_id,
        role=args.role,
        sandbox_provider=args.sandbox_provider,
    )
    client = config.get("client")
    if not isinstance(client, dict) or client.get("base_url") != endpoint_info.client_base_url:
        raise EvalIdentityError("model_endpoint_binding_mismatch")
    rollout_concurrency = execution["rollout_concurrency"]
    if args.sandbox_provider == "vmvm":
        execution["vmvm_environment"] = _effective_vmvm_environment(args, rollout_concurrency)
    else:
        execution["sandoq_environment"] = _effective_sandoq_environment(args, rollout_concurrency, output_dir)
        if execution["runtime"].get("ecr_token_file") != execution["sandoq_environment"]["ecr_token_file"]:
            raise EvalIdentityError("sandoq_ecr_token_file_invalid")
    source = _source_identity(args)
    if args.sandbox_provider == "sandoq" and (
        inputs["image_manifest"] is None
        or inputs["image_manifest"]["sha256"] != source["derived_image_manifest_sha256"]
    ):
        raise EvalIdentityError("derived_image_manifest_sha256_mismatch")
    deployment = _checkpoint_identity(args, endpoint_info.binding)
    expected_request_timeout = request_timeout_for_model(contract["model"])
    if (
        deployment["proxy_policy"]["request_timeout"] != expected_request_timeout
        or config["client"].get("timeout") != expected_request_timeout
    ):
        raise EvalIdentityError("deployment_proxy_timeout_mismatch")
    dataset = _dataset_identity(config, args)
    resolved_config = _artifact(
        config_path,
        _sha256_file(config_path, label="resolved_config"),
        label="resolved_config",
    )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "role": args.role,
        "source": source,
        "config": {"source": source_config, "resolved": resolved_config},
        "inputs": inputs,
        "dataset": dataset,
        "deployment": deployment,
        "contract": contract,
        "execution": execution,
    }
    if args.role != "smoke" and deployment["smoke_checkpoint"] is not None:
        smoke_payload = _json_artifact(
            deployment["smoke_checkpoint"],
            label="smoke_checkpoint",
        )
        if smoke_payload.get("schema_version") == 2:
            try:
                evidence = validate_smoke_qualification(
                    Path(deployment["smoke_checkpoint"]["path"]),
                    deployment["smoke_checkpoint"]["sha256"],
                    deployment_id=deployment["id"],
                    deployment_spec_path=Path(deployment["spec"]["path"]),
                    deployment_spec_sha256=deployment["spec"]["sha256"],
                    readiness_path=Path(deployment["readiness_checkpoint"]["path"]),
                    readiness_sha256=deployment["readiness_checkpoint"]["sha256"],
                    proxy_info_path=Path(endpoint_info.binding["proxy_info"]["path"]),
                    proxy_info_sha256=endpoint_info.binding["proxy_info"]["sha256"],
                    model=contract["model"],
                    identity_loader=load_eval_run_identity,
                )
                validate_target_evaluator_compatibility(identity, evidence.evaluator_evidence)
            except SmokeQualificationError as error:
                raise EvalIdentityError("smoke_checkpoint_target_evaluator_mismatch") from error
    identity_sha256 = _bind_identity(output_dir, identity, resume=args.mode == "resume")
    _bind_provenance(output_dir, identity, identity_sha256, args)
    return identity_sha256


def _prepare_direct_qwen(args: argparse.Namespace) -> str:
    if args.mode != "fresh":
        raise EvalIdentityError("direct_qwen_requires_fresh_identity")
    if args.expected_model != "Qwen3.8-2.4T-A95B":
        raise EvalIdentityError("direct_qwen_model_invalid")
    if (
        not args.invocation_host.strip()
        or any(character in args.invocation_host for character in "\r\n=")
        or not args.slurm_job_id.isdigit()
    ):
        raise EvalIdentityError("direct_qwen_invocation_invalid")
    if args.client_base_url is None:
        raise EvalIdentityError("client_base_url_required")
    output_dir = args.output_dir.resolve()
    inputs_dir = args.inputs_dir.resolve(strict=True)
    config_path = output_dir / "config.toml"
    config = _write_resolved_config(
        output_dir,
        inputs_dir,
        args.client_base_url,
        args.model_override,
        args.approved_task_file_sha256,
    )
    inputs, source_config = _input_identity(
        inputs_dir,
        config,
        args.approved_task_file_sha256,
        args.approved_task_count,
    )
    contract, execution = _contract(
        config,
        args.expected_model,
        role="qwen-direct",
        sandbox_provider=args.sandbox_provider,
    )
    if args.sandbox_provider == "sandoq":
        execution["sandoq_environment"] = _effective_sandoq_environment(
            args,
            execution["rollout_concurrency"],
            output_dir,
        )
        if execution["runtime"].get("ecr_token_file") != execution["sandoq_environment"]["ecr_token_file"]:
            raise EvalIdentityError("sandoq_ecr_token_file_invalid")
    else:
        execution["vmvm_environment"] = _effective_vmvm_environment(
            args,
            execution["rollout_concurrency"],
        )
    source = _source_identity(args)
    if args.sandbox_provider == "sandoq" and (
        inputs["image_manifest"] is None
        or inputs["image_manifest"]["sha256"] != source["derived_image_manifest_sha256"]
    ):
        raise EvalIdentityError("derived_image_manifest_sha256_mismatch")
    worker_manifest = _artifact(
        args.direct_worker_manifest,
        args.direct_worker_manifest_sha256,
        label="direct_worker_manifest",
    )
    for value, label in (
        (args.direct_spec_sha256, "direct_spec_sha256"),
        (args.direct_endpoint_bundle_sha256, "direct_endpoint_bundle_sha256"),
    ):
        if SHA256_RE.fullmatch(value or "") is None:
            raise EvalIdentityError(f"{label}_invalid")
    if args.direct_router_policy != "consistent_hash" or args.direct_request_id_headers != "x-session-id":
        raise EvalIdentityError("direct_router_policy_invalid")
    identity = {
        "schema_version": SCHEMA_VERSION,
        "role": "qwen-direct",
        "source": source,
        "config": {
            "source": source_config,
            "resolved": _artifact(
                config_path,
                _sha256_file(config_path, label="resolved_config"),
                label="resolved_config",
            ),
        },
        "inputs": inputs,
        "dataset": _dataset_identity(config, args),
        "deployment": {
            "kind": "direct_qwen",
            "worker_manifest": worker_manifest,
            "spec_sha256": args.direct_spec_sha256,
            "endpoint_bundle_sha256": args.direct_endpoint_bundle_sha256,
            "base_url": args.client_base_url,
            "router": {
                "policy": args.direct_router_policy,
                "request_id_headers": [args.direct_request_id_headers],
                "provider_concurrency": _positive_int(
                    args.direct_provider_concurrency,
                    "direct_provider_concurrency",
                ),
            },
        },
        "contract": contract,
        "execution": execution,
    }
    _validate_identity_shape(identity)
    digest = _bind_identity(output_dir, identity, resume=False)
    _bind_provenance(output_dir, identity, digest, args)
    return digest


def _prepare_direct_kimi(args: argparse.Namespace) -> str:
    from direct_kimi_workers import validate_saved_manifest

    if args.mode != "fresh" or args.sandbox_provider != "sandoq":
        raise EvalIdentityError("direct_kimi_requires_fresh_sandoq_identity")
    if args.expected_model != "Kimi-K3" or args.role not in DIRECT_KIMI_ROLES:
        raise EvalIdentityError("direct_kimi_model_or_role_invalid")
    if (
        not args.invocation_host.strip()
        or any(character in args.invocation_host for character in "\r\n=")
        or not args.slurm_job_id.isdigit()
    ):
        raise EvalIdentityError("direct_kimi_invocation_invalid")
    if args.client_base_url is None:
        raise EvalIdentityError("client_base_url_required")

    output_dir = args.output_dir.resolve()
    inputs_dir = args.inputs_dir.resolve(strict=True)
    config_path = output_dir / "config.toml"
    config = _write_resolved_config(
        output_dir,
        inputs_dir,
        args.client_base_url,
        args.model_override,
        args.approved_task_file_sha256,
    )
    inputs, source_config = _input_identity(
        inputs_dir,
        config,
        args.approved_task_file_sha256,
        args.approved_task_count,
    )
    contract, execution = _contract(
        config,
        args.expected_model,
        role=args.role,
        sandbox_provider="sandoq",
    )
    expected_concurrency = 1 if args.role == "kimi-direct-smoke" else 24
    if any(
        execution.get(key) != expected_concurrency
        for key in (
            "rollout_concurrency",
            "multiplex",
            "http_max_connections",
            "http_max_keepalive_connections",
        )
    ):
        raise EvalIdentityError("direct_kimi_concurrency_invalid")
    execution["sandoq_environment"] = _effective_sandoq_environment(
        args,
        execution["rollout_concurrency"],
        output_dir,
    )
    if execution["runtime"].get("ecr_token_file") != execution["sandoq_environment"]["ecr_token_file"]:
        raise EvalIdentityError("sandoq_ecr_token_file_invalid")
    source = _source_identity(args)
    if inputs["image_manifest"] is None or (
        inputs["image_manifest"]["sha256"] != source["derived_image_manifest_sha256"]
    ):
        raise EvalIdentityError("derived_image_manifest_sha256_mismatch")

    worker_manifest = _artifact(
        args.direct_worker_manifest,
        args.direct_worker_manifest_sha256,
        label="direct_kimi_worker_manifest",
    )
    try:
        manifest = validate_saved_manifest(Path(worker_manifest["path"]))
    except (OSError, ValueError) as error:
        raise EvalIdentityError("direct_kimi_worker_manifest_invalid") from error
    router = manifest["router"]
    if (
        args.client_base_url != f"http://127.0.0.1:{router['port']}/v1"
        or args.direct_spec_sha256 != manifest["source_spec_sha256"]
        or args.direct_endpoint_bundle_sha256 != manifest["endpoint_bundle_sha256"]
        or args.direct_router_policy != router["policy"]
        or args.direct_request_id_headers != router["request_id_headers"][0]
        or _positive_int(args.direct_provider_concurrency, "direct_provider_concurrency")
        != router["max_concurrent_requests"]
        or _positive_int(args.direct_request_timeout_seconds, "direct_request_timeout_seconds")
        != router["request_timeout_seconds"]
        or args.direct_retries != str(router["retries"])
        or _positive_int(args.direct_worker_count, "direct_worker_count") != len(manifest["workers"])
    ):
        raise EvalIdentityError("direct_kimi_router_contract_invalid")

    smoke_checkpoint = None
    if args.role == "kimi-direct-smoke":
        if args.smoke_checkpoint is not None or args.smoke_checkpoint_sha256 is not None:
            raise EvalIdentityError("direct_kimi_smoke_checkpoint_invalid")
    else:
        if args.smoke_checkpoint is None or args.smoke_checkpoint_sha256 is None:
            raise EvalIdentityError("direct_kimi_smoke_checkpoint_required")
        smoke_checkpoint = _artifact(
            args.smoke_checkpoint,
            args.smoke_checkpoint_sha256,
            label="direct_kimi_smoke_checkpoint",
        )
        payload = _json_artifact(smoke_checkpoint, label="direct_kimi_smoke_checkpoint")
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "direct-kimi-sandoq-smoke"
            or payload.get("state") != "passed"
            or payload.get("model") != "Kimi-K3"
            or payload.get("full_tb4_ready") is not True
            or payload.get("source_spec_sha256") != manifest["source_spec_sha256"]
            or payload.get("endpoint_bundle_sha256") != manifest["endpoint_bundle_sha256"]
        ):
            raise EvalIdentityError("direct_kimi_smoke_checkpoint_invalid")

    identity = {
        "schema_version": SCHEMA_VERSION,
        "role": args.role,
        "source": source,
        "config": {
            "source": source_config,
            "resolved": _artifact(
                config_path,
                _sha256_file(config_path, label="resolved_config"),
                label="resolved_config",
            ),
        },
        "inputs": inputs,
        "dataset": _dataset_identity(config, args),
        "deployment": {
            "kind": "direct_kimi",
            "worker_manifest": worker_manifest,
            "spec_sha256": manifest["source_spec_sha256"],
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "base_url": args.client_base_url,
            "router": {
                "implementation": router["implementation"],
                "implementation_sha256": router["implementation_sha256"],
                "policy": router["policy"],
                "request_id_headers": router["request_id_headers"],
                "provider_concurrency": router["max_concurrent_requests"],
                "request_timeout_seconds": router["request_timeout_seconds"],
                "retries": router["retries"],
                "worker_count": len(manifest["workers"]),
            },
            "smoke_checkpoint": smoke_checkpoint,
        },
        "contract": contract,
        "execution": execution,
    }
    _validate_identity_shape(identity)
    digest = _bind_identity(output_dir, identity, resume=False)
    _bind_provenance(output_dir, identity, digest, args)
    return digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fresh", "resume"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--client-base-url")
    parser.add_argument("--model-override")
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--approved-task-file-sha256", required=True)
    parser.add_argument("--approved-task-count", type=int, required=True)
    parser.add_argument(
        "--role",
        choices=("smoke", "tb4", "mobius", "qwen-direct", "kimi-direct-smoke", "kimi-direct-tb4"),
        required=True,
    )
    parser.add_argument("--dataset-revision")
    parser.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--dataset-archive-sha256")
    parser.add_argument("--dataset-content-sha256")
    parser.add_argument("--deployment-id")
    parser.add_argument("--routing-deployment-id")
    parser.add_argument("--deployment-spec", type=Path)
    parser.add_argument("--deployment-spec-sha256")
    parser.add_argument("--readiness-checkpoint", type=Path)
    parser.add_argument("--readiness-checkpoint-sha256")
    parser.add_argument("--deployment-proxy-info", type=Path)
    parser.add_argument("--deployment-proxy-info-sha256")
    parser.add_argument("--smoke-checkpoint", type=Path)
    parser.add_argument("--smoke-checkpoint-sha256")
    parser.add_argument("--promotion-certificate", type=Path)
    parser.add_argument("--promotion-certificate-sha256")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sandbox-provider", choices=("vmvm", "sandoq"), default="vmvm")
    parser.add_argument("--prime-rl-commit", required=True)
    parser.add_argument("--prime-rl-tree-sha256", required=True)
    parser.add_argument("--verifiers-commit", required=True)
    parser.add_argument("--verifiers-tree-sha256", required=True)
    parser.add_argument("--renderers-commit", required=True)
    parser.add_argument("--renderers-tree-sha256", required=True)
    parser.add_argument("--vmvm-tb-v2-sha256", default="")
    parser.add_argument("--vacli-bin", default="")
    parser.add_argument("--vacli-max-concurrent-leases", default="")
    parser.add_argument("--vacli-lease-retries", default="")
    parser.add_argument("--vacli-max-pull-retries", default="")
    parser.add_argument("--vacli-image-pull-timeout-seconds", default="")
    parser.add_argument("--vacli-container-privileged", default="")
    parser.add_argument("--sandoq-provider-commit")
    parser.add_argument("--sandoq-provider-tree")
    parser.add_argument("--sandoq-client-version")
    parser.add_argument("--sandoq-site", type=Path)
    parser.add_argument("--sandoq-site-sha256")
    parser.add_argument("--derived-image-manifest-sha256")
    parser.add_argument("--sandoq-environment", default="")
    parser.add_argument("--sandoq-task-network", default="")
    parser.add_argument("--sandoq-pool-size", default="")
    parser.add_argument("--sandoq-pool-min-size", default="")
    parser.add_argument("--sandoq-tunnel-policy", default="")
    parser.add_argument("--sandoq-base-url", default="")
    parser.add_argument("--sandoq-owner", default="")
    parser.add_argument("--sandoq-transport-proxy-policy", default="")
    parser.add_argument("--sandoq-pool-socket", default="")
    parser.add_argument("--sandoq-pool-wal", default="")
    parser.add_argument("--sandoq-pool-event-log", default="")
    parser.add_argument("--sandoq-use-ecr", default="")
    parser.add_argument("--sandoq-ecr-registry", default="")
    parser.add_argument("--sandoq-ecr-region", default="")
    parser.add_argument("--sandoq-ecr-pull-through-prefix", default="")
    parser.add_argument("--sandoq-ecr-token-file", default="")
    parser.add_argument("--sandoq-allow-dockerhub-fallback", default="")
    parser.add_argument("--sandoq-create-deadline", default="")
    parser.add_argument("--sandoq-pull-timeout", default="")
    parser.add_argument("--sandoq-pull-poll-max-errors", default="")
    parser.add_argument("--sandoq-gateway-retry-attempts", default="")
    parser.add_argument("--sandoq-gateway-retry-interval", default="")
    parser.add_argument("--sandoq-podman-ignore-chown-errors", default="")
    parser.add_argument("--sandoq-require-resource-limits", default="")
    parser.add_argument("--sandoq-exec-timeout-ceiling", default="")
    parser.add_argument("--sandoq-task-pids-limit", default="")
    parser.add_argument("--sandoq-observability", default="")
    parser.add_argument("--sandoq-pool-heartbeat-timeout", default="")
    parser.add_argument("--sandoq-pool-create-workers", default="")
    parser.add_argument("--sandoq-pool-bootstrap-workers", default="")
    parser.add_argument("--sandoq-pool-bootstrap-per-image", default="")
    parser.add_argument("--sandoq-pool-drain-workers", default="")
    parser.add_argument("--sandoq-pool-drain-timeout", default="")
    parser.add_argument("--sandoq-pool-renew-workers", default="")
    parser.add_argument("--sandoq-session-reuse", default="")
    parser.add_argument("--sandoq-pool-max-reuse-count", default="")
    parser.add_argument("--sandoq-pool-reuse-jitter", default="")
    parser.add_argument("--sandoq-image-cache-max-entries", default="")
    parser.add_argument("--sandoq-secret-cache-ttl", default="")
    parser.add_argument("--sandoq-lease-duration", default="")
    parser.add_argument("--sandoq-pool-renew-interval", default="")
    parser.add_argument("--direct-worker-manifest", type=Path)
    parser.add_argument("--direct-worker-manifest-sha256")
    parser.add_argument("--direct-spec-sha256")
    parser.add_argument("--direct-endpoint-bundle-sha256")
    parser.add_argument("--direct-router-policy")
    parser.add_argument("--direct-request-id-headers")
    parser.add_argument("--direct-provider-concurrency", default="")
    parser.add_argument("--direct-request-timeout-seconds", default="")
    parser.add_argument("--direct-retries", default="")
    parser.add_argument("--direct-worker-count", default="")
    parser.add_argument("--invocation-host", required=True)
    parser.add_argument("--slurm-job-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        digest = prepare(args)
    except (EvalIdentityError, OSError, RuntimeError, ValueError) as error:
        print(f"eval_identity_error:{error}", file=sys.stderr)
        return 2
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
