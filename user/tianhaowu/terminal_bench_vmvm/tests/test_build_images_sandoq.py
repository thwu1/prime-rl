from __future__ import annotations

import json
import sys
import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import build_images_sandoq as builder
import finalize_ecr_image_manifest as finalize
import pytest
import reconcile_sandoq_build_receipts as reconcile
import summarize_sandoq_build_failures as summarize


def _row(context: Path) -> dict[str, str]:
    return {
        "task": "synthetic-task",
        "role": "agent",
        "context_sha256": "a" * 64,
        "context": str(context),
        "image": "588845226011.dkr.ecr.us-east-2.amazonaws.com/repository:tag",
    }


def _args(tmp_path: Path, *, attempts: int = 3) -> SimpleNamespace:
    token = tmp_path / "token"
    token.write_text("opaque-token")
    token.chmod(0o600)
    return SimpleNamespace(
        status_root=tmp_path / "status",
        token_file=token,
        ecr_push_token_file=token,
        build_timeout=30,
        row_attempts=attempts,
    )


def test_upload_uses_bounded_glob_join_and_verifies_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object.__new__(builder.Session)
    session.info = object()
    commands: list[str] = []
    monkeypatch.setattr(builder, "UPLOAD_CHUNK", 4)

    def execute(command: str, timeout: int = 270) -> dict[str, object]:
        commands.append(command)
        return {"stdout": "", "exit_code": 0}

    session.exec = execute
    session.upload("/tmp/context.tar.gz", b"x" * 1000)

    assert len(commands) > 300
    final = commands[-1]
    assert len(final) < 500
    assert "/tmp/context.tar.gz.b64.*" in final
    assert "sha256sum" in final
    assert ".b64.00000000" not in final


def test_upload_uses_bounded_parallel_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object.__new__(builder.Session)
    session.info = object()
    in_flight = 0
    max_in_flight = 0

    monkeypatch.setattr(builder, "UPLOAD_CHUNK", 4)
    monkeypatch.setattr(builder, "UPLOAD_CONCURRENCY", 3)

    def execute(command: str, timeout: int = 270) -> dict[str, object]:
        nonlocal in_flight, max_in_flight
        if ".b64." in command and command.startswith("printf"):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            builder.time.sleep(0.01)
            in_flight -= 1
        return {"stdout": "", "exit_code": 0}

    session.exec = execute
    session.upload("/tmp/context.tar.gz", b"x" * 100)

    assert max_in_flight == 3


def test_build_recipe_configures_docker_short_name_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n")
    args = _args(tmp_path)
    args.status_root.mkdir()
    commands: list[str] = []

    class FakeSession:
        def __init__(self, _token: str) -> None:
            pass

        def start(self) -> None:
            pass

        def upload(self, _destination: str, _payload: bytes) -> None:
            pass

        def exec(self, command: str, timeout: int = 270) -> dict[str, object]:
            commands.append(command)
            if command.startswith("cat "):
                return {"stdout": "sha256:" + "b" * 64, "exit_code": 0}
            if "if test -f" in command:
                return {"stdout": "done:0", "exit_code": 0}
            return {"stdout": "started", "exit_code": 0}

        def stop(self) -> None:
            pass

    monkeypatch.setattr(builder, "Session", FakeSession)
    monkeypatch.setattr(builder, "_context_archive", lambda _path: b"archive")

    builder._build_one(_row(context), args)

    recipe = next(command for command in commands if command.startswith("setsid "))
    assert "unqualified-search-registries" in recipe
    assert "short-name-mode" in recipe
    assert "CONTAINERS_REGISTRIES_CONF=" in recipe


