import hashlib
from pathlib import Path

import certify_direct_qwen_sandoq as certificate_module
import pytest
from certify_direct_qwen_sandoq import DirectSandoqCertificateError, certify


def _identity(task_sha256: str, count: int) -> dict:
    return {
        "role": "qwen-direct",
        "source": {"sandbox_provider": "sandoq"},
        "execution": {
            "cleanup_must_succeed": True,
            "runtime": {"type": "sandoq"},
        },
        "inputs": {"task_file": {"sha256": task_sha256, "count": count}},
        "deployment": {"worker_manifest": {"sha256": "a" * 64}},
    }


def test_direct_sandoq_certificate_binds_identity_and_aggregate_results(tmp_path: Path, monkeypatch) -> None:
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("opaque-a\nopaque-b\n")
    task_sha256 = hashlib.sha256(task_file.read_bytes()).hexdigest()
    (tmp_path / ".writer.lock").write_bytes(b"")
    (tmp_path / "results.jsonl").write_text("{}\n{}\n")
    monkeypatch.setattr(
        certificate_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "identity": _identity(task_sha256, 2),
            "eval_run_identity_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        certificate_module,
        "_summarize_traces",
        lambda *_args, **_kwargs: ({"model_io_turns": 2}, []),
    )

    result = certify(tmp_path, task_file, task_sha256, 2)

    assert result["state"] == "passed"
    assert result["sandbox_provider"] == "sandoq"
    assert result["worker_manifest_sha256"] == "a" * 64


def test_direct_sandoq_certificate_rejects_missing_cleanup_gate(tmp_path: Path, monkeypatch) -> None:
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("opaque-a\nopaque-b\n")
    task_sha256 = hashlib.sha256(task_file.read_bytes()).hexdigest()
    (tmp_path / ".writer.lock").write_bytes(b"")
    identity = _identity(task_sha256, 2)
    identity["execution"]["cleanup_must_succeed"] = False
    monkeypatch.setattr(
        certificate_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "identity": identity,
            "eval_run_identity_sha256": "b" * 64,
        },
    )

    with pytest.raises(DirectSandoqCertificateError, match="sandoq_identity_required"):
        certify(tmp_path, task_file, task_sha256, 2)
