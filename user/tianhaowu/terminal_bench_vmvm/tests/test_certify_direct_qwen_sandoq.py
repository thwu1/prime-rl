import hashlib
import json
from pathlib import Path

import certify_direct_qwen_sandoq as certificate_module
import pytest
from certify_direct_qwen_sandoq import (
    DirectSandoqCertificateError,
    certify,
    validate_predecessor,
    validate_ramp_receipt,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(task_sha256: str, count: int, config: Path) -> dict:
    return {
        "role": "qwen-direct",
        "source": {
            "sandbox_provider": "sandoq",
            "prime_rl_commit": "1" * 40,
            "verifiers_commit": "2" * 40,
            "renderers_commit": "9" * 40,
            "sandoq_provider_commit": "3" * 40,
            "sandoq_provider_tree": "4" * 40,
            "sandoq_client_version": "pinned",
            "sandoq_site_sha256": "5" * 64,
            "derived_image_manifest_sha256": "6" * 64,
        },
        "config": {"source": {"path": str(config)}},
        "execution": {
            "cleanup_must_succeed": True,
            "runtime": {"type": "sandoq"},
            "rollout_concurrency": count,
            "multiplex": count,
            "http_max_connections": count,
            "http_max_keepalive_connections": count,
            "sandoq_environment": {"pool_size": count, "pool_min_size": 0},
        },
        "inputs": {"task_file": {"sha256": task_sha256, "count": count}},
        "deployment": {
            "worker_manifest": {"path": str(config), "sha256": "a" * 64},
            "spec_sha256": "7" * 64,
            "endpoint_bundle_sha256": "8" * 64,
        },
    }


def _evidence(tmp_path: Path) -> tuple[Path, str, Path, str, Path, Path, str, Path, str]:
    canonical = tmp_path / "canonical.txt"
    canonical.write_text("".join(f"opaque-{index}\n" for index in range(2500)))
    canonical_sha = _sha(canonical)
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("opaque-0\nopaque-1\n")
    task_sha256 = _sha(task_file)
    template = tmp_path / "template.toml"
    template.write_text(
        "num_tasks = 2500\nmax_concurrent = 64\nmultiplex = 64\n"
        "max_connections = 32\nmax_keepalive_connections = 32\n"
        'task_file = "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt"\n'
        'task_file_sha256 = "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"\n'
    )
    template_sha = _sha(template)
    config = tmp_path / "config.toml"
    config.write_bytes(
        certificate_module.materialize_config(
            template,
            template_sha,
            count=2,
            task_file=task_file.resolve(),
            task_file_sha256=task_sha256,
        )
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "selection": "ordered-prefix",
                "source_sha256": canonical_sha,
                "source_count": 2500,
                "selected_count": 2,
                "selected_sha256": task_sha256,
                "template_sha256": template_sha,
                "config_sha256": _sha(config),
            }
        )
        + "\n"
    )
    cleanup = tmp_path / "sandoq_cleanup_audit.json"
    cleanup.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "sandoq-pool-cleanup",
                "state": "passed",
                "recorded_outer_sessions": 2,
                "verified_http_404": 2,
                "already_absent": 2,
                "deleted_and_verified": 0,
                "assignments_acquired": 2,
                "assignment_release_rows": 2,
                "assignment_cancellation_rows": 0,
                "cleanup_gateway_retry_count": 0,
                "assignments_cleanup_verified": 2,
                "assignment_event_order_high_water": 2,
                "assignment_measured_high_water": 2,
                "outer_sessions_created": 2,
                "outer_sessions_deleted": 2,
                "outer_session_high_water": 2,
                "pool_drain_deleted": 2,
                "gateway_close_warnings": 0,
                "recovered_poisoned_assignments": 0,
                "failures": 0,
                "raw_audit_sha256": "1" * 64,
                "pool_event_log_sha256": "2" * 64,
                "pool_wal_sha256": "3" * 64,
                "pool_drain_sha256": "4" * 64,
            }
        )
        + "\n"
    )
    return task_file, task_sha256, receipt, _sha(receipt), cleanup, canonical, canonical_sha, template, template_sha


def test_direct_sandoq_certificate_binds_identity_and_aggregate_results(tmp_path: Path, monkeypatch) -> None:
    task_file, task_sha256, receipt, receipt_sha256, cleanup, canonical, canonical_sha, template, template_sha = (
        _evidence(tmp_path)
    )
    monkeypatch.setattr(certificate_module, "CANONICAL_TASK_SOURCE_SHA256", canonical_sha)
    monkeypatch.setattr(certificate_module, "CANONICAL_TEMPLATE_SHA256", template_sha)
    config = tmp_path / "config.toml"
    (tmp_path / ".writer.lock").write_bytes(b"")
    (tmp_path / "results.jsonl").write_text("{}\n{}\n")
    monkeypatch.setattr(
        certificate_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "identity": _identity(task_sha256, 2, config),
            "eval_run_identity_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        certificate_module,
        "_summarize_traces",
        lambda *_args, **_kwargs: ({"model_io_turns": 2}, []),
    )
    monkeypatch.setattr(certificate_module, "validate_saved_manifest", lambda _path: {"workers": [{}] * 24})

    result = certify(tmp_path, task_file, task_sha256, 2, cleanup, receipt, receipt_sha256, canonical, template)

    assert result["state"] == "passed"
    assert result["pool_cleanup"]["outer_session_high_water"] == 2
    assert result["ramp"]["source_sha256"] == canonical_sha