def test_context_archive_lowers_quoted_dockerfile_heredoc_without_mutating_source(
    tmp_path: Path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    original = """FROM example.invalid/base
RUN prepare && \\
    python3 - <<'PY'
import pathlib
pathlib.Path('/tmp/probe').write_text('ok')
PY
"""
    dockerfile.write_text(original)

    payload = builder._context_archive(context)

    with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as archive:
        lowered = archive.extractfile("Dockerfile").read().decode()
    assert dockerfile.read_text() == original
    assert "<<" not in lowered
    assert "\nimport pathlib\n" not in lowered
    assert "RUN prepare && printf %s " in lowered
    assert " | base64 -d | python3 -\n" in lowered


def test_dockerfile_lowering_rejects_unquoted_or_unterminated_heredoc() -> None:
    with pytest.raises(ValueError, match="unsupported heredoc"):
        builder._podman_compatible_dockerfile("RUN python3 - <<PY\nprint('x')\nPY\n")
    with pytest.raises(ValueError, match="no terminator"):
        builder._podman_compatible_dockerfile("RUN python3 - <<'PY'\nprint('x')\n")


def test_success_receipt_is_published_only_after_verified_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n")
    args = _args(tmp_path)
    args.status_root.mkdir()

    class FakeSession:
        def __init__(self, _token: str) -> None:
            pass

        def start(self) -> None:
            pass

        def upload(self, _destination: str, _payload: bytes) -> None:
            pass

        def exec(self, command: str, timeout: int = 270) -> dict[str, object]:
            if command.startswith("cat "):
                return {"stdout": "sha256:" + "b" * 64, "exit_code": 0}
            if "if test -f" in command:
                return {"stdout": "done:0", "exit_code": 0}
            return {"stdout": "started", "exit_code": 0}

        def stop(self) -> None:
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(builder, "Session", FakeSession)
    monkeypatch.setattr(builder, "_context_archive", lambda _path: b"archive")

    with pytest.raises(builder.BuildStageError, match="session_cleanup") as raised:
        builder._build_one(_row(context), args)

    assert raised.value.cleanup_verified is False
    assert not (args.status_root / f"{'a' * 64}.agent.json").exists()


def test_success_receipt_records_verified_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n")
    args = _args(tmp_path)
    args.status_root.mkdir()

    class FakeSession:
        def __init__(self, _token: str) -> None:
            pass

        def start(self) -> None:
            pass

        def upload(self, _destination: str, _payload: bytes) -> None:
            pass

        def exec(self, command: str, timeout: int = 270) -> dict[str, object]:
            if command.startswith("cat "):
                return {"stdout": "sha256:" + "b" * 64, "exit_code": 0}
            if "if test -f" in command:
                return {"stdout": "done:0", "exit_code": 0}
            return {"stdout": "started", "exit_code": 0}

        def stop(self) -> None:
            pass

    monkeypatch.setattr(builder, "Session", FakeSession)
    monkeypatch.setattr(builder, "_context_archive", lambda _path: b"archive")

    builder._build_one(_row(context), args)

    receipt = json.loads((args.status_root / f"{'a' * 64}.agent.json").read_text())
    assert receipt["state"] == "success"
    assert receipt["cleanup_verified"] is True


def test_row_retry_succeeds_without_publishing_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _args(tmp_path)
    args.status_root.mkdir()
    calls = 0

    def build(_row_value: dict[str, str], _args_value: SimpleNamespace) -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise builder.BuildStageError("context_upload", "TimeoutError", cleanup_verified=True)

    monkeypatch.setattr(builder, "_build_one", build)
    monkeypatch.setattr(builder.time, "sleep", lambda _delay: None)

    assert builder._build_with_retries(_row(tmp_path), args, 0) is True
    assert calls == 3
    assert not (args.status_root / f"{'a' * 64}.agent.json").exists()


def test_exhausted_row_retry_publishes_redacted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path, attempts=2)
    args.status_root.mkdir()

    def fail(_row_value: dict[str, str], _args_value: SimpleNamespace) -> None:
        raise builder.BuildStageError("image_build", "NonzeroExit", cleanup_verified=True)

    monkeypatch.setattr(builder, "_build_one", fail)
    monkeypatch.setattr(builder.time, "sleep", lambda _delay: None)

    assert builder._build_with_retries(_row(tmp_path), args, 0) is False
    receipt = json.loads((args.status_root / f"{'a' * 64}.agent.json").read_text())
    assert receipt == {
        **_row(tmp_path),
        "state": "failed",
        "attempts": 2,
        "failure_stage": "image_build",
        "failure_type": "NonzeroExit",
        "cleanup_verified": True,
        "diagnostic_class": None,
        "diagnostic_sha256": None,
    }


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (b"write failed: no space left on device", "disk_exhausted"),
        (b"fatal: could not resolve host: example.invalid", "network_resolution"),
        (b"pip: no matching distribution found", "package_resolution"),
        (b"opaque container build error", "unclassified"),
    ],
)
def test_build_log_classifier_is_redacted(message: bytes, expected: str) -> None:
    assert builder._classify_build_log(message) == expected


def test_capture_build_failure_is_owner_only_and_returns_digest(tmp_path: Path) -> None:
    class FakeSession:
        def exec(self, _command: str, timeout: int = 270) -> dict[str, object]:
            assert timeout == 30
            return {"stdout": "no space left on device\n", "stderr": ""}

    status = tmp_path / "status"
    failure_class, digest = builder._capture_build_failure(
        FakeSession(), "/tmp/build", _row(tmp_path), status
    )

    log_path = status / "failure-logs" / f"{'a' * 64}.agent.log"
    assert failure_class == "disk_exhausted"
    assert len(digest) == 64
    assert log_path.is_file()
    assert log_path.stat().st_mode & 0o777 == 0o600
    assert log_path.parent.stat().st_mode & 0o777 == 0o700


def test_failure_summary_is_aggregate_and_redacts_unsafe_labels(tmp_path: Path) -> None:
    status = tmp_path / "status"
    status.mkdir()
    (status / "first.json").write_text(
        json.dumps(
            {
                "task": "must-not-appear",
                "state": "failed",
                "failure_stage": "image_build",
                "diagnostic_class": "network_timeout",
                "cleanup_verified": True,
            }
        )
    )
    (status / "second.json").write_text(
        json.dumps(
            {
                "state": "failed",
                "failure_stage": "unsafe label with spaces",
                "diagnostic_class": "network_timeout",
                "cleanup_verified": False,
            }
        )
    )
    (status / "success.json").write_text(json.dumps({"state": "success"}))

    result = summarize.summarize(status)

    assert result["states"] == {"failed": 2, "success": 1}
    assert result["failure_stages"] == {"image_build": 1, "invalid": 1}
    assert result["diagnostic_classes"] == {"network_timeout": 2}
    assert result["failure_cleanup_verified"] == {"false": 1, "true": 1}
    assert "must-not-appear" not in json.dumps(result)


