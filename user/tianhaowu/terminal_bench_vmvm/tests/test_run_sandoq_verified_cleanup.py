from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import run_sandoq_verified_cleanup as cleanup


def _private_run(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    run = tmp_path / "run"
    control = run / "control"
    run.mkdir(mode=0o700)
    control.mkdir(mode=0o700)
    run.chmod(0o700)
    control.chmod(0o700)
    event_log = run / "pool_events.jsonl"
    wal = control / "sandoq-pool.wal.jsonl"
    for path in (event_log, wal):
        path.write_bytes(b"private fixture\n")
        path.chmod(0o600)
    drain = tmp_path / "node-local.drained.json"
    provider = tmp_path / "verify_pool_cleanup.py"
    provider.write_text("# fixture\n")
    return run, event_log, wal, drain, provider


def test_verified_cleanup_runs_authoritative_verifier_before_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run, event_log, wal, drain, provider = _private_run(tmp_path)
    calls: list[tuple[str, object]] = []

    def runner(command, **kwargs):
        calls.append(("runner", (tuple(command), kwargs)))
        (run / "pool_cleanup_audit.json").write_bytes(b"{}\n")
        drain.write_bytes(b"{}\n")
        (run / "pool_cleanup_audit.json").chmod(0o600)
        drain.chmod(0o600)
        return subprocess.CompletedProcess(command, 0)

    def sanitize(raw, observed_event, observed_wal, marker, output):
        calls.append(("sanitize", (raw, observed_event, observed_wal, marker, output)))
        output.write_bytes(b'{"state":"passed"}\n')
        output.chmod(0o600)

    monkeypatch.setattr(cleanup.cleanup_sanitizer, "sanitize", sanitize)
    output = run / "sandoq_cleanup_audit.json"
    cleanup.run_verified_cleanup(
        output_dir=run,
        provider_cleanup=provider,
        base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
        owner="fixture-owner",
        concurrency=32,
        event_log=event_log,
        wal=wal,
        drain_marker=drain,
        sanitized_output=output,
        runner=runner,
        source_validator=lambda: None,
    )

    command, kwargs = calls[0][1]
    assert command[:2] == (sys.executable, os.fspath(provider))
    assert kwargs == {
        "check": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    assert calls[1][0] == "sanitize"
    assert output.read_bytes() == b'{"state":"passed"}\n'


def test_verified_cleanup_rejects_hardlinked_wal_before_provider_call(
    tmp_path: Path,
) -> None:
    run, event_log, wal, drain, provider = _private_run(tmp_path)
    os.link(wal, tmp_path / "wal-alias")
    invoked = False

    def runner(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return subprocess.CompletedProcess([], 0)

    with pytest.raises(cleanup.VerifiedCleanupError, match="^cleanup_wal_invalid$"):
        cleanup.run_verified_cleanup(
            output_dir=run,
            provider_cleanup=provider,
            base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
            owner="fixture-owner",
            concurrency=32,
            event_log=event_log,
            wal=wal,
            drain_marker=drain,
            sanitized_output=run / "sandoq_cleanup_audit.json",
            runner=runner,
            source_validator=lambda: None,
        )

    assert invoked is False


def test_verified_cleanup_rejects_existing_sanitized_output(tmp_path: Path) -> None:
    run, event_log, wal, drain, provider = _private_run(tmp_path)
    output = run / "sandoq_cleanup_audit.json"
    output.write_bytes(b"existing")
    output.chmod(0o600)

    with pytest.raises(cleanup.VerifiedCleanupError, match="^cleanup_output_not_fresh$"):
        cleanup.run_verified_cleanup(
            output_dir=run,
            provider_cleanup=provider,
            base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
            owner="fixture-owner",
            concurrency=32,
            event_log=event_log,
            wal=wal,
            drain_marker=drain,
            sanitized_output=output,
        )


def test_verified_cleanup_revalidates_source_before_and_after_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run, event_log, wal, drain, provider = _private_run(tmp_path)
    checks = 0

    def source_validator() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise cleanup.VerifiedCleanupError("cleanup_source_closure_invalid")

    def runner(command, **_kwargs):
        (run / "pool_cleanup_audit.json").write_bytes(b"{}\n")
        drain.write_bytes(b"{}\n")
        (run / "pool_cleanup_audit.json").chmod(0o600)
        drain.chmod(0o600)
        return subprocess.CompletedProcess(command, 0)

    sanitized = False

    def sanitize(*_args):
        nonlocal sanitized
        sanitized = True

    monkeypatch.setattr(cleanup.cleanup_sanitizer, "sanitize", sanitize)
    with pytest.raises(cleanup.VerifiedCleanupError, match="^cleanup_source_closure_invalid$"):
        cleanup.run_verified_cleanup(
            output_dir=run,
            provider_cleanup=provider,
            base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
            owner="fixture-owner",
            concurrency=32,
            event_log=event_log,
            wal=wal,
            drain_marker=drain,
            sanitized_output=run / "sandoq_cleanup_audit.json",
            runner=runner,
            source_validator=source_validator,
        )

    assert checks == 2
    assert sanitized is False


def test_verified_cleanup_rejects_existing_drain_marker_before_provider_call(
    tmp_path: Path,
) -> None:
    run, event_log, wal, drain, provider = _private_run(tmp_path)
    drain.write_bytes(b"stale\n")
    drain.chmod(0o600)
    invoked = False

    def runner(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return subprocess.CompletedProcess([], 0)

    with pytest.raises(cleanup.VerifiedCleanupError, match="^cleanup_drain_marker_invalid$"):
        cleanup.run_verified_cleanup(
            output_dir=run,
            provider_cleanup=provider,
            base_url="https://sandoq.eks-prod.cf.aws.metafb.cloud",
            owner="fixture-owner",
            concurrency=32,
            event_log=event_log,
            wal=wal,
            drain_marker=drain,
            sanitized_output=run / "sandoq_cleanup_audit.json",
            runner=runner,
            source_validator=lambda: None,
        )

    assert invoked is False


def test_source_closure_binds_exact_repositories_and_file_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(cleanup.__file__).resolve().parents[3]
    provider = project / "deps/sandoq-provider"
    provider_script = provider / cleanup.PROVIDER_CLEANUP_RELATIVE
    expected = {
        project: ("1" * 40, "2" * 40),
        provider: (cleanup.EXPECTED_PROVIDER_COMMIT, cleanup.EXPECTED_PROVIDER_TREE),
    }

    def git(root, arguments, *, runner):
        del runner
        commit, tree = expected[root]
        if arguments == ["rev-parse", "HEAD"]:
            return f"{commit}\n".encode()
        if arguments == ["rev-parse", "HEAD^{tree}"]:
            return f"{tree}\n".encode()
        return b""

    monkeypatch.setattr(cleanup, "_git", git)
    arguments = {
        "project_root": project,
        "provider_root": provider,
        "provider_cleanup": provider_script,
        "expected_prime_commit": "1" * 40,
        "expected_prime_tree": "2" * 40,
        "expected_self_sha256": cleanup._stable_sha256(
            Path(cleanup.__file__).resolve(),
            "fixture",
        ),
        "expected_sanitizer_sha256": cleanup._stable_sha256(
            Path(cleanup.cleanup_sanitizer.__file__).resolve(),
            "fixture",
        ),
        "expected_provider_cleanup_sha256": cleanup._stable_sha256(
            provider_script,
            "fixture",
        ),
    }

    cleanup.validate_source_closure(**arguments)
    arguments["expected_provider_cleanup_sha256"] = "0" * 64
    with pytest.raises(
        cleanup.VerifiedCleanupError,
        match="^cleanup_source_closure_invalid$",
    ):
        cleanup.validate_source_closure(**arguments)
