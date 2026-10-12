#!/usr/bin/env python3
"""Run the authoritative Sandoq drain and publish its sanitized receipt."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

import sanitize_sandoq_cleanup_audit as cleanup_sanitizer

CleanupAuditError = cleanup_sanitizer.CleanupAuditError

EXPECTED_PROVIDER_COMMIT = "4890302104d76220cef791c86d2009168597d35f"
EXPECTED_PROVIDER_TREE = "33f092a3982916660e12f472588e6ce34a906fc2"
PROVIDER_CLEANUP_RELATIVE = Path("recipes/sandoq_swerebench_v2_oci/verify_pool_cleanup.py")
SELF_RELATIVE = Path("user/tianhaowu/terminal_bench_vmvm/run_sandoq_verified_cleanup.py")
SANITIZER_RELATIVE = Path("user/tianhaowu/terminal_bench_vmvm/sanitize_sandoq_cleanup_audit.py")
GIT_REVISION_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_GIT_OUTPUT_BYTES = 4 * 1024 * 1024


class VerifiedCleanupError(RuntimeError):
    """The authoritative drain or its aggregate receipt was not verified."""


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stable_sha256(path: Path, code: str) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise VerifiedCleanupError(code) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
        ):
            raise VerifiedCleanupError(code)
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, 1 << 20):
            total += len(chunk)
            if total > MAX_GIT_OUTPUT_BYTES:
                raise VerifiedCleanupError(code)
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _file_identity(before) != _file_identity(after) or total != before.st_size:
        raise VerifiedCleanupError(code)
    return digest.hexdigest()


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
) -> bytes:
    try:
        completed = runner(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                os.fspath(root),
                *arguments,
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=120,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerifiedCleanupError("cleanup_source_closure_invalid") from error
    if completed.returncode != 0 or len(completed.stdout) > MAX_GIT_OUTPUT_BYTES:
        raise VerifiedCleanupError("cleanup_source_closure_invalid")
    return completed.stdout


def _has_ignored_python_state(raw: bytes) -> bool:
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        value = encoded.decode("utf-8", errors="surrogateescape")
        parts = value.split("/")
        name = parts[-1]
        if (
            "__pycache__" in parts
            or name.endswith((".pyc", ".pyo", ".pth"))
            or name in {"sitecustomize.py", "usercustomize.py"}
        ):
            return True
    return False


def validate_source_closure(
    *,
    project_root: Path,
    provider_root: Path,
    provider_cleanup: Path,
    expected_prime_commit: str,
    expected_prime_tree: str,
    expected_self_sha256: str,
    expected_sanitizer_sha256: str,
    expected_provider_cleanup_sha256: str,
    git_runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> None:
    expected_digests = (
        expected_self_sha256,
        expected_sanitizer_sha256,
        expected_provider_cleanup_sha256,
    )
    if (
        GIT_REVISION_RE.fullmatch(expected_prime_commit or "") is None
        or GIT_REVISION_RE.fullmatch(expected_prime_tree or "") is None
        or any(SHA256_RE.fullmatch(value or "") is None for value in expected_digests)
    ):
        raise VerifiedCleanupError("cleanup_source_closure_invalid")
    try:
        project = project_root.resolve(strict=True)
        provider = provider_root.resolve(strict=True)
        cleanup = provider_cleanup.resolve(strict=True)
        self_path = Path(__file__).resolve(strict=True)
        sanitizer_path = Path(cleanup_sanitizer.__file__).resolve(strict=True)
    except (OSError, TypeError) as error:
        raise VerifiedCleanupError("cleanup_source_closure_invalid") from error
    if (
        project != project_root
        or provider != provider_root
        or project / "deps/sandoq-provider" != provider
        or cleanup != provider / PROVIDER_CLEANUP_RELATIVE
        or self_path != project / SELF_RELATIVE
        or sanitizer_path != project / SANITIZER_RELATIVE
        or any(
            path.is_symlink()
            for path in (
                project_root,
                provider_root,
                provider_cleanup,
                Path(__file__),
                Path(cleanup_sanitizer.__file__),
            )
        )
        or _stable_sha256(self_path, "cleanup_source_closure_invalid")
        != expected_self_sha256
        or _stable_sha256(sanitizer_path, "cleanup_source_closure_invalid")
        != expected_sanitizer_sha256
        or _stable_sha256(cleanup, "cleanup_source_closure_invalid")
        != expected_provider_cleanup_sha256
    ):
        raise VerifiedCleanupError("cleanup_source_closure_invalid")
    expected = (
        (project, expected_prime_commit, expected_prime_tree),
        (provider, EXPECTED_PROVIDER_COMMIT, EXPECTED_PROVIDER_TREE),
    )
    for root, commit, tree in expected:
        if (
            _git(root, ["rev-parse", "HEAD"], runner=git_runner).decode("ascii").strip()
            != commit
            or _git(root, ["rev-parse", "HEAD^{tree}"], runner=git_runner)
            .decode("ascii")
            .strip()
            != tree
            or _git(
                root,
                ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
                runner=git_runner,
            )
            != b""
        ):
            raise VerifiedCleanupError("cleanup_source_closure_invalid")
        _git(root, ["diff", "--quiet", "--no-ext-diff", "HEAD", "--"], runner=git_runner)
        ignored = _git(
            root,
            ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
            runner=git_runner,
        )
        if _has_ignored_python_state(ignored):
            raise VerifiedCleanupError("cleanup_source_closure_invalid")


def _private_directory(path: Path, code: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise VerifiedCleanupError(code) from error
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise VerifiedCleanupError(code)
    return resolved


def _new_private_output(path: Path, root: Path, code: str) -> Path:
    if path.is_symlink() or os.path.lexists(path):
        raise VerifiedCleanupError(code)
    try:
        parent = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise VerifiedCleanupError(code) from error
    if parent != root and root not in parent.parents:
        raise VerifiedCleanupError(code)
    return resolved


def _private_artifact(path: Path, root: Path, code: str) -> os.stat_result:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        metadata = path.lstat()
    except (OSError, ValueError) as error:
        raise VerifiedCleanupError(code) from error
    if (
        path != resolved
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise VerifiedCleanupError(code)
    return metadata


def run_verified_cleanup(
    *,
    output_dir: Path,
    provider_cleanup: Path,
    base_url: str,
    owner: str,
    concurrency: int,
    event_log: Path,
    wal: Path,
    drain_marker: Path,
    sanitized_output: Path,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    project_root: Path | None = None,
    provider_root: Path | None = None,
    expected_prime_commit: str | None = None,
    expected_prime_tree: str | None = None,
    expected_self_sha256: str | None = None,
    expected_sanitizer_sha256: str | None = None,
    expected_provider_cleanup_sha256: str | None = None,
    source_validator: Callable[[], None] | None = None,
) -> None:
    root = _private_directory(output_dir, "cleanup_output_directory_invalid")
    try:
        resolved_provider_cleanup = provider_cleanup.resolve(strict=True)
        provider_metadata = provider_cleanup.lstat()
    except OSError as error:
        raise VerifiedCleanupError("cleanup_contract_invalid") from error
    if (
        provider_cleanup != resolved_provider_cleanup
        or provider_cleanup.is_symlink()
        or not stat.S_ISREG(provider_metadata.st_mode)
        or provider_metadata.st_uid != os.getuid()
        or provider_metadata.st_nlink != 1
        or base_url != "https://sandoq.eks-prod.cf.aws.metafb.cloud"
        or not owner
        or any(character in owner for character in "\r\n=")
        or isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not 1 <= concurrency <= 64
    ):
        raise VerifiedCleanupError("cleanup_contract_invalid")
    raw_audit = _new_private_output(
        root / "pool_cleanup_audit.json",
        root,
        "cleanup_output_not_fresh",
    )
    sanitized = _new_private_output(
        sanitized_output,
        root,
        "cleanup_output_not_fresh",
    )
    if source_validator is None:
        if (
            project_root is None
            or provider_root is None
            or expected_prime_commit is None
            or expected_prime_tree is None
            or expected_self_sha256 is None
            or expected_sanitizer_sha256 is None
            or expected_provider_cleanup_sha256 is None
        ):
            raise VerifiedCleanupError("cleanup_source_closure_invalid")

        def source_validator() -> None:
            validate_source_closure(
                project_root=project_root,
                provider_root=provider_root,
                provider_cleanup=provider_cleanup,
                expected_prime_commit=expected_prime_commit,
                expected_prime_tree=expected_prime_tree,
                expected_self_sha256=expected_self_sha256,
                expected_sanitizer_sha256=expected_sanitizer_sha256,
                expected_provider_cleanup_sha256=expected_provider_cleanup_sha256,
            )

    expected_inputs = {
        "event_log": event_log,
        "wal": wal,
    }
    input_identities: dict[str, tuple[int, ...]] = {}
    for label, path in expected_inputs.items():
        metadata = _private_artifact(path, root, f"cleanup_{label}_invalid")
        input_identities[label] = _file_identity(metadata)
    try:
        marker_parent = drain_marker.parent.resolve(strict=True)
        marker_parent_metadata = drain_marker.parent.lstat()
        marker = drain_marker.resolve(strict=False)
    except OSError as error:
        raise VerifiedCleanupError("cleanup_drain_marker_invalid") from error
    if (
        not drain_marker.is_absolute()
        or drain_marker != Path(os.path.normpath(drain_marker))
        or drain_marker.parent != marker_parent
        or not stat.S_ISDIR(marker_parent_metadata.st_mode)
        or marker_parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(marker_parent_metadata.st_mode) != 0o700
        or drain_marker.is_symlink()
        or os.path.lexists(drain_marker)
    ):
        raise VerifiedCleanupError("cleanup_drain_marker_invalid")

    source_validator()
    command: Sequence[str] = (
        sys.executable,
        os.fspath(provider_cleanup.resolve(strict=True)),
        "--output-dir",
        os.fspath(root),
        "--base-url",
        base_url,
        "--owner",
        owner,
        "--concurrency",
        str(concurrency),
    )
    try:
        completed = runner(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerifiedCleanupError("authoritative_cleanup_failed") from error
    if completed.returncode != 0:
        raise VerifiedCleanupError("authoritative_cleanup_failed")
    source_validator()
    raw_identity = _file_identity(
        _private_artifact(raw_audit, root, "authoritative_cleanup_evidence_invalid")
    )
    marker_identity = _file_identity(
        _private_artifact(marker, marker_parent, "cleanup_drain_marker_invalid")
    )
    try:
        cleanup_sanitizer.sanitize(raw_audit, event_log, wal, marker, sanitized)
    except (OSError, CleanupAuditError) as error:
        raise VerifiedCleanupError("sanitized_cleanup_failed") from error
    source_validator()
    if (
        _file_identity(_private_artifact(raw_audit, root, "authoritative_cleanup_evidence_changed"))
        != raw_identity
        or _file_identity(_private_artifact(marker, marker_parent, "cleanup_drain_marker_changed"))
        != marker_identity
        or any(
            _file_identity(_private_artifact(path, root, f"cleanup_{label}_changed"))
            != input_identities[label]
            for label, path in expected_inputs.items()
        )
    ):
        raise VerifiedCleanupError("cleanup_evidence_changed")
    _private_artifact(sanitized, root, "sanitized_cleanup_invalid")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider-cleanup", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--wal", type=Path, required=True)
    parser.add_argument("--drain-marker", type=Path, required=True)
    parser.add_argument("--sanitized-output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--provider-root", type=Path, required=True)
    parser.add_argument("--expected-prime-commit", required=True)
    parser.add_argument("--expected-prime-tree", required=True)
    parser.add_argument("--expected-self-sha256", required=True)
    parser.add_argument("--expected-sanitizer-sha256", required=True)
    parser.add_argument("--expected-provider-cleanup-sha256", required=True)
    try:
        run_verified_cleanup(**vars(parser.parse_args()))
    except VerifiedCleanupError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