def test_reconcile_promotes_only_successful_terminal_rows_and_quarantines_failed(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.tsv"
    status = tmp_path / "status"
    logs = tmp_path / "logs"
    quarantine = tmp_path / "quarantine"
    status.mkdir()
    logs.mkdir()
    rows = [
        {
            "task": f"synthetic-{index}",
            "role": "agent",
            "context_sha256": str(index + 1) * 64,
            "context": f"/dataset/synthetic-{index}/environment",
            "image": f"{builder.REGISTRY}/repository:tag-{index}",
        }
        for index in range(2)
    ]
    plan.write_text("".join("\t".join(row.values()) + "\n" for row in rows))
    (logs / "sandoq_build_123_0.log").write_text("row=0 state=success\n")
    (logs / "sandoq_build_123_1.log").write_text("row=0 state=failed type=RuntimeError\n")
    for row in rows:
        (status / f"{row['context_sha256']}.agent.json").write_text(
            json.dumps({**row, "state": "success", "digest": "sha256:" + "a" * 64}) + "\n"
        )

    receipt = reconcile.reconcile(plan, logs, status, quarantine, "123", 2)

    assert receipt["success_outcomes_promoted"] == 1
    assert receipt["non_success_receipts_quarantined"] == 1
    assert receipt["failed_outcomes_without_receipts"] == 0
    assert receipt["unobserved_rows"] == 0
    promoted = json.loads((status / f"{'1' * 64}.agent.json").read_text())
    assert promoted["cleanup_verified"] is True
    assert not (status / f"{'2' * 64}.agent.json").exists()
    assert (quarantine / f"{'2' * 64}.agent.json").is_file()


def test_reconcile_rejects_incomplete_terminal_log_coverage(tmp_path: Path) -> None:
    plan = tmp_path / "plan.tsv"
    logs = tmp_path / "logs"
    logs.mkdir()
    plan.write_text(
        "synthetic\tagent\t"
        + "a" * 64
        + "\t/dataset/synthetic/environment\t"
        + f"{builder.REGISTRY}/repository:tag\n"
    )
    (logs / "sandoq_build_123_0.log").write_text("still running\n")

    with pytest.raises(SystemExit, match="one terminal outcome"):
        reconcile.reconcile(plan, logs, tmp_path / "status", tmp_path / "quarantine", "123", 1)

    receipt = reconcile.reconcile(
        plan,
        logs,
        tmp_path / "status",
        tmp_path / "quarantine",
        "123",
        1,
        require_complete=False,
    )
    assert receipt["terminal_outcomes"] == 0
    assert receipt["unobserved_rows"] == 1
    assert receipt["unobserved_rows_without_receipts"] == 1


def test_reconcile_preserves_cleanup_verified_success_from_newer_builder(tmp_path: Path) -> None:
    plan = tmp_path / "plan.tsv"
    logs = tmp_path / "logs"
    status = tmp_path / "status"
    quarantine = tmp_path / "quarantine"
    logs.mkdir()
    status.mkdir()
    row = _row(tmp_path)
    plan.write_text("\t".join(row.values()) + "\n")
    (logs / "sandoq_build_123_0.log").write_text("row=0 state=failed type=RuntimeError\n")
    receipt_path = status / f"{row['context_sha256']}.agent.json"
    receipt_path.write_text(
        json.dumps(
            {
                **row,
                "state": "success",
                "digest": "sha256:" + "b" * 64,
                "cleanup_verified": True,
            }
        )
        + "\n"
    )

    result = reconcile.reconcile(plan, logs, status, quarantine, "123", 1)

    assert result["verified_receipts_preserved"] == 1
    assert result["non_success_receipts_quarantined"] == 0
    assert receipt_path.is_file()


def test_manifest_finalizer_requires_cleanup_verified_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row(tmp_path)
    plan = tmp_path / "plan.tsv"
    status = tmp_path / "status"
    output = tmp_path / "manifest.json"
    status.mkdir()
    plan.write_text("\t".join(row.values()) + "\n")
    receipt_path = status / f"{row['context_sha256']}.agent.json"
    receipt = {**row, "state": "success", "digest": "sha256:" + "b" * 64}
    receipt_path.write_text(json.dumps(receipt) + "\n")
    argv = [
        "finalize_ecr_image_manifest.py",
        "--plan",
        str(plan),
        "--status-root",
        str(status),
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit, match="does not match"):
        finalize.main()

    receipt["cleanup_verified"] = True
    receipt_path.write_text(json.dumps(receipt) + "\n")
    finalize.main()

    manifest = json.loads(output.read_text())
    assert manifest["images"]["synthetic-task"]["agent"].endswith("@sha256:" + "b" * 64)