def test_direct_sandoq_certificate_rejects_missing_cleanup_gate(tmp_path: Path, monkeypatch) -> None:
    task_file, task_sha256, receipt, receipt_sha256, cleanup, canonical, canonical_sha, template, template_sha = (
        _evidence(tmp_path)
    )
    monkeypatch.setattr(certificate_module, "CANONICAL_TASK_SOURCE_SHA256", canonical_sha)
    monkeypatch.setattr(certificate_module, "CANONICAL_TEMPLATE_SHA256", template_sha)
    identity = _identity(task_sha256, 2, tmp_path / "config.toml")
    identity["execution"]["cleanup_must_succeed"] = False
    (tmp_path / ".writer.lock").write_bytes(b"")
    monkeypatch.setattr(
        certificate_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {"identity": identity, "eval_run_identity_sha256": "b" * 64},
    )

    with pytest.raises(DirectSandoqCertificateError, match="sandoq_identity_required"):
        certify(tmp_path, task_file, task_sha256, 2, cleanup, receipt, receipt_sha256, canonical, template)


def test_direct_sandoq_certificate_rejects_under_capacity(tmp_path: Path, monkeypatch) -> None:
    task_file, task_sha256, receipt, receipt_sha256, cleanup, canonical, canonical_sha, template, template_sha = (
        _evidence(tmp_path)
    )
    monkeypatch.setattr(certificate_module, "CANONICAL_TASK_SOURCE_SHA256", canonical_sha)
    monkeypatch.setattr(certificate_module, "CANONICAL_TEMPLATE_SHA256", template_sha)
    payload = json.loads(cleanup.read_text())
    payload["outer_session_high_water"] = 1
    cleanup.write_text(json.dumps(payload))
    (tmp_path / ".writer.lock").write_bytes(b"")
    (tmp_path / "results.jsonl").write_text("{}\n{}\n")
    monkeypatch.setattr(
        certificate_module,
        "load_eval_run_identity",
        lambda *_args, **_kwargs: {
            "identity": _identity(task_sha256, 2, tmp_path / "config.toml"),
            "eval_run_identity_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(certificate_module, "_summarize_traces", lambda *_a, **_k: ({"model_io_turns": 2}, []))
    monkeypatch.setattr(certificate_module, "validate_saved_manifest", lambda _path: {"workers": [{}] * 24})

    with pytest.raises(DirectSandoqCertificateError, match="pool_cleanup_proof_invalid"):
        certify(tmp_path, task_file, task_sha256, 2, cleanup, receipt, receipt_sha256, canonical, template)


def test_predecessor_binds_source_and_ordered_prefix(tmp_path: Path) -> None:
    current = tmp_path / "tasks.txt"
    current.write_text("".join(f"opaque-{index}\n" for index in range(8)))
    prefix_sha = hashlib.sha256(b"opaque-0\nopaque-1\n").hexdigest()
    source = {"provider": "pinned"}
    ramp = {"source_sha256": "a" * 64, "template_sha256": "b" * 64}
    prior = {
        "schema_version": 1,
        "kind": "direct-qwen-sandoq-ramp",
        "state": "passed",
        "stage_count": 2,
        "eval_run_identity_sha256": "1" * 64,
        "results_sha256": "2" * 64,
        "task_file_sha256": prefix_sha,
        "sandbox_provider": "sandoq",
        "cleanup_must_succeed": True,
        "worker_manifest_sha256": "3" * 64,
        "worker_count": 24,
        "pool_cleanup": {"failures": 0},
        "predecessor": None,
        "ramp": ramp,
        "source": source,
    }
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(prior, sort_keys=True))
    digest = _sha(path)

    result = validate_predecessor(
        8,
        path,
        digest,
        expected_source=source,
        expected_ramp=ramp,
        current_task_file=current,
    )
    assert result["task_file_sha256"] == prefix_sha

    with pytest.raises(DirectSandoqCertificateError, match="predecessor_invalid"):
        validate_predecessor(
            8,
            path,
            digest,
            expected_source={"provider": "different"},
            expected_ramp=ramp,
            current_task_file=current,
        )


def test_ramp_receipt_rejects_noncanonical_selected_bytes(tmp_path: Path, monkeypatch) -> None:
    task_file, task_sha256, receipt, receipt_sha256, _cleanup, canonical, canonical_sha, template, template_sha = (
        _evidence(tmp_path)
    )
    monkeypatch.setattr(certificate_module, "CANONICAL_TASK_SOURCE_SHA256", canonical_sha)
    monkeypatch.setattr(certificate_module, "CANONICAL_TEMPLATE_SHA256", template_sha)
    task_file.write_text("opaque-1\nopaque-0\n")
    forged_sha = _sha(task_file)
    payload = json.loads(receipt.read_text())
    payload["selected_sha256"] = forged_sha
    receipt.write_text(json.dumps(payload))

    with pytest.raises(DirectSandoqCertificateError, match="ramp_selection_not_canonical_prefix"):
        validate_ramp_receipt(
            2,
            forged_sha,
            task_file,
            canonical,
            template,
            tmp_path / "config.toml",
            receipt,
            _sha(receipt),
        )


def test_ramp_receipt_rejects_altered_canonical_template(tmp_path: Path, monkeypatch) -> None:
    task_file, task_sha256, receipt, _receipt_sha256, _cleanup, canonical, canonical_sha, template, template_sha = (
        _evidence(tmp_path)
    )
    monkeypatch.setattr(certificate_module, "CANONICAL_TASK_SOURCE_SHA256", canonical_sha)
    monkeypatch.setattr(certificate_module, "CANONICAL_TEMPLATE_SHA256", template_sha)
    template.write_text(template.read_text() + "# altered\n")

    with pytest.raises(DirectSandoqCertificateError, match="canonical_template_mismatch"):
        validate_ramp_receipt(
            2,
            task_sha256,
            task_file,
            canonical,
            template,
            tmp_path / "config.toml",
            receipt,
            _sha(receipt),
        )
