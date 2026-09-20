from __future__ import annotations

import ast
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import socket
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("registry_direct_pull_v32_controller", HERE / "controller.py")
assert SPEC is not None and SPEC.loader is not None
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

SUCCESS_CATEGORY = "success"


def held_record() -> dict[str, str]:
    job_id = "12345"
    token = "a" * 24
    return {
        "JobId": job_id,
        "JobName": controller.JOB_NAME,
        "UserId": controller.OWNER_RECORD,
        "Comment": f"{controller.COMMENT_PREFIX}{token}",
        "Command": "(null)",
        "WorkDir": str(controller.BUNDLE),
        "Account": controller.ACCOUNT,
        "QOS": controller.QOS,
        "Partition": controller.PARTITION,
        "TimeLimit": controller.WALLTIME,
        "StdOut": str(controller.LOG_ROOT / f"slurm-{job_id}.log"),
        "StdErr": str(controller.LOG_ROOT / f"slurm-{job_id}.log"),
        "Requeue": "0",
        "Restarts": "0",
        "NumNodes": "1",
        "NumCPUs": "4",
        "ReqTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "AllocTRES": "(null)",
        "JobState": "PENDING",
        "Priority": "0",
        "EligibleTime": "Unknown",
        "Reason": "JobHeldUser",
    }


def terminal_accounting_record(*, state: str = "FAILED", exit_code: str = "2:0") -> dict[str, str]:
    job_id = "12345"
    token = "a" * 24
    return {
        "JobIDRaw": job_id,
        "JobName": controller.JOB_NAME,
        "User": controller.OWNER,
        "Account": controller.ACCOUNT,
        "QOS": controller.QOS,
        "Partition": controller.PARTITION,
        "State": state,
        "ExitCode": exit_code,
        "Elapsed": "00:00:02",
        "ReqTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "AllocTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "NNodes": "1",
        "ReqCPUS": "4",
        "TimeLimit": controller.WALLTIME,
        "Comment": f"{controller.COMMENT_PREFIX}{token}",
    }


def mode400_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "compute_tools.sha256"
    manifest.write_bytes((HERE / "compute_tools.sha256").read_bytes())
    manifest.chmod(0o400)
    return manifest


def bind_private_probe_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> None:
    private = tmp_path / "private_manifest.tsv"
    private.write_bytes(raw)
    private.chmod(0o400)
    private_sha = hashlib.sha256(raw).hexdigest()
    result_payload = json.loads(controller.COMPUTE_PROBE_RESULT.read_bytes())
    result_payload["private_manifest_sha256"] = private_sha
    result_raw = controller.canonical(result_payload)
    result = tmp_path / "result.json"
    result.write_bytes(result_raw)
    result.chmod(0o400)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_PRIVATE", private)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_PRIVATE_SHA256", private_sha)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_PRIVATE_SIZE", len(raw))
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT", result)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT_SHA256", hashlib.sha256(result_raw).hexdigest())
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT_SIZE", len(result_raw))


def bind_result_probe_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    raw = controller.canonical(payload)
    result = tmp_path / "result.json"
    result.write_bytes(raw)
    result.chmod(0o400)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT", result)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(controller, "COMPUTE_PROBE_RESULT_SIZE", len(raw))


def bind_job_probe_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    raw = controller.canonical(payload)
    job_result = tmp_path / "job_result.json"
    job_result.write_bytes(raw)
    job_result.chmod(0o400)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_JOB_RESULT", job_result)
    monkeypatch.setattr(controller, "COMPUTE_PROBE_JOB_RESULT_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(controller, "COMPUTE_PROBE_JOB_RESULT_SIZE", len(raw))
    result_payload = json.loads(controller.COMPUTE_PROBE_RESULT.read_bytes())
    result_payload["public_log_sha256"] = hashlib.sha256(raw).hexdigest()
    bind_result_probe_variant(tmp_path, monkeypatch, result_payload)


def test_canonical_has_one_newline() -> None:
    assert controller.canonical({"b": 1, "a": 2}) == b'{"a":2,"b":1}\n'


def test_approval_is_diagnostic_only() -> None:
    contract = controller.approval_contract({"controller": "a" * 64}, {"same_inode": True})
    assert contract["state"] == "approved_once"
    assert contract["source_bound"] is True
    assert contract["diagnostic_only"] is True
    assert contract["production_authorized"] is False
    assert contract["protocol"]["task_free"] is True
    assert contract["protocol"]["model_free"] is True
    assert contract["protocol"]["one_sbatch"] is True
    assert contract["protocol"]["one_ucloud_mint"] is True
    assert contract["protocol"]["ucloud_outform_text"] is True
    assert contract["protocol"]["one_offline_podman_authfile_lookup"] is True
    assert contract["protocol"]["network_login_forbidden"] is True
    assert contract["protocol"]["one_guarded_digest_pinned_pull"] is True
    assert contract["protocol"]["registry_pull_retries"] == 0
    assert contract["protocol"]["pull_explicit_authfile"] is True
    assert contract["protocol"]["pull_explicit_platform"] == "linux/arm64"
    assert contract["protocol"]["pull_tls_verify"] is True
    assert contract["protocol"]["exact_digest_inspection"] is True
    assert contract["protocol"]["exact_repository_digest"] is True
    assert contract["protocol"]["image_removed_after_inspection"] is True
    assert contract["protocol"]["token_shape_coarse_only"] is True
    assert contract["protocol"]["guard_stage_markers"] == ["precondition", "child", "postcondition"]
    assert contract["protocol"]["sealed_memfd_batch_stdin"] is True
    assert contract["protocol"]["sbatch_stdin_without_script_operand"] is True
    assert contract["protocol"]["spooled_batch_self_hash"] is True
    assert contract["protocol"]["descriptor_open_stderr_restored"] is True
    assert contract["protocol"]["rootless_storage_path_equals_graphroot"] is True
    assert contract["protocol"]["rootless_runroot"] == "XDG_RUNTIME_DIR/containers"
    assert contract["protocol"]["cleanup_roots_pairwise_disjoint"] is True
    assert contract["protocol"]["podman_info_categories"] == [
        "podman_info_command",
        "podman_info_shape",
        "podman_store_graphroot",
        "podman_store_runroot",
        "podman_store_driver",
        "podman_info_image_present",
        "podman_info_image_check",
    ]
    assert contract["protocol"]["positive_probe_cleanup_proof"] == "gate_cleanup=retained_empty"
    assert contract["protocol"]["cleanup_failure_precedes_operational_category"] is True
    assert contract["protocol"]["source_failure_phase_split"] is True
    assert contract["protocol"]["compute_manifest_mismatch_encoding"] == "count-plus-33-bit-index-bitmap"
    assert contract["protocol"]["compute_manifest_observed_hashes_public"] is False
    assert contract["protocol"]["compute_manifest_fresh_probe_bound"] is True
    assert contract["protocol"]["compute_manifest_symlinks_rejected"] is True
    assert contract["protocol"]["terminal_accounting_stable_reads"] == 2
    assert contract["protocol"]["rapid_terminal_handoff"] is True
    assert contract["protocol"]["terminal_observation_suppresses_cancel"] is True
    assert contract["protocol"]["terminal_queue_absence_before_result"] is True
    assert contract["protocol"]["fd_bound_runtime_sources"] is True
    assert contract["protocol"]["dirfd_anchored_cleanup"] is True
    assert contract["protocol"]["retained_scrubbed_roots"] is True
    assert contract["protocol"]["retained_raw_stream_fds"] is True
    assert contract["protocol"]["podman_directory_inode_binding"] is True
    assert contract["protocol"]["per_attempt_podman_directory_binding"] is True
    assert contract["protocol"]["unsafe_entry_preflight"] is True
    assert contract["protocol"]["mountpoint_rejection"] is True
    assert contract["protocol"]["global_cleanup_preflight"] is True
    assert contract["protocol"]["cleanup_single_writer_required"] is True
    assert contract["protocol"]["podman_writer_quiescence_handshake"] is True
    assert contract["protocol"]["signal_deferred_cleanup"] is True
    assert contract["protocol"]["signal_deadline_armed_on_receipt"] is True
    assert contract["protocol"]["live_writer_cleanup_unproven_terminal"] is True
    assert contract["protocol"]["live_writer_scheduler_absence_before_final_result"] is True
    assert contract["protocol"]["cleanup_retry_budget"] == 3
    assert contract["protocol"]["fd_relative_no_follow_scrub"] is True
    assert contract["protocol"]["sensitive_files_nlink_zero_after_writer_quiescence"] is True
    assert contract["protocol"]["retained_empty_directories"] is True
    assert contract["protocol"]["private_scrub_forbidden_without_writer_quiescence"] is True
    assert contract["protocol"]["live_writer_private_cleanup_claim"] is False
    assert contract["protocol"]["podman_guard_signal_bound_seconds"] == 3
    assert contract["protocol"]["bounded_signal_cleanup_seconds"] == 210
    assert contract["protocol"]["malformed_submit_output_reconciled"] is True
    assert contract["protocol"]["discovered_id_bound_before_identity_wait"] is True
    assert contract["protocol"]["unknown_id_cleanup_reconciled"] is True
    assert contract["protocol"]["single_non_reentrant_publication"] is True
    assert contract["protocol"]["signal_deferred_publication"] is True
    assert contract["protocol"]["maximum_public_json_lines"] == 1
    assert contract["protocol"]["maximum_durable_results"] == 1
    assert contract["scheduler"]["time"] == "00:30:00"
    assert contract["scheduler"]["nodelist"] == controller.PINNED_NODE


def test_source_is_explicitly_bound_and_image_remains_bound() -> None:
    contract = controller.approval_contract({}, {})
    assert controller.SOURCE_BOUND is True
    assert contract["state"] == "approved_once"
    assert contract["source_bound"] is True
    assert contract["source_root"] == "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-468a6e5"
    assert contract["source_revision"] == "468a6e5b83ba51a8fe0389f1105f34dd18fa03f3"
    assert contract["source_tree"] == "bd6d81b7748c5055876100b9dc115eed8a764fe0"
    assert contract["source_bundle_sha256"] == "7aaeec5142d7d3e0fdaabebc441094e79300adb36aee370f8a397a3f356968a3"
    assert controller.SOURCE_BUNDLE_SIZE == 5_436_664
    assert contract["image"].endswith("@" + controller.IMAGE_DIGEST)
    assert set(contract["source_files"]) == {
        "vllm_tools/serve_api_v2/config/models/kimi-k3/card.toml",
        "vllm_tools/serve_api_v2/src/serve_api_v2/worker/aws_creds.sh",
        "vllm_tools/serve_api_v2/src/serve_api_v2/worker/worker_vllm.sh",
        "vllm_tools/serve_api_v2/tests/script_tests/smoke_container_args.sh",
    }
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in contract["source_files"].values())
    provenance = contract["compute_tool_provenance"]
    assert provenance["node"] == controller.PINNED_NODE
    assert provenance["fresh_entries"] == 33
    assert provenance["all_33_fresh_and_exact"] is True
    assert provenance["fresh_source"] == "fresh_compute_node"
    assert provenance["probe_kind"] == "k3-compute-tool-manifest-diag-v5"
    assert provenance["projection_sha256"] == controller.COMPUTE_PROJECTION_SHA256
    assert provenance["python_preferred_index"] == 3
    assert provenance["python_version"] == "3.12"
    assert provenance["python_identity"] == "regular_file:755:0:1"
    assert provenance["private_manifest_path"] == str(controller.COMPUTE_PROBE_PRIVATE)
    assert provenance["private_manifest_sha256"] == controller.COMPUTE_PROBE_PRIVATE_SHA256
    assert provenance["private_manifest_size"] == controller.COMPUTE_PROBE_PRIVATE_SIZE
    assert provenance["result_path"] == str(controller.COMPUTE_PROBE_RESULT)
    assert provenance["result_sha256"] == controller.COMPUTE_PROBE_RESULT_SHA256
    assert provenance["result_size"] == controller.COMPUTE_PROBE_RESULT_SIZE
    assert provenance["job_result_path"] == str(controller.COMPUTE_PROBE_JOB_RESULT)
    assert provenance["job_result_sha256"] == controller.COMPUTE_PROBE_JOB_RESULT_SHA256
    assert provenance["job_result_size"] == controller.COMPUTE_PROBE_JOB_RESULT_SIZE
    assert provenance["probe_approval_sha256"] == controller.COMPUTE_PROBE_APPROVAL_SHA256


def test_source_validation_fails_at_unbound_barrier_before_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", False)
    monkeypatch.setattr(controller, "stable_file", lambda *_args, **_kwargs: pytest.fail("filesystem reached"))
    monkeypatch.setattr(controller, "git_output", lambda *_args: pytest.fail("git reached"))
    monkeypatch.setattr(
        controller,
        "validate_compute_probe",
        lambda *_args: pytest.fail("compute evidence reached"),
    )
    with pytest.raises(controller.GateError, match="^source_unbound$"):
        controller.validate_source(Path("/nonexistent/tools-manifest"))


def test_audit_fails_source_unbound_before_tools_scheduler_or_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", False)
    monkeypatch.setattr(controller, "validate_tools", lambda: pytest.fail("tool validation reached"))
    monkeypatch.setattr(controller, "qos_contract", lambda: pytest.fail("scheduler reached"))
    monkeypatch.setattr(controller, "prove_fresh", lambda: pytest.fail("namespace reached"))
    with pytest.raises(controller.GateError, match="^source_unbound$"):
        controller.audit({})


def test_execute_fails_source_unbound_before_scheduler_tls_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", False)
    monkeypatch.setattr(
        controller,
        "validate_compute_probe",
        lambda *_args: pytest.fail("compute evidence reached"),
    )
    monkeypatch.setattr(controller, "validate_tmux", lambda: pytest.fail("tmux reached"))
    monkeypatch.setattr(controller, "tls_binding", lambda: pytest.fail("TLS reached"))
    monkeypatch.setattr(controller, "validate_approval", lambda *_args: pytest.fail("approval reached"))
    monkeypatch.setattr(controller, "submit_once", lambda *_args: pytest.fail("scheduler reached"))
    with pytest.raises(controller.GateError, match="^source_unbound$"):
        controller.execute({})


def test_approval_validation_fails_source_unbound_before_approval_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", False)
    monkeypatch.setattr(controller, "stable_file", lambda *_args, **_kwargs: pytest.fail("approval read"))
    with pytest.raises(controller.GateError, match="^source_unbound$"):
        controller.validate_approval({}, {})


def test_rendered_source_has_approval_state() -> None:
    assert controller.approval_contract({}, {})["state"] == "approved_once"
    pending = controller.pending_contract({})
    assert pending["state"] == "pending_independent_approval"
    assert pending["source_bound"] is True


def test_probe_contains_exact_bound_source() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert "ram-common-b1f0aa6" not in probe
    assert "adef5c3" not in probe
    assert "expected_source_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-468a6e5" in probe
    assert '"${GATE_SOURCE_REVISION:-}" == 468a6e5b83ba51a8fe0389f1105f34dd18fa03f3' in probe
    assert '"${GATE_SOURCE_TREE:-}" == bd6d81b7748c5055876100b9dc115eed8a764fe0' in probe


@pytest.mark.parametrize("mode", ["audit", "execute"])
def test_main_fails_source_unbound_before_bundle_read(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", False)
    monkeypatch.setattr(sys, "argv", ["controller.py", mode])
    monkeypatch.setattr(controller, "bundle_hashes", lambda: pytest.fail("bundle read"))
    assert controller.main() == 2
    assert json.loads(capsys.readouterr().err) == {"category": "source_unbound", "state": "blocked"}


def test_completed_fresh_compute_probe_is_exactly_bound(tmp_path: Path) -> None:
    controller.validate_compute_probe(mode400_manifest(tmp_path))


def test_compute_probe_selected_identity_drift_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = controller.COMPUTE_PROBE_PRIVATE.read_bytes()
    changed = raw.replace(b"python\t3\t1\tregular\t", b"python\t3\t0\tregular\t", 1)
    assert changed != raw and len(changed) == len(raw)
    bind_private_probe_variant(tmp_path, monkeypatch, changed)
    with pytest.raises(controller.GateError, match="compute_probe_python_identity"):
        controller.validate_compute_probe(mode400_manifest(tmp_path))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"fresh_compute_node", b"reviewed_node_hash"),
        (b"regular_file:755:0:1", b"symbolic_link:777:0:1"),
    ],
)
def test_compute_probe_rejects_nonfresh_or_nonregular_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old: bytes, new: bytes
) -> None:
    raw = controller.COMPUTE_PROBE_PRIVATE.read_bytes()
    changed = raw.replace(old, new, 1)
    assert changed != raw
    bind_private_probe_variant(tmp_path, monkeypatch, changed)
    with pytest.raises(controller.GateError, match="compute_probe_record"):
        controller.validate_compute_probe(mode400_manifest(tmp_path))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("private_manifest_sha256", "0" * 64),
        ("public_log_sha256", "0" * 64),
        ("approval_sha256", "0" * 64),
        ("kind", "wrong-kind"),
        ("state", "failed"),
    ],
)
def test_compute_probe_rejects_controller_result_semantic_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    payload = json.loads(controller.COMPUTE_PROBE_RESULT.read_bytes())
    payload[field] = value
    bind_result_probe_variant(tmp_path, monkeypatch, payload)
    with pytest.raises(controller.GateError, match="compute_probe_result_contract"):
        controller.validate_compute_probe(mode400_manifest(tmp_path))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("checked_count", 32),
        ("mismatch_bitmap", "0" * 33),
        ("kind", "wrong-kind"),
        ("extra", "forbidden"),
    ],
)
def test_compute_probe_rejects_job_result_semantic_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    payload = json.loads(controller.COMPUTE_PROBE_JOB_RESULT.read_bytes())
    payload[field] = value
    bind_job_probe_variant(tmp_path, monkeypatch, payload)
    with pytest.raises(controller.GateError, match="compute_probe_result_contract"):
        controller.validate_compute_probe(mode400_manifest(tmp_path))


def test_execute_rejects_compute_probe_before_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", True)
    monkeypatch.setattr(
        controller,
        "validate_compute_probe",
        lambda _manifest: controller.fail("compute_probe_injected"),
    )
    monkeypatch.setattr(controller, "validate_tmux", lambda: pytest.fail("tmux must not be reached"))
    monkeypatch.setattr(controller, "tls_binding", lambda: pytest.fail("TLS must not be reached"))
    with pytest.raises(controller.GateError, match="compute_probe_injected"):
        controller.execute({})


def test_execute_rejects_compute_probe_identity_drift_before_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller, "SOURCE_BOUND", True)
    bindings = iter(((1,) * 9 for _ in range(4)))
    first = tuple(next(bindings) for _ in range(4))
    second = tuple((2,) * 9 for _ in range(4))
    probe_bindings = iter((first, second))
    tls = ({}, {"sha256": "a" * 64, "size": controller.TLS_SIZE})
    monkeypatch.setattr(controller, "RUN_ROOT", tmp_path / "run")
    monkeypatch.setattr(controller, "LOG_ROOT", tmp_path / "logs")
    monkeypatch.setattr(controller, "validate_compute_probe", lambda _manifest: next(probe_bindings))
    monkeypatch.setattr(controller, "validate_tmux", lambda: None)
    monkeypatch.setattr(controller, "tls_binding", lambda: tls)
    monkeypatch.setattr(controller, "validate_approval", lambda _hashes, _tls: ("b" * 64, {"ok": True}))
    monkeypatch.setattr(controller, "prove_fresh", lambda: None)
    monkeypatch.setattr(controller, "name_ids", lambda: set())
    monkeypatch.setattr(controller, "acquire_lock", lambda: controller.LockState(-1, -1, (0, 0), (0, 0, 0, 0)))
    monkeypatch.setattr(controller, "write_environment", lambda _path, _values: "c" * 64)
    monkeypatch.setattr(controller, "submit_once", lambda *_args: pytest.fail("submission must not be reached"))
    monkeypatch.setattr(controller, "cancel_exact", lambda *_args: None)
    hashes = {key: "d" * 64 for key in controller.BUNDLE_FILES}
    with pytest.raises(controller.GateError, match="approval_revalidation"):
        controller.execute(hashes)


def test_parse_tres_accepts_only_exact_map() -> None:
    raw = "node=1,mem=16G,gres/gpu=1,cpu=4,billing=4"
    assert controller.parse_tres(raw, allow_null=False) == controller.EXPECTED_REQ_TRES


@pytest.mark.parametrize(
    "raw",
    [
        "billing=4,cpu=4,mem=16G,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1,foo=1",
        "billing=4,cpu=8,gres/gpu=1,mem=16G,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1,node=1",
        "billing=4,cpu=4,gres/gpu=1,mem=16G,node =1",
    ],
)
def test_parse_tres_rejects_drift(raw: str) -> None:
    with pytest.raises(controller.GateError, match="request_tres"):
        controller.parse_tres(raw, allow_null=False)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown"])
def test_parse_tres_null_is_only_explicitly_transient(raw: str | None) -> None:
    assert controller.parse_tres(raw, allow_null=True) is None
    with pytest.raises(controller.GateError, match="request_tres"):
        controller.parse_tres(raw, allow_null=False)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown", "0", "0-1"])
def test_held_node_only_incomplete_is_transient(raw: str | None) -> None:
    record = held_record()
    record["NumNodes"] = raw  # type: ignore[assignment]
    with pytest.raises(controller.IdentityTransient, match="held_nodes"):
        controller.held_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize("raw", [None, "", "None", "(null)", "Unknown", "0", "0-4", "8"])
def test_cpu_projection_never_retries(raw: str | None) -> None:
    record = held_record()
    record["NumCPUs"] = raw  # type: ignore[assignment]
    with pytest.raises(controller.GateError, match="identity_cpus"):
        controller.held_identity(record, "12345", "a" * 24)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("JobState", "RUNNING", "held_envelope"),
        ("Priority", "1", "held_envelope"),
        ("EligibleTime", "2026-09-20T00:00:00", "held_envelope"),
        ("Reason", "Resources", "held_reason"),
        ("AllocTRES", "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1", "held_alloc_tres"),
    ],
)
def test_held_envelope_drift_fails_immediately(field: str, value: str, code: str) -> None:
    record = held_record()
    record[field] = value
    with pytest.raises(controller.GateError, match=code):
        controller.held_identity(record, "12345", "a" * 24)


def test_released_pending_requires_positive_projections() -> None:
    record = held_record()
    record.update(Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="Resources")
    assert controller.released_identity(record, "12345", "a" * 24)


def test_released_node_count_is_strict() -> None:
    record = held_record()
    record.update(Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="Resources", NumNodes="0-1")
    with pytest.raises(controller.GateError, match="released_resources"):
        controller.released_identity(record, "12345", "a" * 24)


def test_released_running_requires_exact_alloc_tres() -> None:
    record = held_record()
    record.update(JobState="RUNNING", Priority="12", EligibleTime="2026-09-20T06:00:00", Reason="None")
    with pytest.raises(controller.IdentityTransient, match="released_alloc_tres"):
        controller.released_identity(record, "12345", "a" * 24)
    record["AllocTRES"] = record["ReqTRES"]
    assert controller.released_identity(record, "12345", "a" * 24)


def test_release_hands_rapid_terminal_to_accounting_without_second_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = "12345"
    token = "a" * 24
    reads: list[bool] = []
    releases: list[tuple[str, ...]] = []

    def fake_stable_reads(_job_id: str, _token: str, *, held: bool, rounds: int = 32) -> dict[str, str]:
        del rounds
        reads.append(held)
        if held:
            return held_record()
        raise controller.TerminalBeforeActive("terminal_before_active")

    monkeypatch.setattr(controller, "stable_reads", fake_stable_reads)
    monkeypatch.setattr(
        controller,
        "run",
        lambda argv, **_kwargs: releases.append(tuple(argv)) or subprocess.CompletedProcess(argv, 0, b"", b""),
    )
    controller.release_once(job_id, token)
    assert reads == [True, False]
    assert len(releases) == 1
    assert releases[0][3:] == ("release", job_id)


def test_released_identity_uses_typed_terminal_handoff() -> None:
    record = held_record()
    record.update(JobState="FAILED", AllocTRES=record["ReqTRES"])
    with pytest.raises(controller.TerminalBeforeActive, match="terminal_before_active"):
        controller.released_identity(record, "12345", "a" * 24)


def test_released_scontrol_terminal_handoff_sets_no_cancel_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    record = held_record()
    record.update(JobState="FAILED", AllocTRES=record["ReqTRES"])
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(controller, "show_job", lambda _job_id: record)
    with pytest.raises(controller.TerminalBeforeActive, match="terminal_before_active"):
        controller.stable_reads("12345", "a" * 24, held=False)
    assert controller.TERMINAL_ACCOUNTING_OBSERVED is True


def test_released_sampling_hands_disappeared_scontrol_to_terminal_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = terminal_accounting_record()
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(
        controller,
        "show_job",
        lambda _job_id: (_ for _ in ()).throw(controller.SchedulerUnavailable("show_job_failed")),
    )
    monkeypatch.setattr(controller, "accounting", lambda _job_id: terminal)
    with pytest.raises(controller.TerminalBeforeActive, match="terminal_before_active"):
        controller.stable_reads("12345", "a" * 24, held=False)
    assert controller.TERMINAL_ACCOUNTING_OBSERVED is True


def test_released_terminal_handoff_still_requires_exact_static_resources() -> None:
    record = held_record()
    record.update(JobState="FAILED", NumCPUs="0")
    with pytest.raises(controller.GateError, match="identity_cpus"):
        controller.released_identity(record, "12345", "a" * 24)
    record = held_record()
    record.update(JobState="FAILED", NumNodes="0-1")
    with pytest.raises(controller.GateError, match="released_resources"):
        controller.released_identity(record, "12345", "a" * 24)


def test_stable_projection_omits_volatile_scheduler_fields() -> None:
    first = held_record()
    second = dict(first)
    first.update(RunTime="00:00:01", LastSchedEval="2026-09-20T07:00:01")
    second.update(RunTime="00:00:02", LastSchedEval="2026-09-20T07:00:02")
    assert controller.identity_projection(first) == controller.identity_projection(second)


def test_sbatch_command_is_exact_and_held() -> None:
    command = controller.sbatch_command(Path("/private/environment.bin"), "b" * 24)
    assert command.count("/usr/bin/sbatch") == 1
    assert command.count("--hold") == 1
    assert command.count("--nodes=1") == 1
    assert command.count("--ntasks=1") == 1
    assert command.count("--gpus-per-node=1") == 1
    assert command.count("--cpus-per-task=4") == 1
    assert command.count("--mem=16G") == 1
    assert command.count("--time=00:30:00") == 1
    assert command.count("--no-requeue") == 1
    assert command.count("--signal=B:TERM@240") == 1
    assert command.count(f"--nodelist={controller.PINNED_NODE}") == 1
    assert [part for part in command if part.startswith("--export")] == ["--export-file=/private/environment.bin"]
    assert str(controller.BUNDLE / "run_registry_gate.sbatch") not in command
    assert command[-1] == "--export-file=/private/environment.bin"
    assert "-" not in command
    assert [part for part in command if not part.startswith("-")] == ["/usr/bin/sbatch", controller.CLUSTER]


def test_environment_is_sorted_nul_and_private(tmp_path: Path) -> None:
    path = tmp_path / "environment.bin"
    observed = controller.write_environment(path, {"B": "2", "A": "1"})
    assert path.read_bytes() == b"A=1\0B=2\0"
    assert observed == controller.digest(path.read_bytes())
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    with pytest.raises(FileExistsError):
        controller.write_environment(path, {"A": "1"})


def test_environment_rejects_nul_or_equals(tmp_path: Path) -> None:
    with pytest.raises(controller.GateError, match="environment_invalid"):
        controller.write_environment(tmp_path / "one", {"A=B": "x"})
    with pytest.raises(controller.GateError, match="environment_invalid"):
        controller.write_environment(tmp_path / "two", {"A": "x\0y"})


def test_publish_is_no_replace_and_leaves_one_link(tmp_path: Path) -> None:
    target = tmp_path / "output"
    target.mkdir(mode=0o700)
    expected = {"kind": "test", "state": "complete"}
    sha = controller.publish_exclusive(target, "result.json", expected)
    result = target / "result.json"
    assert result.read_bytes() == controller.canonical(expected)
    assert sha == controller.digest(result.read_bytes())
    assert result.stat().st_nlink == 1
    assert not list(target.glob(".*.tmp"))
    with pytest.raises(FileExistsError):
        controller.publish_exclusive(target, "result.json", expected)


def test_publish_cleans_owned_temp_when_link_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "output"
    target.mkdir(mode=0o700)

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected")

    monkeypatch.setattr(controller.os, "link", fail_link)
    with pytest.raises(OSError, match="injected"):
        controller.publish_exclusive(target, "result.json", {"state": "blocked"})
    assert list(target.iterdir()) == []


def test_terminal_lock_is_retained_and_single_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = tmp_path / "gate.lock"
    monkeypatch.setattr(controller, "LOCK", lock_path)
    lock = controller.acquire_lock()
    controller.finalize_lock(lock, "success")
    assert json.loads(lock_path.read_bytes())["state"] == "terminal"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        controller.acquire_lock()


def test_cleanup_envelope_accepts_only_known_propagation_gaps() -> None:
    record = held_record()
    for field in ("Command", "WorkDir", "Account", "QOS", "Partition", "TimeLimit", "ReqTRES", "NumCPUs"):
        record[field] = "(null)"
    record["NumNodes"] = "0-1"
    assert controller.cancellation_envelope(record, "12345", "a" * 24)


def test_cleanup_envelope_rejects_owner_or_resource_drift() -> None:
    record = held_record()
    record["UserId"] = "other(1)"
    with pytest.raises(controller.GateError, match="cleanup_identity_conflict"):
        controller.cancellation_envelope(record, "12345", "a" * 24)
    record = held_record()
    record["NumCPUs"] = "8"
    with pytest.raises(controller.GateError, match="cleanup_identity_conflict"):
        controller.cancellation_envelope(record, "12345", "a" * 24)


def test_submit_retries_transient_name_query_without_resubmit(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    calls = {"submit": 0, "query": 0, "stable": 0}
    batch_raw = b"#!/usr/bin/bash\nexit 0\n"
    submitted: dict[str, object] = {}

    def fake_submit(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls["submit"] += 1
        command = _args[0]
        assert command[-1] == "--export-file=/private/environment"
        assert "-" not in command
        stdin = kwargs["stdin"]
        assert isinstance(stdin, int)
        submitted["raw"] = os.read(stdin, len(batch_raw) + 1)
        submitted["seals"] = fcntl.fcntl(stdin, fcntl.F_GET_SEALS)
        return subprocess.CompletedProcess([], 0, f"{job_id}\n".encode(), b"")

    def fake_query() -> set[str]:
        calls["query"] += 1
        if calls["query"] == 1:
            raise controller.SchedulerUnavailable("squeue_failed")
        return {job_id} if calls["query"] == 2 else set()

    def fake_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["stable"] += 1
        return held_record()

    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller.subprocess, "run", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "stable_reads", fake_stable)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.submit_once(Path("/private/environment"), "a" * 24, batch_raw) == job_id
    assert calls == {"submit": 1, "query": 3, "stable": 1}
    assert submitted["raw"] == batch_raw
    assert submitted["seals"] == (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
    assert job_id in controller.OWNED_JOB_IDS


def test_direct_id_is_retained_before_submission_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, f"{job_id}\n".encode(), b""),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {job_id, "12346"})
    with pytest.raises(controller.GateError, match="submission_conflict"):
        controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\nexit 0\n")
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS


@pytest.mark.parametrize(
    "error",
    [controller.GateInterrupted(), controller.SchedulerUnavailable("show_job_unavailable")],
)
def test_discovered_id_is_bound_before_identity_failure(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    job_id = "12345"
    batch_raw = b"#!/usr/bin/bash\nexit 0\n"
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"not-a-job-id\n", b""),
    )
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {job_id})

    def fail_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        assert controller.SUBMITTED_JOB_ID == job_id
        assert job_id in controller.OWNED_JOB_IDS
        raise error

    monkeypatch.setattr(controller, "stable_reads", fail_stable)
    with pytest.raises(type(error)):
        controller.submit_once(Path("/private/environment"), "a" * 24, batch_raw)
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS


def test_malformed_sbatch_stdout_enters_bounded_name_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    calls = {"submit": 0, "query": 0, "stable": 0}

    def fake_submit(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls["submit"] += 1
        return subprocess.CompletedProcess([], 0, b"\xff\xfe\n", b"")

    def fake_query() -> set[str]:
        calls["query"] += 1
        if calls["query"] == 1:
            raise controller.SchedulerUnavailable("squeue_unavailable")
        return {job_id} if calls["query"] == 2 else set()

    def fake_stable(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["stable"] += 1
        assert controller.SUBMITTED_JOB_ID == job_id
        assert job_id in controller.OWNED_JOB_IDS
        return held_record()

    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller.subprocess, "run", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "stable_reads", fake_stable)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    assert controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\n") == job_id
    assert calls == {"submit": 1, "query": 3, "stable": 1}


def test_nonzero_sbatch_is_sanitized_after_bounded_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"submit": 0, "query": 0}
    clock = [0.0]

    def fake_submit(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls["submit"] += 1
        command = _args[0]
        assert command[-1] == "--export-file=/private/environment"
        assert "-" not in command
        assert isinstance(kwargs["stdin"], int)
        return subprocess.CompletedProcess([], 1, b"", b"private diagnostic")

    def fake_query() -> set[str]:
        calls["query"] += 1
        return set()

    monkeypatch.setattr(controller, "SUBMISSION_ATTEMPTED", False)
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())
    monkeypatch.setattr(controller.subprocess, "run", fake_submit)
    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(controller.GateError, match="submission_cli_failed"):
        controller.submit_once(Path("/private/environment"), "a" * 24, b"#!/usr/bin/bash\n")
    assert calls["submit"] == 1
    assert calls["query"] >= 2
    assert controller.SUBMISSION_ATTEMPTED is True
    assert controller.SUBMITTED_JOB_ID is None
    assert controller.OWNED_JOB_IDS == set()


def test_cancel_exact_accepts_partial_propagation_then_proves_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    partial = held_record()
    partial.update(Command="(null)", WorkDir="(null)", ReqTRES="(null)", NumNodes="0-1")
    queue_reads = iter(({job_id}, set(), set()))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", {job_id})
    monkeypatch.setattr(controller, "show_job", lambda _job_id: partial)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: next(queue_reads))
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(controller, "run", fake_run)
    controller.cancel_exact(job_id, token)
    assert commands == [("/usr/bin/scancel", "-M", controller.CLUSTER, job_id)]


def test_cancel_never_targets_unproven_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    partial = held_record()
    partial["Comment"] = "(null)"
    clock = [0.0]
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", {job_id})
    monkeypatch.setattr(controller, "show_job", lambda _job_id: partial)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: set())
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not cancel unproven identity")),
    )
    controller.cancel_exact(job_id, token)


def test_cancel_exact_refuses_after_terminal_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", True)
    monkeypatch.setattr(
        controller,
        "run",
        lambda argv, **_kwargs: scheduler_calls.append(tuple(argv)),
    )
    with pytest.raises(controller.GateError, match="cancel_after_terminal"):
        controller.cancel_exact("12345", "a" * 24)
    assert scheduler_calls == []


def test_cleanup_reconciles_unknown_id_after_submit_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    queue_reads: list[set[str] | BaseException] = [
        controller.SchedulerUnavailable("squeue_unavailable"),
        {job_id},
        set(),
        set(),
    ]
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(controller, "SUBMISSION_ATTEMPTED", True)
    monkeypatch.setattr(controller, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(controller, "OWNED_JOB_IDS", set())

    def fake_query() -> set[str]:
        observed = queue_reads.pop(0)
        if isinstance(observed, BaseException):
            raise observed
        return observed

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(controller, "queue_name_ids", fake_query)
    monkeypatch.setattr(controller, "show_job", lambda _job_id: held_record())
    monkeypatch.setattr(controller, "run", fake_run)
    monkeypatch.setattr(controller.time, "sleep", lambda _seconds: None)
    controller.cancel_exact(None, token)
    assert controller.SUBMITTED_JOB_ID == job_id
    assert job_id in controller.OWNED_JOB_IDS
    assert commands == [("/usr/bin/scancel", "-M", controller.CLUSTER, job_id)]


def test_cleanup_without_submit_attempt_does_not_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "SUBMISSION_ATTEMPTED", False)
    monkeypatch.setattr(
        controller,
        "queue_name_ids",
        lambda: (_ for _ in ()).throw(AssertionError("must not query without a submit attempt")),
    )
    controller.cancel_exact(None, "a" * 24)


def test_tmux_ancestry_parser_handles_parenthesized_command(tmp_path: Path) -> None:
    for pid, parent in ((300, 200), (200, 100), (100, 1)):
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(f"{pid} (name with ) paren) S {parent} 0 0 0\n")
    assert controller.pid_ancestry_contains(300, 100, tmp_path)
    assert not controller.pid_ancestry_contains(300, 99, tmp_path)


def test_tmux_validation_accepts_python_foreground_via_ancestry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%0")
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"swebench_vmvm:Launcher.0|42\n", b""),
    )
    monkeypatch.setattr(controller, "pid_ancestry_contains", lambda start, target: start > 1 and target == 42)
    controller.validate_tmux()


def test_tmux_validation_rejects_unrelated_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%0")
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"swebench_vmvm:Launcher.0|42\n", b""),
    )
    monkeypatch.setattr(controller, "pid_ancestry_contains", lambda _start, _target: False)
    with pytest.raises(controller.GateError, match="tmux_identity"):
        controller.validate_tmux()


def test_error_code_is_sanitized() -> None:
    assert controller.error_code(controller.GateError("safe_code")) == "safe_code"
    assert controller.error_code(controller.GateError("raw / path")) == "internal_error"
    assert controller.error_code(ValueError("secret")) == "internal_error"


def test_probe_is_one_shot_direct_pull_and_never_invokes_network_login_or_tasks() -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    assert text.count("_container_registry_arm_cleanup") == 1
    assert text.count("_container_registry_disarm_cleanup") == 1
    assert '_container_registry_login "$GATE_IMAGE"' not in text
    assert '_container_registry_pull "$GATE_IMAGE"' not in text
    assert text.count("/usr/bin/ucloud ecr get-credentials") == 1
    assert text.count("--outform text") == 1
    assert text.count('podman login --authfile "$auth_path" --get-login "$host"') == 1
    assert "--password-stdin" not in text
    assert "--username AWS" not in text
    assert text.count('podman pull --authfile "$auth_path" --platform linux/arm64') == 1
    assert text.count('--tls-verify=true --quiet "$image"') == 1
    for secret in ("$token", "$value"):
        assert f"/usr/bin/printf '%s' \"{secret}\"" not in text
    assert "builtin printf -- '%s' \"$token\"" not in text
    assert text.count("builtin printf -- 'AWS:%s' \"$token\"") == 1
    assert text.count("builtin printf -- '%s' \"$value\"") == 1
    assert text.count("/usr/bin/podman image inspect") == 1
    assert text.count("/usr/bin/podman image rm --force") == 1
    assert text.count('/usr/bin/podman image exists "$GATE_IMAGE"') == 1
    assert "container_run " not in text
    assert "/usr/bin/podman run" not in text
    assert "nvidia-container" not in text
    assert "vllm serve" not in text
    diagnostic = text[text.index("    diagnostic_pull_once()") : text.index("    _container_registry_arm_cleanup")]
    assert "_container_registry_backoff" not in diagnostic
    assert "/usr/bin/sleep" not in diagnostic
    assert "while " not in diagnostic


def test_pull_guard_binds_full_argv_auth_identity_and_content() -> None:
    guard = (HERE / "podman_guard.sh").read_text()
    assert '[[ $# == 5 && "$1" == login' in guard
    assert 'elif [[ $# == 8 && "$1" == pull' in guard
    for fragment in (
        '"$2" == --authfile',
        '"$4" == --platform',
        '"$5" == linux/arm64',
        '"$6" == --tls-verify=true',
        '"$7" == --quiet',
        '"$8" == "${GATE_EXPECTED_IMAGE:-}"',
        '"$8" == "${GATE_IMAGE:-}"',
        "GATE_EXPECTED_AUTH_IDENTITY",
        "GATE_EXPECTED_AUTH_SHA256",
        "GATE_WRITER_STATE_FD",
        "GATE_WRITER_STATE_IDENTITY",
    ):
        assert fragment in guard
    assert "--password-stdin" not in guard
    assert '"$1" == push' not in guard
    assert '"$1" == run' not in guard


def test_pull_lifecycle_unsets_secret_before_pull_and_removes_before_failure() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    offline_at = probe.index("DIAG_OFFLINE=ok")
    unset_at = probe.index("unset token encoded lookup_user", offline_at)
    pull_at = probe.index('podman pull --authfile "$auth_path"')
    inspect_at = probe.index("/usr/bin/podman image inspect")
    remove_at = probe.index("/usr/bin/podman image rm --force")
    failure_at = probe.index('if [[ "$DIAG_OUTCOME" != success ]]')
    assert unset_at < pull_at < inspect_at < remove_at < failure_at
    assert "/usr/bin/timeout --signal=TERM --kill-after=10s 300s" in probe
    assert "/usr/bin/timeout --foreground --signal=TERM --kill-after=10s 300s" not in probe
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    assert "exec /usr/bin/setsid /usr/bin/timeout --foreground" in batch


def test_every_podman_storage_writer_has_a_fail_closed_quiescence_handshake() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    assert probe.count("set_writer_state armed") == 5
    assert probe.count("set_writer_state quiesced") == 6
    assert probe.count("writer_is_quiesced || abandon_live_writer") == 3
    assert "private_runtime_armed && writer_state_required" in probe
    child = guard[guard.index("set +e\nset_writer_state armed") :]
    assert child.index("set_writer_state armed") < child.index('/usr/bin/podman "$@"')
    assert child.index('/usr/bin/podman "$@"') < child.index("set_writer_state quiesced")
    assert "private_dirs_bound && auth_path_bound && writer_is_quiesced" in guard


def test_signal_path_retains_private_files_when_tracked_wrapper_reaps_but_descendant_survives(
    tmp_path: Path,
) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    writer_functions = probe[probe.index("writer_state_file_bound()") : probe.index("image_identity_matches()")]
    signal_functions = textwrap.dedent(
        probe[probe.index("    abandon_live_writer()") : probe.index("    classify_token()")]
    )
    auth = tmp_path / "auth"
    auth.write_text("private-auth-material")
    auth.chmod(0o600)
    auth_inode = auth.stat().st_ino
    state = tmp_path / "writer-state"
    state.write_text("gate_writer_state=armed\n")
    state.chmod(0o600)
    cleanup_called = tmp_path / "cleanup-called"
    wrapper_pid_file = tmp_path / "wrapper-pid"
    survivor_pid_file = tmp_path / "survivor-pid"
    shell = (
        "set -euo pipefail\n"
        + writer_functions
        + signal_functions
        + "\nGATE_EXPECTED_UID=$(id -u)\n"
        + 'inspect_file=$1\nexec {inspect_fd}<>"$inspect_file"\n'
        + "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        + "writer_state_required=1\n_CONTAINER_REGISTRY_SPAWNING=0\n"
        + "_CONTAINER_REGISTRY_PENDING_SIGNAL=\n_CONTAINER_REGISTRY_PENDING_STATUS=\n"
        + '_container_registry_cleanup() { : > "$3"; rm -f -- "$2"; }\n'
        + "/usr/bin/bash -c '"
        + '/usr/bin/sleep 30 </dev/null >/dev/null 2>&1 & builtin printf "%s\\n" "$!" > "$1"; '
        + 'trap "exit 0" TERM; wait\' surviving-wrapper "$5" &\n'
        + "_CONTAINER_REGISTRY_ACTIVE_PID=$!\n"
        + 'builtin printf "%s\\n" "$_CONTAINER_REGISTRY_ACTIVE_PID" > "$4"\n'
        + 'for _ in {1..100}; do [[ -s "$5" ]] && break; /usr/bin/sleep 0.01; done\n'
        + '[[ -s "$5" ]]\n'
        + "_container_registry_signal_exit TERM 143\n"
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            shell,
            "signal-writer-state",
            str(state),
            str(auth),
            str(cleanup_called),
            str(wrapper_pid_file),
            str(survivor_pid_file),
        ],
        check=False,
        capture_output=True,
        timeout=10,
    )
    survivor_pid = int(survivor_pid_file.read_text())
    try:
        assert result.returncode == 143, result.stderr.decode()
        assert result.stdout == b""
        assert result.stderr == b"gate_category=live_writer_cleanup_unproven\n"
        assert auth.exists() and auth.stat().st_ino == auth_inode
        assert auth.read_text() == "private-auth-material"
        assert not cleanup_called.exists()
        wrapper_pid = int(wrapper_pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(wrapper_pid, 0)
        os.kill(survivor_pid, 0)
    finally:
        try:
            os.kill(survivor_pid, 9)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize(
    ("repo_digests", "architecture", "accepted"),
    [
        ("123456789012.dkr.ecr.us-east-2.amazonaws.com/repository@{digest}", "arm64", True),
        (
            "mirror.invalid/repository@{digest},123456789012.dkr.ecr.us-east-2.amazonaws.com/repository@{digest}",
            "arm64",
            True,
        ),
        ("mirror.invalid/repository@{digest}", "arm64", False),
        ("prefix123456789012.dkr.ecr.us-east-2.amazonaws.com/repository@{digest}", "arm64", False),
        ("123456789012.dkr.ecr.us-east-2.amazonaws.com/repository@{digest}", "amd64", False),
    ],
)
def test_image_identity_requires_exact_canonical_repository_digest_member(
    repo_digests: str, architecture: str, accepted: bool
) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    function = probe[probe.index("image_identity_matches()") : probe.index("mount_free_anchored_tree()")]
    digest = "sha256:" + "a" * 64
    image = f"123456789012.dkr.ecr.us-east-2.amazonaws.com/repository:tag@{digest}"
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            "set -euo pipefail\n" + function + '\nimage_identity_matches "$1" "$2" "$2" linux "$3" "$4"',
            "image-identity",
            image,
            digest,
            architecture,
            repo_digests.format(digest=digest),
        ],
        check=False,
        capture_output=True,
    )
    assert (result.returncode == 0) is accepted, result.stderr.decode()


def test_auth_fd_is_bound_before_lookup_and_fsynced_after_unlink() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    open_at = probe.index('exec {auth_fd}<>"$auth_path"')
    lookup_at = probe.index('podman login --authfile "$auth_path" --get-login')
    pull_at = probe.index('podman pull --authfile "$auth_path"')
    disarm_at = probe.index("_container_registry_disarm_cleanup", pull_at)
    truncate_at = probe.index('/usr/bin/truncate -s 0 -- "/proc/self/fd/$auth_fd"', disarm_at)
    sync_at = probe.index('/usr/bin/sync -f "/proc/self/fd/$auth_fd"', truncate_at)
    proof_at = probe.index('"$auth_after" == *":600:${GATE_EXPECTED_UID}:0:0"', sync_at)
    close_at = probe.index("exec {auth_fd}>&-", proof_at)
    assert open_at < lookup_at < pull_at < disarm_at < truncate_at < sync_at < proof_at < close_at


@pytest.mark.parametrize(
    ("value", "expected_shape", "expected_size"),
    [
        ("{not-json-content}", "json", "lt2k"),
        ("export TOKEN=value", "env_export", "lt2k"),
        ("AWS:private-value", "literal_basic", "lt2k"),
        ("A" * 2047 + "!", "bad_charset", "b2k_4k"),
        (base64.b64encode(b"AWS:" + b"A" * 1532).decode(), "encoded_basic", "b2k_4k"),
    ],
)
def test_token_shape_reject_classes_are_fixed(value: str, expected_shape: str, expected_size: str) -> None:
    shell = (
        "set -euo pipefail\n"
        + _v32_diagnostic_functions()
        + '\nclassify_token "$1"\n'
        + 'printf "%s:%s" "$DIAG_TOKEN_SHAPE" "$DIAG_TOKEN_SIZE"\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "token-shape", value],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode() == f"{expected_shape}:{expected_size}"


def _v32_diagnostic_functions() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("    classify_token()") : text.index("    diagnostic_pull_once()")]


@pytest.mark.parametrize(
    ("length", "expected_shape", "expected_size"),
    [
        (0, "empty", "none"),
        (2047, "too_short", "lt2k"),
        (2048, "valid_text", "b2k_4k"),
        (4096, "valid_text", "b4k_8k"),
        (8192, "valid_text", "b8k_16k"),
        (16384, "valid_text", "b8k_16k"),
        (16385, "too_long", "gt16k"),
    ],
)
def test_token_shape_boundaries_are_coarse(length: int, expected_shape: str, expected_size: str) -> None:
    shell = (
        "set -euo pipefail\n"
        + _v32_diagnostic_functions()
        + '\nvalue=$(head -c "$1" /dev/zero | tr "\\000" A)\n'
        + 'classify_token "$value"\n'
        + 'printf "%s:%s" "$DIAG_TOKEN_SHAPE" "$DIAG_TOKEN_SIZE"\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "token-shape", str(length)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode() == f"{expected_shape}:{expected_size}"


@pytest.mark.parametrize(
    ("raw", "rc", "outcome", "stage"),
    [
        ("", 125, "empty_125", "none"),
        ("gate_guard_stage=child\n", 125, "empty_125", "child"),
        ("gate_guard_stage=precondition\n", 125, "guard_precondition", "precondition"),
        ("gate_guard_stage=postcondition\n", 125, "guard_postcondition", "postcondition"),
        ("", 124, "timeout", "none"),
        ("request failed with status code 400\n", 1, "http_400", "none"),
        ("request failed with status 401\n", 1, "http_401", "none"),
        ("request failed with http status 403\n", 1, "http_403", "none"),
        ("request failed with status=404\n", 1, "http_404", "none"),
        ("request failed with status 429\n", 1, "http_other4xx", "none"),
        ("request failed with status 503\n", 1, "http_5xx", "none"),
        ("authorization token has expired\n", 1, "expired", "none"),
        ("not authorized\n", 1, "not_authorized", "none"),
        ("unauthorized\n", 1, "not_authorized", "none"),
        ("access denied\n", 1, "denied", "none"),
        ("invalid username/password\n", 1, "denied", "none"),
        ("authentication required\n", 1, "auth_challenge", "none"),
        ("manifest unknown\n", 1, "image_missing", "none"),
        ("no matching manifest\n", 1, "platform", "none"),
        ("digest mismatch\n", 1, "image_identity", "none"),
        ("no space left on device\n", 1, "storage", "none"),
        ("saving credentials failed\n", 1, "writeback", "none"),
        ("registries.conf parse failed\n", 1, "config", "none"),
        ("x509: certificate signed by unknown authority\n", 1, "tls", "none"),
        ("proxyconnect failed\n", 1, "proxy", "none"),
        ("dial tcp: connection refused\n", 1, "transport", "none"),
        (("unrecognized diagnostic text\n" * 4096), 125, "unknown", "none"),
        ("unrecognized private diagnostic\n", 125, "unknown", "none"),
    ],
)
def test_pull_classifier_emits_only_fixed_enums(tmp_path: Path, raw: str, rc: int, outcome: str, stage: str) -> None:
    diagnostic = tmp_path / "diagnostic"
    diagnostic.write_text(raw)
    shell = (
        "set -euo pipefail\n"
        + _v32_diagnostic_functions()
        + "\nDIAG_GUARD_STAGE=not_run; DIAG_OUTCOME=unknown\n"
        + 'classify_pull "$1" "$2"\n'
        + 'printf "%s:%s" "$DIAG_OUTCOME" "$DIAG_GUARD_STAGE"\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "pull-classifier", str(diagnostic), str(rc)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode() == f"{outcome}:{stage}"


def test_merged_lineage_preserves_guard_cleanup_and_publication_protections() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    scrubber = (HERE / "scrub_private_tree.py").read_text()
    assert "private_dirs_bound && auth_path_bound && writer_is_quiesced || guard_fail precondition" in guard
    assert "private_dirs_bound && auth_path_bound || guard_fail postcondition" in guard
    assert "preflight_batch_contents" in batch and "preflight_anchored_directory" in probe
    assert "cleanup_attempted" not in batch and "cleanup_attempted" not in probe
    assert "cleanup_retry_limit=3" in batch and "cleanup_retry_limit=3" in probe
    assert "cleanup_in_progress" in batch and "cleanup_in_progress" in probe
    assert "--bound-file" in batch and "--bound-file" in probe
    assert "os.O_NOFOLLOW" in scrubber and "unlinked.st_nlink == 0" in scrubber
    assert "publication_started" in batch and "publication_in_progress" in batch
    assert "finish_publication" in batch and batch.count("/usr/bin/printf '%s' \"$raw\" >&8") == 1
    assert controller.SIGNAL_LEAD_SECONDS == 240
    assert controller.SIGNAL_TEARDOWN_BOUND_SECONDS == 210


def test_cleanup_completion_follows_proof_and_has_no_attempt_latch() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    for text, function_name, proof_checkpoint in (
        (batch, "remove_batch_root()", "cleanup_checkpoint batch_after_retained_root_proof"),
        (probe, "retain_private_root()", "cleanup_checkpoint probe_after_scrub"),
    ):
        assert "cleanup_attempted" not in text
        function = text[text.index(function_name) : text.index("cleanup_private_tree()")]
        assert function.index(proof_checkpoint) < function.index("cleanup_complete=1")
        assert function.index("cleanup_complete=1") < function.index("cleanup_in_progress=0")
        assert "cleanup_retry_limit=3" in text
        assert "cleanup_exit_running=1" in text


def test_batch_has_one_production_shaped_srun() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    assert text.count("/usr/bin/srun -M") == 1
    for fragment in (
        "--overlap",
        "--nodes=1",
        "--ntasks=1",
        "--gpus-per-node=1",
        "--cpus-per-task=4",
        "--cpu-bind=none",
        "--export=ALL",
    ):
        assert fragment in text


def test_batch_public_output_is_only_emit() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    assert "raw=$(/usr/bin/printf" in text
    assert '/usr/bin/printf \'%s\' "$raw" >&"$publish_temp_fd"' in text
    assert "/usr/bin/printf '%s' \"$raw\" | /usr/bin/sha256sum" in text
    assert text.count("/usr/bin/printf '%s' \"$raw\" >&8") == 1
    assert "exec 8>&1 4>&2 || exit 3" in text
    assert "exec >/dev/null 2>/dev/null || exit 3" in text
    assert '>&"$stdout_fd" 2>&"$stderr_fd"' in text
    assert "GATE_JOB_RESULT" in text
    assert '/usr/bin/ln -- "$temp" "$result"' in text
    for line in text.splitlines():
        if "/usr/bin/unlink --" in line:
            assert line.count('"$') == 1
    assert "finish_publication" in text
    assert "cleanup_proof_count=$(/usr/bin/grep -Fxc 'gate_cleanup=retained_empty'" in text
    success_check = text[text.index("success='") : text.index("finish_publication success 0")]
    assert '"$cleanup_proof_count" == 1' in success_check
    assert "! /usr/bin/grep -q '^gate_category='" in success_check
    assert '"$(<"$stdout_stream")" == "$success"' in success_check


def test_batch_publisher_closes_before_unlink_and_emits_exact_payload(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    functions = text[text.index("cleanup_public_temp()") : text.index("emit()")]
    result_path = tmp_path / "result.json"
    temp_path = tmp_path / "result.json.synthetic.tmp"
    log_path = tmp_path / "slurm.log"
    raw = '{"category":"success","state":"complete"}\n'
    script = (
        "set -euo pipefail\npublication_child_checkpoint() { :; }\n"
        + functions
        + '\nexec 8>"$3"\npublish_payload "$4" "$2" "$1" "$1" "$(id -u)" "$$"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "publisher-test",
            str(result_path),
            str(temp_path),
            str(log_path),
            raw,
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == result.stderr == b""
    assert result_path.read_text() == raw
    assert log_path.read_text() == raw
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o400
    assert result_path.stat().st_nlink == 1
    assert not temp_path.exists()


def test_batch_publisher_reconciles_ambiguous_link_before_scrub(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    function = text[text.index("cleanup_public_temp()") : text.index("publish_payload()")]
    script = (
        "set -euo pipefail\n"
        + function
        + "\npublish_temp=$1/temp; publish_result=$1/result; publish_expected_uid=$(id -u); publish_committed=0\n"
        'printf payload > "$publish_temp"; publish_temp_fd=-1; exec {publish_temp_fd}<>"$publish_temp"; chmod 400 "$publish_temp"\n'
        'opened=$(stat -Lc \'%d:%i:%a:%u:%h:%s\' "/proc/self/fd/$publish_temp_fd"); IFS=: read -r dev ino mode uid links size <<< "$opened"; publish_temp_identity=$dev:$ino:$uid\n'
        'ln "$publish_temp" "$publish_result"\n'
        "cleanup_public_temp\n"
        '[[ $publish_committed == 1 && ! -e "$publish_temp" && $(<"$publish_result") == payload ]]\n'
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "link-reconcile", str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_publisher_scrubs_owned_fd_without_unlinking_replacement(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    function = text[text.index("cleanup_public_temp()") : text.index("publish_payload()")]
    script = (
        "set -euo pipefail\n"
        + function
        + "\npublish_temp=$1/temp; moved=$1/moved; publish_result=$1/result; publish_expected_uid=$(id -u); publish_committed=0\n"
        'printf payload > "$publish_temp"; publish_temp_fd=-1; exec {publish_temp_fd}<>"$publish_temp"; chmod 400 "$publish_temp"\n'
        'opened=$(stat -Lc \'%d:%i:%a:%u:%h:%s\' "/proc/self/fd/$publish_temp_fd"); IFS=: read -r dev ino mode uid links size <<< "$opened"; publish_temp_identity=$dev:$ino:$uid\n'
        'mv "$publish_temp" "$moved"; printf replacement > "$publish_temp"\n'
        "cleanup_public_temp\n"
        '[[ ! -s "$moved" && $(<"$publish_temp") == replacement ]]\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "temp-replacement", str(tmp_path)], capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()


def test_batch_publisher_is_killed_inside_one_teardown_deadline(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    functions = text[text.index("arm_teardown_deadline()") : text.index("block()")]
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=3; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "expected_digest=sha256:synthetic; expected_result=$1/result.json; GATE_JOB_RESULT=$expected_result; SLURM_JOB_ID=1\n"
        + functions
        + "\npublish_payload() { /usr/bin/sleep 30; }\n"
        'exec 8>"$2"\n'
        "set +e; emit internal; rc=$?; set -e\n"
        "[[ $rc -ne 0 && $SECONDS -le 4 ]]\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "deadline-test", str(tmp_path), str(log_path)],
        capture_output=True,
        timeout=6,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == result.stderr == b""
    assert log_path.read_bytes() == b""


def test_batch_emit_runs_bound_publisher_under_remaining_deadline(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    functions = text[text.index("arm_teardown_deadline()") : text.index("block()")]
    result_path = tmp_path / "result.json"
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=10; publication_reserve_seconds=2; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "expected_digest=sha256:synthetic; expected_result=$1; GATE_JOB_RESULT=$1; SLURM_JOB_ID=1\n"
        + functions
        + '\nexec 8>"$2"\n'
        f"emit {SUCCESS_CATEGORY}\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "emit-test", str(result_path), str(log_path)],
        capture_output=True,
        timeout=12,
    )
    assert result.returncode == 0, result.stderr.decode()
    expected = (
        f'{{"category":"{SUCCESS_CATEGORY}","image_digest":"sha256:synthetic",'
        '"kind":"k3-registry-direct-pull-gate-v32","platform":"linux/arm64","state":"complete"}\n'
    )
    assert result_path.read_text() == expected
    assert log_path.read_text() == expected
    assert not list(tmp_path.glob("*.tmp"))


PUBLICATION_CHECKPOINTS = [
    "parent_before_started",
    "parent_after_started",
    "parent_before_publisher",
    "parent_after_publisher",
    "parent_before_in_progress_clear",
    "parent_after_in_progress_clear",
    "child_before_temp_open",
    "child_after_temp_open",
    "child_after_temp_identity",
    "child_after_temp_write",
    "child_after_temp_sync",
    "child_before_link",
    "child_after_link",
    "child_before_temp_close",
    "child_after_temp_close",
    "child_before_temp_unlink",
    "child_after_temp_unlink",
    "child_after_result_sync",
    "child_before_fd8",
    "child_after_fd8",
    "child_after_fd8_sync",
]


@pytest.mark.parametrize(("signal_name", "status"), [("HUP", 129), ("INT", 130), ("TERM", 143)])
@pytest.mark.parametrize("checkpoint", PUBLICATION_CHECKPOINTS)
def test_batch_publication_defers_signal_and_emits_at_most_once(
    tmp_path: Path, checkpoint: str, signal_name: str, status: int
) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    functions = text[text.index("arm_teardown_deadline()") : text.index("block()")]
    result_path = tmp_path / "result.json"
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=10; publication_reserve_seconds=2; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "pending_signal=; pending_signal_status=130; injected=0; target=$3; signal_name=$4\n"
        "expected_digest=sha256:synthetic; expected_result=$1; GATE_JOB_RESULT=$1; SLURM_JOB_ID=1\n"
        + functions
        + '\nremember_signal() { pending_signal=$1; case "$1" in HUP) pending_signal_status=129;; INT) pending_signal_status=130;; TERM) pending_signal_status=143;; esac; }\n'
        'handle_test_signal() { remember_signal "$1"; if (( publication_started && publication_in_progress )); then :; elif (( publication_started )); then exit "$pending_signal_status"; else finish_publication interrupted "$pending_signal_status"; fi; }\n'
        'publication_checkpoint() { if (( injected == 0 )) && [[ $1 == "$target" ]]; then injected=1; kill -"$signal_name" "$$"; fi; }\n'
        'publication_child_checkpoint() { if [[ $1 == "${PUBLICATION_TEST_TARGET:-}" ]]; then kill -"${PUBLICATION_TEST_SIGNAL:-TERM}" "$publication_parent_pid"; fi; }\n'
        "export PUBLICATION_TEST_TARGET=$target PUBLICATION_TEST_SIGNAL=$signal_name\n"
        'exec 8>"$2"\n'
        "trap 'handle_test_signal HUP' HUP; trap 'handle_test_signal INT' INT; trap 'handle_test_signal TERM' TERM\n"
        "finish_publication success 0\n"
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "publication-signal",
            str(result_path),
            str(log_path),
            checkpoint,
            signal_name,
        ],
        capture_output=True,
        timeout=12,
    )
    assert result.returncode == status, (checkpoint, signal_name, result.stderr.decode())
    assert result.stdout == result.stderr == b""
    assert result_path.exists()
    assert result_path.read_bytes() == log_path.read_bytes()
    assert len(log_path.read_text().splitlines()) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_batch_signal_during_slow_publisher_uses_one_deadline_and_never_reenters(tmp_path: Path) -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    functions = text[text.index("arm_teardown_deadline()") : text.index("block()")]
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=3; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "pending_signal=; pending_signal_status=130\n"
        "expected_digest=sha256:synthetic; expected_result=$1/result.json; GATE_JOB_RESULT=$expected_result; SLURM_JOB_ID=1\n"
        + functions
        + "\nremember_signal() { pending_signal=$1; pending_signal_status=143; }\n"
        'handle_test_signal() { remember_signal "$1"; if (( publication_started && publication_in_progress )); then :; else exit "$pending_signal_status"; fi; }\n'
        'publish_payload() { kill -TERM "$6"; /usr/bin/sleep 30; }\n'
        'exec 8>"$2"\n'
        "trap 'handle_test_signal TERM' TERM\n"
        "finish_publication success 0\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "slow-signal", str(tmp_path), str(log_path)],
        capture_output=True,
        timeout=6,
    )
    assert result.returncode == 143, result.stderr.decode()
    assert result.stdout == result.stderr == b""
    assert log_path.read_bytes() == b""
    assert not (tmp_path / "result.json").exists()


def test_batch_failure_scrubs_private_state_before_publication() -> None:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    block = text[text.index("block()") : text.index("[[ $# == 0")]
    assert block.index("cleanup_private_tree") < block.index('finish_publication "$category"')
    assert "private_cleanup_retained" in block
    assert "private_cleanup_sensitive" in block


def test_batch_empty_log_uses_numeric_identity_not_percent_f(tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.touch(mode=0o600)
    observed = subprocess.run(
        ["/usr/bin/stat", "-Lc", "%F", str(empty)], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert observed == "regular empty file"
    text = (HERE / "run_registry_gate.sbatch").read_text()
    log_block = text[text.index("stable_log_reads=0") : text.index("readonly local_parent")]
    assert "%F" not in log_block
    assert "/proc/self/fd/8" in log_block and "/proc/self/fd/4" in log_block


def test_exact_bytes_are_executed_from_bound_descriptors() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert 'exec 9<"${BASH_SOURCE[0]}"' in batch
    assert 'exec 7<"$classifier" 6<"$probe" 5<"$tools_manifest" 3<"$scrubber"' in batch
    assert "/usr/bin/sha256sum -- /proc/self/fd/9" in batch
    assert 'exec </proc/self/fd/6 >&"$stdout_fd" 2>&"$stderr_fd"' in batch
    assert 'classify_registry_error_file "$stderr_stream" "$rc" "$stderr_identity"' in batch
    assert "exec /usr/bin/setsid /usr/bin/timeout" in batch
    assert "/usr/bin/bash -p -s" in batch
    assert "source /proc/self/fd/8" in probe
    assert "source /proc/self/fd/9" in probe
    assert 'exec 9<"$worker" 8<"$aws_creds" 7<"$tools_manifest"' in probe
    assert "readonly scrubber=${GATE_LOCAL_SCRUBBER:-}" in probe
    assert '"$scrubber" != /proc/self/fd/*' in probe
    assert '"$scrubber" == "$(/usr/bin/readlink -f -- "$scrubber" 2>/dev/null)"' in probe


def test_descriptor_only_opens_restore_stderr(tmp_path: Path) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    for fragment in (
        'if ! { exec 9<"$worker"',
        'if ! { exec 4<"$tls_source"; } 2>/dev/null',
        'if ! { exec {private_root_fd}<"$private_root"; } 2>/dev/null',
        '{ exec {storage_conf_fd}<>"$storage_conf"; } 2>/dev/null',
        '{ exec {local_tls_fd}<>"$local_tls"; } 2>/dev/null',
        '{ exec {inspect_fd}<>"$inspect_file"; } 2>/dev/null',
        'if ! { exec {graphroot_fd}<"$graphroot"',
        '{ exec {auth_fd}<>"$auth_path"; } 2>/dev/null',
    ):
        assert fragment in probe
    for fragment in (
        'if { exec {publish_temp_fd}>"$temp"; } 2>/dev/null',
        'if ! { exec 9<"${BASH_SOURCE[0]}"; } 2>/dev/null',
        'if ! { exec 7<"$classifier" 6<"$probe"',
        'if ! { exec {private_fd}<"$private"; } 2>/dev/null',
        '{ exec {stdout_fd}<>"$stdout"; } 2>/dev/null',
        '{ exec {stderr_fd}<>"$stderr"; } 2>/dev/null',
        'if ! { exec {local_tools_fd}<>"$local_tools"; } 2>/dev/null',
        'if ! { exec {local_scrubber_fd}<>"$local_scrubber"; } 2>/dev/null',
    ):
        assert fragment in batch
    for text in (probe, batch.replace("exec >/dev/null 2>/dev/null || exit 3", "")):
        assert re.search(r"\bexec[^;\n]*(?:<|>)[^;\n]* 2>/dev/null", text) is None

    stderr_file = tmp_path / "stderr"
    source_file = tmp_path / "source"
    source_file.write_text("bound")
    script = (
        'exec 2>"$1"\n'
        'if ! { exec 9<"$2"; } 2>/dev/null; then exit 3; fi\n'
        'if ! { exec 8<"$3"; } 2>/dev/null; then printf "gate_category=open_failed\\n" >&2; fi\n'
        'printf "gate_category=marker_visible\\n" >&2\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "fd2-restore",
            str(stderr_file),
            str(source_file),
            str(tmp_path / "missing"),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert stderr_file.read_text().splitlines() == [
        "gate_category=open_failed",
        "gate_category=marker_visible",
    ]


def test_batch_normalizes_sealed_copy_modes_before_rw_descriptor_open() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    tools_copy = batch.index('/usr/bin/cp -- /proc/self/fd/5 "$local_tools"')
    tools_chmod = batch.index('/usr/bin/chmod 600 "$local_tools"', tools_copy)
    tools_open = batch.index('exec {local_tools_fd}<>"$local_tools"', tools_chmod)
    scrubber_copy = batch.index('/usr/bin/cp -- /proc/self/fd/3 "$local_scrubber"')
    scrubber_chmod = batch.index('/usr/bin/chmod 600 "$local_scrubber"', scrubber_copy)
    scrubber_open = batch.index('exec {local_scrubber_fd}<>"$local_scrubber"', scrubber_chmod)
    assert tools_copy < tools_chmod < tools_open
    assert scrubber_copy < scrubber_chmod < scrubber_open


def test_cleanup_traps_precede_first_mktemp() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert "shopt -u varredir_close" in batch
    assert "shopt -u varredir_close" in probe
    assert batch.index("trap exit_cleanup EXIT") < batch.index("private=$(/usr/bin/mktemp")
    assert probe.index("trap exit_cleanup EXIT") < probe.index("private_root=$(/usr/bin/mktemp")
    assert (
        batch.index("private=$(/usr/bin/mktemp")
        < batch.index('exec {private_fd}<"$private"')
        < batch.index('/usr/bin/touch "$stdout"')
    )
    assert (
        probe.index("private_root=$(/usr/bin/mktemp")
        < probe.index('exec {private_root_fd}<"$private_root"')
        < probe.index('/usr/bin/mkdir -m 700 -- "$graphroot"')
    )


def test_private_cleanup_makes_read_only_files_writable_before_truncation() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    scrubber = (HERE / "scrub_private_tree.py").read_text()
    scrub = batch[batch.index("scrub_batch_contents()") : batch.index("remove_batch_root()")]
    assert scrub.index('/usr/bin/chmod 600 -- "/proc/self/fd/$owned_fd"') < scrub.index(
        '/usr/bin/truncate -s 0 -- "/proc/self/fd/$owned_fd"'
    )
    assert scrubber.index("os.fchmod(file_fd, 0o600)") < scrubber.index("os.ftruncate(file_fd, 0)")
    assert scrubber.index("os.ftruncate(file_fd, 0)") < scrubber.index("os.unlink(name, dir_fd=parent_fd)")


def run_scrubber(root: Path, *exclusions: str) -> subprocess.CompletedProcess[bytes]:
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        device = os.fstat(directory_fd).st_dev
        specification = f"{directory_fd}:{','.join(exclusions)}"
        return subprocess.run(
            [
                "/usr/bin/python3.12",
                "-I",
                "-S",
                "-B",
                str(HERE / "scrub_private_tree.py"),
                str(os.getuid()),
                str(device),
                specification,
            ],
            pass_fds=(directory_fd,),
            capture_output=True,
        )
    finally:
        os.close(directory_fd)


def test_fd_scrubber_truncates_unlinks_files_and_retains_empty_directories(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nested = root / "graphroot" / "nested"
    nested.mkdir(parents=True, mode=0o700)
    (root / "tls").write_bytes(b"synthetic-tls")
    (nested / "layer").write_bytes(b"synthetic-layer")
    (root / "tls").chmod(0o400)
    (nested / "layer").chmod(0o400)
    result = run_scrubber(root)
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""
    assert root.is_dir() and nested.is_dir()
    assert not any(path.is_file() for path in root.rglob("*"))


@pytest.mark.parametrize("entry_kind", ["hardlink", "symlink", "fifo", "socket"])
def test_fd_scrubber_rejects_unsafe_entry_types_without_mutation(tmp_path: Path, entry_kind: str) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.write_bytes(b"synthetic-external")
    target = root / "unsafe"
    if entry_kind == "hardlink":
        os.link(external, target)
    elif entry_kind == "symlink":
        target.symlink_to(external)
    elif entry_kind == "fifo":
        os.mkfifo(target, 0o600)
    else:
        unix_socket = socket.socket(socket.AF_UNIX)
        unix_socket.bind(str(target))
        unix_socket.close()
    result = run_scrubber(root)
    assert result.returncode == 41
    assert result.stdout == result.stderr == b""
    assert target.exists() or target.is_symlink()
    assert external.read_bytes() == b"synthetic-external"


def test_fd_scrubber_rejects_simulated_device_crossing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    crossing = root / "crossing"
    crossing.write_bytes(b"synthetic-crossing")
    spec = importlib.util.spec_from_file_location("registry_direct_pull_v32_scrubber", HERE / "scrub_private_tree.py")
    assert spec is not None and spec.loader is not None
    scrubber = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scrubber)
    real_stat = scrubber.os.stat

    def crossed_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        observed = real_stat(path, *args, **kwargs)
        if path == "crossing" and kwargs.get("dir_fd") is not None:
            fields = list(observed)
            fields[2] = observed.st_dev + 1
            return os.stat_result(fields)
        return observed

    monkeypatch.setattr(scrubber.os, "stat", crossed_stat)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(scrubber.UnsafeTree):
            scrubber.scrub_directory(directory_fd, os.getuid(), os.fstat(directory_fd).st_dev, frozenset(), set())
    finally:
        os.close(directory_fd)
    assert crossing.read_bytes() == b"synthetic-crossing"


def test_fd_scrubber_globally_preflights_all_roots_before_mutation(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir(mode=0o700)
    second.mkdir(mode=0o700)
    (first / "private").write_bytes(b"first-secret")
    os.mkfifo(second / "reject-fifo", 0o600)
    first_fd = os.open(first, os.O_RDONLY | os.O_DIRECTORY)
    second_fd = os.open(second, os.O_RDONLY | os.O_DIRECTORY)
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3.12",
                "-I",
                "-S",
                "-B",
                str(HERE / "scrub_private_tree.py"),
                str(os.getuid()),
                str(os.fstat(first_fd).st_dev),
                f"{first_fd}:",
                f"{second_fd}:",
            ],
            pass_fds=(first_fd, second_fd),
            capture_output=True,
        )
    finally:
        os.close(second_fd)
        os.close(first_fd)
    assert result.returncode == 41
    assert (first / "private").read_bytes() == b"first-secret"
    assert (second / "reject-fifo").is_fifo()


def test_bound_file_scrubber_unlinks_exact_inode_and_proves_nlink_zero(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = root / "raw"
    target.write_bytes(b"synthetic-private")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    target_fd = os.open(target, os.O_RDWR)
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3.12",
                "-I",
                "-S",
                "-B",
                str(HERE / "scrub_private_tree.py"),
                "--bound-file",
                str(os.getuid()),
                str(os.fstat(root_fd).st_dev),
                str(root_fd),
                "raw",
                str(target_fd),
            ],
            pass_fds=(root_fd, target_fd),
            capture_output=True,
        )
        assert result.returncode == 0
        assert os.fstat(target_fd).st_size == 0
        assert os.fstat(target_fd).st_nlink == 0
        assert not target.exists()
    finally:
        os.close(target_fd)
        os.close(root_fd)


def test_bound_file_scrubber_preserves_replacement_and_returns_retained_drift(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target = root / "raw"
    moved = root / "moved"
    target.write_bytes(b"synthetic-private")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    target_fd = os.open(target, os.O_RDWR)
    target.rename(moved)
    target.write_bytes(b"replacement")
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3.12",
                "-I",
                "-S",
                "-B",
                str(HERE / "scrub_private_tree.py"),
                "--bound-file",
                str(os.getuid()),
                str(os.fstat(root_fd).st_dev),
                str(root_fd),
                "raw",
                str(target_fd),
            ],
            pass_fds=(root_fd, target_fd),
            capture_output=True,
        )
        assert result.returncode == 42
        assert os.fstat(target_fd).st_size == 0
        assert os.fstat(target_fd).st_nlink == 1
        assert moved.stat().st_size == 0
        assert target.read_bytes() == b"replacement"
    finally:
        os.close(target_fd)
        os.close(root_fd)


def _batch_cleanup_functions() -> str:
    text = (HERE / "run_registry_gate.sbatch").read_text()
    return text[text.index("batch_mount_free()") : text.index("early_signal()")]


def _batch_fd_setup() -> str:
    return (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        "private=$1/original\n"
        'mkdir -m 700 -- "$private"\n'
        "private_fd=-1\nstdout_fd=-1\nstderr_fd=-1\nlocal_tools_fd=-1\nlocal_scrubber_fd=-1\n"
        'scrubber_exec_fd=-1\nexec {scrubber_exec_fd}<"$2"\n'
        'exec {private_fd}<"$private"\n'
        "private_anchor=/proc/self/fd/${private_fd}/.\n"
        "private_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_anchor\")\n"
        "private_anchor_trusted=1\n"
        "cleanup_complete=0\ncleanup_outcome=sensitive_residue\ncleanup_root_drift=0\n"
        "cleanup_running=0\ncleanup_in_progress=0\ncleanup_exit_running=0\ncleanup_retry_limit=3\n"
        "cleanup_deadline=$((SECONDS + 30))\npending_signal=\npending_signal_status=130\n"
        "writer_state=absent\nspawning=0\nactive_pid=\nactive_group_id=\n"
        "active_writer_live() { return 1; }\nwriter_cleanup_allowed() { ! active_writer_live; }\n"
        "mark_live_writer_cleanup_unproven() { writer_state=unproven; cleanup_outcome=live_writer_cleanup_unproven; }\n"
        "cleanup_checkpoint() { :; }\n"
        "stdout=$private_anchor/stdout\nstderr=$private_anchor/stderr\n"
        "local_tools=$private_anchor/compute_tools.sha256\n"
        "local_scrubber=$private_anchor/scrub_private_tree.py\n"
        'touch "$stdout" "$stderr" "$local_tools"\n'
        'printf tools > "$local_tools"; cp "$2" "$local_scrubber"\n'
        'chmod 600 "$local_tools" "$local_scrubber"\n'
        'exec {stdout_fd}<>"$stdout" {stderr_fd}<>"$stderr" {local_tools_fd}<>"$local_tools" {local_scrubber_fd}<>"$local_scrubber"\n'
        'chmod 600 "$stdout" "$stderr"; chmod 400 "$local_tools"; chmod 500 "$local_scrubber"\n'
        "stdout_clean=0\nstderr_clean=0\nlocal_tools_clean=0\nlocal_scrubber_clean=0\n"
        "stdout_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$stdout_fd)\n"
        "stderr_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$stderr_fd)\n"
        "local_tools_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$local_tools_fd)\n"
        "local_scrubber_identity=$(stat -Lc '%d:%i:%a:%u:%h' /proc/self/fd/$local_scrubber_fd)\n"
        "printf stdout-secret > /proc/self/fd/$stdout_fd\n"
        "printf stderr-secret > /proc/self/fd/$stderr_fd\n"
        "exec {check_stdout}>&$stdout_fd {check_stderr}>&$stderr_fd\n"
    )


def test_batch_retains_scrubbed_root_and_exact_log_descriptors(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup() + _batch_cleanup_functions() + "\ncleanup_private_tree\n"
        "[[ -d $private && ! -L $private ]]\n"
        "[[ $private_fd == -1 && $stdout_fd == -1 && $stderr_fd == -1 && $local_tools_fd == -1 && $local_scrubber_fd == -1 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        '[[ -z "$(find "$private" -mindepth 1 -print -quit)" ]]\n'
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "anchor-test", str(tmp_path), str(HERE / "scrub_private_tree.py")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_batch_empty_root_swap_after_scrub_is_preserved(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + '\nscrub_batch_contents\nmoved=$1/moved\nmv "$private" "$moved"\nmkdir -m 700 -- "$private"\n'
        'replacement_identity=$(stat -c "%d:%i" "$private")\n'
        "set +e; cleanup_private_tree; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(stat -c "%d:%i" "$private") == "$replacement_identity" ]]\n'
        '[[ -z "$(find "$moved" -mindepth 1 -print -quit)" ]]\n'
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "anchor-test", str(tmp_path), str(HERE / "scrub_private_tree.py")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_batch_named_log_replacement_is_preserved_while_exact_inode_is_scrubbed(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + '\nmv "$private/stdout" "$1/moved-stdout"\nprintf keep > "$private/stdout"\n'
        "set +e; cleanup_private_tree; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(<"$private/stdout") == keep ]]\n'
        '[[ $(stat -c %s "$1/moved-stdout") == 0 ]]\n'
        "[[ $(stat -Lc %s /proc/self/fd/$check_stdout) == 0 ]]\n"
        "[[ $(stat -Lc %s /proc/self/fd/$check_stderr) == 0 ]]\n"
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "inode-test", str(tmp_path), str(HERE / "scrub_private_tree.py")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_batch_global_preflight_rejects_before_any_log_mutation(tmp_path: Path) -> None:
    script = (
        _batch_fd_setup() + _batch_cleanup_functions() + '\nln "$private/compute_tools.sha256" "$1/outside-hardlink"\n'
        "set +e; scrub_batch_contents; rc=$?; set -e\n"
        "[[ $rc -ne 0 ]]\n"
        '[[ $(<"$private/stdout") == stdout-secret && $(<"$private/stderr") == stderr-secret ]]\n'
        '[[ $(<"$private/compute_tools.sha256") == tools ]]\n'
        "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "batch-global-preflight",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


BATCH_CLEANUP_CHECKPOINTS = [
    "batch_before_cleanup_running",
    "batch_cleanup_running",
    "batch_before_attempt",
    "batch_before_in_progress",
    "batch_in_progress",
    "batch_scrub_start",
    *[
        f"batch_{position}_{boundary}{suffix}"
        for boundary in ("stdout", "stderr", "tools")
        for position, suffix in (
            ("before", ""),
            ("after", "_stat"),
            ("after", "_chmod"),
            ("after", "_truncate"),
            ("before", "_unlink"),
            ("after", "_unlink"),
            ("after", ""),
        )
    ],
    "batch_before_scrubber",
    "batch_after_scrubber_stat",
    "batch_before_scrubber_unlink",
    "batch_after_scrubber_unlink",
    "batch_after_scrubber",
    "batch_before_empty_check",
    "batch_after_empty_check",
    "batch_after_scrub",
    "batch_before_named_stat",
    "batch_after_named_stat",
    "batch_before_retained_root_proof",
    "batch_after_retained_root_proof",
    "batch_before_fd_close",
    "batch_after_fd_close",
    "batch_before_complete",
    "batch_after_complete",
    "batch_before_in_progress_clear",
    "batch_after_in_progress",
    "batch_after_attempt",
    "batch_before_cleanup_running_clear",
    "batch_after_cleanup_running",
]


@pytest.mark.parametrize(("signal_name", "status"), [("HUP", 129), ("INT", 130), ("TERM", 143)])
@pytest.mark.parametrize("checkpoint", BATCH_CLEANUP_CHECKPOINTS)
def test_batch_cleanup_defers_signal_at_every_checkpoint(
    tmp_path: Path, checkpoint: str, signal_name: str, status: int
) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + "\ninjected=0; target=$3; signal_name=$4\n"
        + 'remember_signal() { pending_signal=$1; case "$1" in HUP) pending_signal_status=129;; INT) pending_signal_status=130;; TERM) pending_signal_status=143;; esac; }\n'
        + 'handle_test_signal() { remember_signal "$1"; if (( cleanup_running || cleanup_in_progress || cleanup_exit_running )); then return; fi; exit "$pending_signal_status"; }\n'
        + 'cleanup_checkpoint() { if (( injected == 0 )) && [[ $1 == "$target" ]]; then injected=1; kill -"$signal_name" "$$"; fi; }\n'
        + "trap exit_cleanup EXIT\n"
        + "trap 'handle_test_signal HUP' HUP; trap 'handle_test_signal INT' INT; trap 'handle_test_signal TERM' TERM\n"
        + "cleanup_private_tree\n"
        + '[[ -z "$pending_signal" ]] || exit "$pending_signal_status"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "batch-cleanup-signal",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
            checkpoint,
            signal_name,
        ],
        capture_output=True,
        timeout=12,
    )
    assert result.returncode == status, (checkpoint, signal_name, result.stderr.decode())
    assert result.stdout == result.stderr == b""
    assert (tmp_path / "original").is_dir()
    assert not any((tmp_path / "original").iterdir())


def test_batch_cleanup_retries_after_interrupted_partial_scrub(tmp_path: Path) -> None:
    functions = _batch_cleanup_functions().replace("scrub_batch_contents() {", "real_scrub_batch_contents() {", 1)
    script = (
        _batch_fd_setup()
        + functions
        + "\nscrub_calls=0\n"
        + "cleanup_checkpoint() { :; }\n"
        + "remember_signal() { pending_signal=$1; pending_signal_status=143; }\n"
        + "handle_test_signal() { remember_signal TERM; return; }\n"
        + 'scrub_batch_contents() { scrub_calls=$((scrub_calls + 1)); if (( scrub_calls == 1 )); then chmod 600 "$stdout"; truncate -s 0 "$stdout"; kill -TERM "$$"; return 1; fi; real_scrub_batch_contents; }\n'
        + "trap exit_cleanup EXIT; trap handle_test_signal TERM\n"
        + 'cleanup_private_tree; [[ $scrub_calls == 2 ]]; [[ -z "$pending_signal" ]] || exit "$pending_signal_status"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "batch-cleanup-retry",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
        timeout=12,
    )
    assert result.returncode == 143, result.stderr.decode()
    assert (tmp_path / "original").is_dir()
    assert not any((tmp_path / "original").iterdir())


def _probe_directory_scrubber() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("mount_free_anchored_tree()") : text.index("preflight_exact_probe_file()")]


def _probe_cleanup_functions() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("private_root_bound()") : text.index("trap exit_cleanup EXIT")]


def _probe_exact_file_scrubber() -> str:
    text = (HERE / "probe_registry_gate.sh").read_text()
    return text[text.index("preflight_exact_probe_file()") : text.index("close_probe_private_fds()")]


def _probe_cleanup_setup() -> str:
    return (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'private_root_fd=-1\nexec {private_root_fd}<"$private_root"\n'
        "private_root_anchor=/proc/self/fd/${private_root_fd}/.\n"
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_complete=0\ncleanup_outcome=sensitive_residue\n"
        "cleanup_root_drift=0\ncleanup_running=0\ncleanup_in_progress=0\ncleanup_exit_running=0\n"
        "cleanup_retry_limit=3\ncleanup_deadline=$((SECONDS + 30))\npending_signal=\npending_signal_status=130\n"
        "private_runtime_armed=1\nwriter_state_required=0\npodman_guard_fd=-1\npodman_guard_alias=\n"
        "podman_guard_alias_anchor=\npodman_guard_alias_identity=\npodman_guard_alias_clean=0\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$2"\n'
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\nprivate_dir_identities=()\n"
        "private_dir_manifests=()\n"
        "for name in graphroot xdg-runtime xdg-config xdg-data home tmp; do\n"
        ' path="$private_root/$name"; mkdir -m 700 -- "$path"; printf secret > "$path/private"\n'
        ' exec {held}<"$path"; private_dir_paths+=("$path"); private_dir_fds+=("$held")\n'
        ' private_dir_anchors+=("/proc/self/fd/${held}/.")\n'
        " private_dir_identities+=(\"$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/${held}/.)\")\n"
        " unset held\ndone\n"
        'xdg_runtime=$private_root/xdg-runtime\nrunroot=$xdg_runtime/containers\nmkdir -m 700 -- "$runroot"\n'
        'printf secret > "$runroot/private"\nrunroot_anchor=${private_dir_anchors[1]}/containers\n'
        "runroot_identity=$(stat -Lc '%d:%i:%a:%u' \"$runroot_anchor\")\n"
        "private_tmp=$private_root/tmp\n"
        "storage_conf=$private_root/storage.conf\nlocal_tls=$private_root/tls-combined.pem\ninspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf tls-secret > "$local_tls"; printf inspect-secret > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        "storage_conf_clean=0\nlocal_tls_clean=0\ninspect_clean=0\n"
    )


def test_probe_cleanup_refuses_to_mutate_while_writer_state_is_armed(tmp_path: Path) -> None:
    shell = (
        _probe_cleanup_setup()
        + _probe_cleanup_functions()
        + "\ncleanup_checkpoint() { :; }\n"
        + "builtin printf 'gate_writer_state=armed\\n' > /proc/self/fd/$inspect_fd\n"
        + "writer_state_required=1\n"
        + "if cleanup_private_tree; then exit 91; fi\n"
        + "[[ $cleanup_outcome == live_writer_cleanup_unproven ]]\n"
        + '[[ -f "$private_root/graphroot/private" ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            shell,
            "writer-state-cleanup",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_tls_inode_is_armed_before_copy_and_signal_scrubs_partial_bytes(tmp_path: Path) -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    open_at = probe.index('exec {local_tls_fd}<>"$local_tls"')
    armed_at = probe.index("local_tls_identity=$(/usr/bin/stat -Lc '%d:%i'", open_at)
    copy_at = probe.index('/usr/bin/cp -- /proc/self/fd/4 "/proc/self/fd/$local_tls_fd"')
    assert open_at < armed_at < copy_at

    tls_copy = tmp_path / "tls-combined.pem"
    shell = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nlocal_tls=$1\n"
        "private_root_fd=-1\nscrubber_fd=-1\n"
        'exec {private_root_fd}<"${local_tls%/*}"; exec {scrubber_fd}<"$2"\n'
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/$private_root_fd)\n"
        "cleanup_deadline=$((SECONDS + 30))\n"
        'touch "$local_tls"; chmod 600 "$local_tls"; exec {local_tls_fd}<>"$local_tls"\n'
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        + _probe_exact_file_scrubber()
        + '\ntrap \'scrub_exact_probe_file "$local_tls_fd" "$local_tls_identity" tls-combined.pem; exit 130\' TERM\n'
        'printf partial-private-tls > "/proc/self/fd/$local_tls_fd"\nkill -TERM $$\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            shell,
            "tls-signal-test",
            str(tls_copy),
            str(HERE / "scrub_private_tree.py"),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 130
    assert not tls_copy.exists()


def test_early_cleanup_scrubs_tls_before_directory_descriptors_exist(tmp_path: Path) -> None:
    shell = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'exec {private_root_fd}<"$private_root"\nprivate_root_anchor=/proc/self/fd/${private_root_fd}/.\n'
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_complete=0\n"
        "cleanup_outcome=sensitive_residue\ncleanup_root_drift=0\ncleanup_running=0\n"
        "cleanup_in_progress=0\ncleanup_exit_running=0\ncleanup_retry_limit=3\n"
        "cleanup_deadline=$((SECONDS + 30))\npending_signal=\npending_signal_status=130\n"
        "cleanup_checkpoint() { :; }\nprivate_runtime_armed=0\npodman_guard_fd=-1\n"
        "podman_guard_alias=\npodman_guard_alias_anchor=\npodman_guard_alias_identity=\npodman_guard_alias_clean=0\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$2"\n'
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\n"
        "private_dir_identities=()\nprivate_dir_manifests=()\n"
        'mkdir -m 700 -- "$private_root/graphroot" "$private_root/xdg-runtime" '
        '"$private_root/xdg-config" "$private_root/home" "$private_root/tmp"\n'
        'mkdir -m 700 -- "$private_root/xdg-runtime/containers"\n'
        "storage_conf=$private_root/storage.conf; local_tls=$private_root/tls-combined.pem; inspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf partial-private-tls > "$local_tls"; : > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        "storage_conf_clean=0\nlocal_tls_clean=0\ninspect_clean=0\n"
        + _probe_cleanup_functions()
        + "\nset +e; scrub_private_contents; rc=$?; set -e\n"
        '[[ $rc -ne 0 && ! -e "$local_tls" ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            shell,
            "early-tls-cleanup",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_probe_retains_verified_scrubbed_root_and_child_directories(tmp_path: Path) -> None:
    script = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'private_root_fd=-1\nexec {private_root_fd}<"$private_root"\n'
        "private_root_anchor=/proc/self/fd/${private_root_fd}/.\n"
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_complete=0\ncleanup_outcome=sensitive_residue\n"
        "cleanup_root_drift=0\ncleanup_running=0\ncleanup_in_progress=0\ncleanup_exit_running=0\n"
        "cleanup_retry_limit=3\ncleanup_deadline=$((SECONDS + 30))\npending_signal=\npending_signal_status=130\n"
        "cleanup_checkpoint() { :; }\nprivate_runtime_armed=1\n"
        "podman_guard_fd=-1\npodman_guard_alias=\npodman_guard_alias_anchor=\npodman_guard_alias_identity=\npodman_guard_alias_clean=0\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$2"\n'
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\nprivate_dir_identities=()\n"
        "private_dir_manifests=()\npodman_guard_fd=-1\n"
        "for name in graphroot xdg-runtime xdg-config xdg-data home tmp; do\n"
        ' path="$private_root/$name"; mkdir -m 700 -- "$path"; printf secret > "$path/private"\n'
        ' exec {held}<"$path"; private_dir_paths+=("$path"); private_dir_fds+=("$held")\n'
        ' private_dir_anchors+=("/proc/self/fd/${held}/.")\n'
        " private_dir_identities+=(\"$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/${held}/.)\")\n"
        " unset held\ndone\n"
        'xdg_runtime=$private_root/xdg-runtime\nrunroot=$xdg_runtime/containers\nmkdir -m 700 -- "$runroot"\n'
        'printf secret > "$runroot/private"\nrunroot_anchor=${private_dir_anchors[1]}/containers\n'
        "runroot_identity=$(stat -Lc '%d:%i:%a:%u' \"$runroot_anchor\")\n"
        "storage_conf=$private_root/storage.conf\nlocal_tls=$private_root/tls-combined.pem\ninspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf tls > "$local_tls"; printf inspect > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        'chmod 500 "$local_tls"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        "storage_conf_clean=0\nlocal_tls_clean=0\ninspect_clean=0\nprivate_tmp=$private_root/tmp\n"
        + _probe_cleanup_functions()
        + "\nretain_private_root\n"
        '[[ -d "$private_root" && ! -L "$private_root" ]]\n'
        'for path in "${private_dir_paths[@]}"; do [[ -d "$path" && -z "$(find "$path" -mindepth 1 ! -type d -print -quit)" ]]; done\n'
        '[[ -d "$runroot" && -z "$(find "$runroot" -mindepth 1 -print -quit)" ]]\n'
        '[[ ! -e "$storage_conf" && ! -e "$local_tls" && ! -e "$inspect_file" ]]\n'
        "[[ $private_root_fd == -1 && $storage_conf_fd == -1 && $local_tls_fd == -1 && $inspect_fd == -1 ]]\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "probe-retain", str(tmp_path), str(HERE / "scrub_private_tree.py")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("directory_name", ["graphroot", "runroot"])
def test_probe_scrubs_moved_podman_directory_by_fd_and_preserves_replacement(
    tmp_path: Path, directory_name: str
) -> None:
    script = (
        "set -euo pipefail\n"
        "GATE_EXPECTED_UID=$(id -u)\n"
        "original=$1/$2\nmoved=$1/moved-$2\nreplacement=$1/$2\n"
        'mkdir -m 700 -- "$original"\nmkdir "$original/nested"\nprintf secret > "$original/nested/private"\n'
        'exec {held_fd}<"$original"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$3"\ncleanup_deadline=$((SECONDS + 30))\n'
        + _probe_directory_scrubber()
        + '\nmv "$original" "$moved"\nmkdir -m 700 -- "$replacement"\nprintf keep > "$replacement/sentinel"\n'
        'manifest=$(preflight_anchored_directory "$anchor" "$identity")\n'
        'scrub_anchored_directory "$held_fd" "$anchor" "$identity" "$manifest"\n'
        '[[ -z "$(find "$moved" -mindepth 1 ! -type d -print -quit)" ]]\n'
        '[[ $(<"$replacement/sentinel") == keep ]]\nexec {held_fd}<&-\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "anchor-test",
            str(tmp_path),
            directory_name,
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_probe_preflight_rejects_hardlinks_and_specials_before_mutation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.write_text("secret")
    outside = tmp_path / "outside"
    os.link(private, outside)
    os.mkfifo(root / "fifo", mode=0o600)
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nroot=$1\n"
        'exec {held_fd}<"$root"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$2"\ncleanup_deadline=$((SECONDS + 30))\n'
        + _probe_directory_scrubber()
        + '\nset +e; preflight_anchored_directory "$anchor" "$identity" >/dev/null; rc=$?; set -e\n'
        '[[ $rc -ne 0 ]]\n[[ $(<"$root/private") == secret ]]\n'
        '[[ -p "$root/fifo" ]]\nexec {held_fd}<&-\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "preflight-test",
            str(root),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert outside.read_text() == "secret"


def test_probe_manifest_recheck_rejects_swap_before_mutation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.write_text("original-secret")
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\nroot=$1/root\n"
        'exec {held_fd}<"$root"\nanchor=/proc/self/fd/${held_fd}/.\n'
        "identity=$(stat -Lc '%d:%i:%a:%u' \"$anchor\")\n"
        + _probe_directory_scrubber()
        + '\nmanifest=$(preflight_anchored_directory "$anchor" "$identity")\n'
        'mv "$root/private" "$1/moved"\nprintf replacement > "$root/private"\n'
        'set +e; scrub_anchored_directory "$held_fd" "$anchor" "$identity" "$manifest"; rc=$?; set -e\n'
        '[[ $rc -ne 0 && $(<"$root/private") == replacement && $(<"$1/moved") == original-secret ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "manifest-swap",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_mount_table_check_rejects_exact_mountpoint() -> None:
    script = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        + _probe_directory_scrubber()
        + "\nset +e; mount_free_anchored_tree /proc; rc=$?; set -e\n[[ $rc -ne 0 ]]\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "mount-test"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_global_preflight_rejects_one_bad_tree_before_mutating_any_target(tmp_path: Path) -> None:
    script = (
        "set -euo pipefail\nshopt -u varredir_close\nGATE_EXPECTED_UID=$(id -u)\n"
        'private_root=$1/root\nmkdir -m 700 -- "$private_root"\n'
        'exec {private_root_fd}<"$private_root"\nprivate_root_anchor=/proc/self/fd/${private_root_fd}/.\n'
        "private_root_identity=$(stat -Lc '%d:%i:%a:%u' \"$private_root_anchor\")\n"
        "private_root_anchor_trusted=1\ncleanup_complete=0\ncleanup_outcome=sensitive_residue\n"
        "cleanup_root_drift=0\ncleanup_running=0\ncleanup_in_progress=0\ncleanup_exit_running=0\n"
        "cleanup_retry_limit=3\ncleanup_deadline=$((SECONDS + 30))\npending_signal=\npending_signal_status=130\n"
        "cleanup_checkpoint() { :; }\nprivate_runtime_armed=1\n"
        "podman_guard_fd=-1\npodman_guard_alias=\npodman_guard_alias_anchor=\npodman_guard_alias_identity=\npodman_guard_alias_clean=0\n"
        'scrubber_fd=-1\nexec {scrubber_fd}<"$2"\n'
        "private_dir_paths=()\nprivate_dir_fds=()\nprivate_dir_anchors=()\n"
        "private_dir_identities=()\nprivate_dir_manifests=()\n"
        "for name in graphroot xdg-runtime xdg-config xdg-data home tmp; do\n"
        ' path="$private_root/$name"; mkdir -m 700 -- "$path"; printf secret > "$path/private"\n'
        ' exec {held}<"$path"; private_dir_paths+=("$path"); private_dir_fds+=("$held")\n'
        ' private_dir_anchors+=("/proc/self/fd/${held}/.")\n'
        " private_dir_identities+=(\"$(stat -Lc '%d:%i:%a:%u' /proc/self/fd/${held}/.)\")\n"
        " unset held\ndone\n"
        'xdg_runtime=$private_root/xdg-runtime\nrunroot=$xdg_runtime/containers\nmkdir -m 700 -- "$runroot"\n'
        'printf secret > "$runroot/private"\nrunroot_anchor=${private_dir_anchors[1]}/containers\n'
        "runroot_identity=$(stat -Lc '%d:%i:%a:%u' \"$runroot_anchor\")\n"
        "storage_conf=$private_root/storage.conf; local_tls=$private_root/tls-combined.pem; inspect_file=$private_root/inspect\n"
        'printf config > "$storage_conf"; printf tls-secret > "$local_tls"; printf inspect > "$inspect_file"\n'
        'chmod 600 "$storage_conf" "$local_tls" "$inspect_file"\n'
        'exec {storage_conf_fd}<>"$storage_conf" {local_tls_fd}<>"$local_tls" {inspect_fd}<>"$inspect_file"\n'
        "storage_conf_identity=$(stat -Lc '%d:%i' /proc/self/fd/$storage_conf_fd)\n"
        "local_tls_identity=$(stat -Lc '%d:%i' /proc/self/fd/$local_tls_fd)\n"
        "inspect_identity=$(stat -Lc '%d:%i' /proc/self/fd/$inspect_fd)\n"
        "storage_conf_clean=0\nlocal_tls_clean=0\ninspect_clean=0\nprivate_tmp=$private_root/tmp\n"
        + _probe_cleanup_functions()
        + '\nmkfifo "$private_root/tmp/reject-fifo"\n'
        "set +e; scrub_private_contents; rc=$?; set -e\n"
        '[[ $rc -ne 0 && $(<"$private_root/graphroot/private") == secret ]]\n'
        '[[ $(<"$local_tls") == tls-secret && -p "$private_root/tmp/reject-fifo" ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "global-preflight",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


PROBE_CLEANUP_CHECKPOINTS = [
    "probe_before_cleanup_running",
    "probe_cleanup_running",
    "probe_before_attempt",
    "probe_before_in_progress",
    "probe_in_progress",
    "probe_scrub_start",
    "probe_after_global_root_preflight",
    "probe_after_directory_preflight",
    "probe_after_exact_preflight",
    "probe_before_guard_alias_removal",
    "probe_after_guard_alias_removal",
    "probe_before_directory_scrub",
    "probe_after_directory_scrub",
    "probe_before_storage.conf_scrub",
    "probe_after_storage.conf_scrub",
    "probe_before_tls-combined.pem_scrub",
    "probe_after_tls-combined.pem_scrub",
    "probe_before_inspect_scrub",
    "probe_after_inspect_scrub",
    "probe_before_postflight",
    "probe_after_postflight",
    "probe_after_scrub",
    "probe_before_fd_close",
    "probe_after_fd_close",
    "probe_before_complete",
    "probe_after_complete",
    "probe_before_in_progress_clear",
    "probe_after_in_progress",
    "probe_after_attempt",
    "probe_before_cleanup_running_clear",
    "probe_after_cleanup_running",
]


@pytest.mark.parametrize(("signal_name", "status"), [("HUP", 129), ("INT", 130), ("TERM", 143)])
@pytest.mark.parametrize("checkpoint", PROBE_CLEANUP_CHECKPOINTS)
def test_probe_cleanup_defers_signal_at_every_checkpoint(
    tmp_path: Path, checkpoint: str, signal_name: str, status: int
) -> None:
    script = (
        _probe_cleanup_setup()
        + _probe_cleanup_functions()
        + "\ninjected=0; target=$3; signal_name=$4\n"
        + 'remember_signal() { pending_signal=$1; case "$1" in HUP) pending_signal_status=129;; INT) pending_signal_status=130;; TERM) pending_signal_status=143;; esac; }\n'
        + 'handle_test_signal() { remember_signal "$1"; if (( cleanup_running || cleanup_in_progress || cleanup_exit_running )); then return; fi; exit "$pending_signal_status"; }\n'
        + 'cleanup_checkpoint() { if (( injected == 0 )) && [[ $1 == "$target" ]]; then injected=1; kill -"$signal_name" "$$"; fi; }\n'
        + "trap exit_cleanup EXIT\n"
        + "trap 'handle_test_signal HUP' HUP; trap 'handle_test_signal INT' INT; trap 'handle_test_signal TERM' TERM\n"
        + "cleanup_private_tree\n"
        + '[[ -z "$pending_signal" ]] || exit "$pending_signal_status"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "probe-cleanup-signal",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
            checkpoint,
            signal_name,
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == status, (checkpoint, signal_name, result.stderr.decode())
    assert result.stdout == b""
    assert result.stderr == b"gate_cleanup=retained_empty\n"
    root = tmp_path / "root"
    assert root.is_dir()
    assert not any(path.is_file() for path in root.rglob("*"))


def test_probe_cleanup_retries_after_interrupted_scrub(tmp_path: Path) -> None:
    functions = _probe_cleanup_functions().replace("scrub_private_contents() {", "real_scrub_private_contents() {", 1)
    script = (
        _probe_cleanup_setup()
        + functions
        + "\nscrub_calls=0\ncleanup_checkpoint() { :; }\n"
        + "remember_signal() { pending_signal=$1; pending_signal_status=143; }\n"
        + "handle_test_signal() { remember_signal TERM; return; }\n"
        + 'scrub_private_contents() { scrub_calls=$((scrub_calls + 1)); if (( scrub_calls == 1 )); then chmod 600 "$local_tls"; truncate -s 0 "$local_tls"; kill -TERM "$$"; return 1; fi; real_scrub_private_contents; }\n'
        + "trap exit_cleanup EXIT; trap handle_test_signal TERM\n"
        + 'cleanup_private_tree; [[ $scrub_calls == 2 ]]; [[ -z "$pending_signal" ]] || exit "$pending_signal_status"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "probe-cleanup-retry",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 143, result.stderr.decode()
    assert (tmp_path / "root").is_dir()
    assert not any(path.is_file() for path in (tmp_path / "root").rglob("*"))


def test_probe_cleanup_signal_during_child_wait_still_reaps_and_scrubs(tmp_path: Path) -> None:
    functions = _probe_cleanup_functions().replace(
        "scrub_anchored_directory() {", "real_scrub_anchored_directory() {", 1
    )
    script = (
        _probe_cleanup_setup()
        + functions
        + "\ncleanup_checkpoint() { :; }\n"
        + "remember_signal() { pending_signal=$1; pending_signal_status=143; }\n"
        + "handle_test_signal() { remember_signal TERM; return; }\n"
        + 'scrub_anchored_directory() { /usr/bin/sleep 0.2; real_scrub_anchored_directory "$@"; }\n'
        + "trap exit_cleanup EXIT; trap handle_test_signal TERM\n"
        + '( /usr/bin/sleep 0.05; /usr/bin/kill -TERM "$$" ) &\n'
        + "cleanup_private_tree\n"
        + '[[ -z "$pending_signal" ]] || exit "$pending_signal_status"\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "probe-child-wait-signal",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 143, result.stderr.decode()
    assert result.stdout == b""
    assert result.stderr == b"gate_cleanup=retained_empty\n"
    assert (tmp_path / "root").is_dir()
    assert not any(path.is_file() for path in (tmp_path / "root").rglob("*"))


def test_probe_root_replacement_is_preserved_after_original_is_scrubbed(tmp_path: Path) -> None:
    script = (
        _probe_cleanup_setup()
        + _probe_cleanup_functions()
        + "\ncleanup_checkpoint() { :; }\n"
        + 'moved=$1/moved; mv "$private_root" "$moved"; mkdir -m 700 -- "$private_root"; printf keep > "$private_root/replacement"\n'
        + "set +e; cleanup_private_tree; rc=$?; set -e\n"
        + "[[ $rc -ne 0 && $cleanup_complete == 0 && $cleanup_outcome == retained_drift ]]\n"
        + '[[ $(<"$private_root/replacement") == keep ]]\n'
        + '[[ -z "$(find "$moved" -mindepth 1 ! -type d -print -quit)" ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "probe-root-replacement",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_probe_tls_replacement_is_preserved_and_original_fd_scrubbed(tmp_path: Path) -> None:
    script = (
        _probe_cleanup_setup()
        + _probe_cleanup_functions()
        + "\ncleanup_checkpoint() { :; }\n"
        + 'moved=$1/moved-tls; mv "$local_tls" "$moved"; printf keep > "$local_tls"\n'
        + "set +e; cleanup_private_tree; rc=$?; set -e\n"
        + "[[ $rc -ne 0 && $cleanup_complete == 0 && $cleanup_outcome == retained_drift ]]\n"
        + '[[ $(<"$local_tls") == keep && $(stat -c %s "$moved") == 0 ]]\n'
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            script,
            "probe-tls-replacement",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_cleanup_retains_roots_and_binds_every_podman_directory() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    assert "/usr/bin/rmdir" not in batch and "/usr/bin/rmdir" not in probe
    assert "/usr/bin/rm -r" not in batch and "/usr/bin/rm -r" not in probe
    assert "remove_batch_root" in batch and "retain_private_root" in probe
    assert 'private_dir_paths=("$graphroot" "$xdg_runtime"' in probe
    assert "private_dirs_bound || blocked" in probe
    assert probe.count("private_dirs_bound || blocked") >= 10
    assert 'exec {auth_fd}<>"$auth_path"' in probe
    assert '/usr/bin/truncate -s 0 -- "/proc/self/fd/$auth_fd"' in probe
    assert "done < /proc/self/mountinfo" in batch
    assert "done < /proc/self/mountinfo" in probe
    storage_block = probe[probe.index("readonly graphroot=") :]
    assert 'graphroot = "%s"' in storage_block and 'runroot = "%s"' in storage_block
    assert 'rootless_storage_path = "%s"' in storage_block
    assert '"$graphroot" "$runroot" "$graphroot" > "$storage_conf"' in storage_block
    assert "readonly runroot=$xdg_runtime/containers" in storage_block
    assert 'private_dir_paths=("$graphroot" "$xdg_runtime"' in storage_block
    assert 'private_dir_paths=("$graphroot" "$runroot"' not in storage_block
    assert "unset STORAGE_DRIVER STORAGE_OPTS" in probe
    assert (
        "/proc/self/fd"
        not in storage_block[
            storage_block.index("/usr/bin/printf '[storage]") : storage_block.index(
                '/usr/bin/chmod 600 "$storage_conf"'
            )
        ]
    )


def test_podman_preflight_has_distinct_sanitized_leaves() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    preflight = probe[probe.index("store=$(/usr/bin/timeout") : probe.index("# Source only the reviewed")]
    for category in (
        "podman_info_command",
        "podman_info_shape",
        "podman_store_graphroot",
        "podman_store_runroot",
        "podman_store_driver",
        "podman_info_image_present",
        "podman_info_image_check",
    ):
        assert f"blocked {category}" in preflight
        assert category in controller.ALLOWED_PUBLIC_CATEGORIES
    assert "blocked podman_info\n" not in preflight
    assert "observed_graphroot" in preflight
    assert "observed_runroot" in preflight
    assert "observed_driver" in preflight


def test_offline_lookup_and_one_pull_use_exact_guard_descriptor() -> None:
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    assert controller.WORKER.exists()
    assert controller.SOURCE_FILES[controller.WORKER] == hashlib.sha256(controller.WORKER.read_bytes()).hexdigest()
    assert '/usr/bin/ln -s -- "/proc/self/fd/$podman_guard_fd" "$podman_guard_alias"' in probe
    assert "export PATH=$private_tmp:/usr/bin:/bin" in probe
    assert "GATE_PODMAN_GUARD_IDENTITY" in probe
    for value in (
        "GATE_EXPECTED_GRAPHROOT",
        "GATE_EXPECTED_RUNROOT",
        "GATE_EXPECTED_RUNROOT_ANCHOR",
        "GATE_EXPECTED_RUNROOT_IDENTITY",
        "GATE_EXPECTED_XDG_RUNTIME",
        "GATE_EXPECTED_XDG_DATA",
        "GATE_EXPECTED_STORAGE_CONF",
        "GATE_EXPECTED_STORAGE_CONF_IDENTITY",
        "GATE_EXPECTED_STORAGE_CONF_SHA256",
        "GATE_EXPECTED_AUTH_IDENTITY",
        "GATE_EXPECTED_AUTH_SHA256",
        "GATE_EXPECTED_IMAGE",
        "GATE_WRITER_STATE_FD",
        "GATE_WRITER_STATE_IDENTITY",
    ):
        assert value in probe
        assert value in guard
    call = '/usr/bin/podman "$@"'
    assert guard.count(call) == 1
    call_at = guard.index(call)
    assert (
        guard.rfind(
            "private_dirs_bound && auth_path_bound && writer_is_quiesced || guard_fail precondition",
            0,
            call_at,
        )
        >= 0
    )
    assert guard.index("private_dirs_bound && auth_path_bound || guard_fail postcondition", call_at) > call_at
    assert "valid_registry_call=0" in guard
    assert '[[ $# == 5 && "$1" == login' in guard
    assert '[[ $# == 8 && "$1" == pull' in guard
    assert '--platform && "$5" == linux/arm64' in guard
    assert '"$6" == --tls-verify=true && "$7" == --quiet' in guard
    assert "--password-stdin" not in guard


def _run_exact_guard_lookup(
    tmp_path: Path,
    drift: tuple[str, str] | None = None,
    argv_variant: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if os.getuid() != controller.OWNER_UID:
        pytest.skip("the frozen guard intentionally binds the production uid")
    source_guard = HERE / "podman_guard.sh"
    guard = tmp_path / "podman_guard.sh"
    guard.write_bytes(source_guard.read_bytes())
    guard.chmod(0o500)
    private_root = tmp_path / "root"
    private_root.mkdir(mode=0o700)
    directories = []
    for name in ("graphroot", "xdg-runtime", "xdg-config", "xdg-data", "home", "tmp"):
        path = private_root / name
        path.mkdir(mode=0o700)
        directories.append(path)
    runroot = directories[1] / "containers"
    runroot.mkdir(mode=0o700)
    storage_conf = private_root / "storage.conf"
    storage_conf.write_text(
        '[storage]\ndriver = "overlay"\n'
        f'graphroot = "{directories[0]}"\nrunroot = "{runroot}"\n'
        f'rootless_storage_path = "{directories[0]}"\n'
    )
    storage_conf.chmod(0o600)
    auth_file = directories[1] / "serve-api-v2-registry-auth.test"
    auth_file.write_text('{"auths":{"123456789012.dkr.ecr.us-east-2.amazonaws.com":{"auth":"QVdTOnRlc3Q="}}}\n')
    auth_file.chmod(0o600)
    writer_state = private_root / "writer-state"
    writer_state.write_text("gate_writer_state=quiesced\n")
    writer_state.chmod(0o600)
    registry_host = "123456789012.dkr.ecr.us-east-2.amazonaws.com"
    expected_image = f"{registry_host}/repository:tag@sha256:{'a' * 64}"

    guard_fd = os.open(guard, os.O_RDONLY)
    root_fd = os.open(private_root, os.O_RDONLY | os.O_DIRECTORY)
    writer_state_fd = os.open(writer_state, os.O_RDWR)
    directory_fds = [os.open(path, os.O_RDONLY | os.O_DIRECTORY) for path in directories]
    alias = directories[-1] / "podman"
    alias.symlink_to(f"/proc/self/fd/{guard_fd}")
    try:
        root_info = os.fstat(root_fd)
        guard_info = os.fstat(guard_fd)
        runroot_info = runroot.stat()
        storage_info = storage_conf.stat()
        auth_info = auth_file.stat()
        writer_state_info = writer_state.stat()
        env = {
            "HOME": str(directories[-2]),
            "PATH": f"{directories[-1]}:/usr/bin:/bin",
            "TMPDIR": str(directories[-1]),
            "XDG_RUNTIME_DIR": str(directories[1]),
            "XDG_CONFIG_HOME": str(directories[2]),
            "XDG_DATA_HOME": str(directories[3]),
            "CONTAINERS_STORAGE_CONF": str(storage_conf),
            "GATE_EXPECTED_UID": str(controller.OWNER_UID),
            "GATE_PRIVATE_ROOT_PATH": str(private_root),
            "GATE_PRIVATE_ROOT_ANCHOR": f"/proc/self/fd/{root_fd}/.",
            "GATE_PRIVATE_ROOT_IDENTITY": (
                f"{root_info.st_dev}:{root_info.st_ino}:{stat.S_IMODE(root_info.st_mode):o}:{root_info.st_uid}"
            ),
            "GATE_PODMAN_GUARD_FD": str(guard_fd),
            "GATE_PODMAN_GUARD_IDENTITY": (
                f"{guard_info.st_dev}:{guard_info.st_ino}:{stat.S_IMODE(guard_info.st_mode):o}:"
                f"{guard_info.st_uid}:{guard_info.st_nlink}"
            ),
            "GATE_PODMAN_GUARD_SHA256": hashlib.sha256(guard.read_bytes()).hexdigest(),
            "GATE_PODMAN_GUARD_ALIAS": str(alias),
            "GATE_EXPECTED_GRAPHROOT": str(directories[0]),
            "GATE_EXPECTED_RUNROOT": str(runroot),
            "GATE_EXPECTED_RUNROOT_ANCHOR": f"/proc/self/fd/{directory_fds[1]}/./containers",
            "GATE_EXPECTED_RUNROOT_IDENTITY": (
                f"{runroot_info.st_dev}:{runroot_info.st_ino}:{stat.S_IMODE(runroot_info.st_mode):o}:"
                f"{runroot_info.st_uid}"
            ),
            "GATE_EXPECTED_XDG_RUNTIME": str(directories[1]),
            "GATE_EXPECTED_XDG_DATA": str(directories[3]),
            "GATE_EXPECTED_STORAGE_CONF": str(storage_conf),
            "GATE_EXPECTED_STORAGE_CONF_IDENTITY": f"{storage_info.st_dev}:{storage_info.st_ino}",
            "GATE_EXPECTED_STORAGE_CONF_SHA256": hashlib.sha256(storage_conf.read_bytes()).hexdigest(),
            "GATE_EXPECTED_AUTH_PATH": str(auth_file),
            "GATE_EXPECTED_REGISTRY_HOST": registry_host,
            "GATE_EXPECTED_AUTH_IDENTITY": (
                f"{auth_info.st_dev}:{auth_info.st_ino}:{stat.S_IMODE(auth_info.st_mode):o}:"
                f"{auth_info.st_uid}:{auth_info.st_nlink}"
            ),
            "GATE_EXPECTED_AUTH_SHA256": hashlib.sha256(auth_file.read_bytes()).hexdigest(),
            "GATE_WRITER_STATE_FD": str(writer_state_fd),
            "GATE_WRITER_STATE_IDENTITY": (
                f"{writer_state_info.st_dev}:{writer_state_info.st_ino}:"
                f"{stat.S_IMODE(writer_state_info.st_mode):o}:{writer_state_info.st_uid}:"
                f"{writer_state_info.st_nlink}"
            ),
            "GATE_EXPECTED_IMAGE": expected_image,
            "GATE_IMAGE": expected_image,
            "REGISTRY_AUTH_FILE": str(auth_file),
        }
        for index, (path, fd) in enumerate(zip(directories, directory_fds, strict=True)):
            info = os.fstat(fd)
            env[f"GATE_PRIVATE_PATH_{index}"] = str(path)
            env[f"GATE_PRIVATE_ANCHOR_{index}"] = f"/proc/self/fd/{fd}/."
            env[f"GATE_PRIVATE_IDENTITY_{index}"] = (
                f"{info.st_dev}:{info.st_ino}:{stat.S_IMODE(info.st_mode):o}:{info.st_uid}"
            )
        if drift is not None:
            env[drift[0]] = drift[1]
        guard_args = ["login", "--authfile", str(auth_file), "--get-login", registry_host]
        if argv_variant == "login_extra":
            guard_args.append("extra")
        elif argv_variant == "login_reordered":
            guard_args = ["login", "--get-login", registry_host, "--authfile", str(auth_file)]
        elif argv_variant == "network_login":
            guard_args = ["login", "--authfile", str(auth_file), "--username", "AWS", "--password-stdin", registry_host]
        elif argv_variant == "pull_missing_tls":
            guard_args = ["pull", "--authfile", str(auth_file), "--platform", "linux/arm64", "--quiet", expected_image]
        elif argv_variant == "pull_extra":
            guard_args = [
                "pull",
                "--authfile",
                str(auth_file),
                "--platform",
                "linux/arm64",
                "--tls-verify=true",
                "--quiet",
                expected_image,
                "extra",
            ]
        elif argv_variant == "pull_wrong_image":
            guard_args = [
                "pull",
                "--authfile",
                str(auth_file),
                "--platform",
                "linux/arm64",
                "--tls-verify=true",
                "--quiet",
                expected_image.replace("repository", "wrong"),
            ]
        result = subprocess.run(
            ["/usr/bin/timeout", "2s", str(alias), *guard_args],
            env=env,
            pass_fds=(guard_fd, root_fd, writer_state_fd, *directory_fds),
            check=False,
            capture_output=True,
        )
    finally:
        for fd in directory_fds:
            os.close(fd)
        os.close(writer_state_fd)
        os.close(root_fd)
        os.close(guard_fd)
    return result


def test_exact_guard_fd_executes_and_validates_around_offline_lookup(tmp_path: Path) -> None:
    result = _run_exact_guard_lookup(tmp_path)
    assert result.returncode == 0
    assert result.stdout == b"AWS\n"


@pytest.mark.parametrize(
    "variant",
    ["login_extra", "login_reordered", "network_login", "pull_missing_tls", "pull_extra", "pull_wrong_image"],
)
def test_exact_guard_rejects_every_unapproved_argv_shape(tmp_path: Path, variant: str) -> None:
    result = _run_exact_guard_lookup(tmp_path, argv_variant=variant)
    assert result.returncode == 125
    assert result.stdout == b""
    assert b"gate_guard_stage=precondition" in result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STORAGE_DRIVER", "vfs"),
        ("STORAGE_OPTS", "ignore_chown_errors=true"),
        ("XDG_RUNTIME_DIR", "/tmp/wrong-runtime"),
        ("CONTAINERS_STORAGE_CONF", "/tmp/wrong-storage.conf"),
        ("GATE_EXPECTED_RUNROOT", "/tmp/wrong-runroot"),
        ("GATE_EXPECTED_AUTH_IDENTITY", "0:0:600:656177:1"),
        ("GATE_EXPECTED_AUTH_SHA256", "0" * 64),
    ],
)
def test_exact_guard_rejects_storage_environment_drift(tmp_path: Path, name: str, value: str) -> None:
    result = _run_exact_guard_lookup(tmp_path, (name, value))
    assert result.returncode == 125


def test_guard_signal_ladder_kills_and_reaps_term_ignoring_child() -> None:
    guard = (HERE / "podman_guard.sh").read_text()
    stop_function = guard[guard.index("process_identity()") : guard.index("trap 'forward_signal 129'")]
    shell = (
        "set -euo pipefail\nGATE_EXPECTED_UID=$(id -u)\n"
        + stop_function
        + "\n/usr/bin/bash -c 'trap \"\" TERM; exec /usr/bin/sleep 30' &\n"
        "child=$!\n"
        "/usr/bin/sleep 0.2\n"
        'identity=$(process_identity "$child")\n'
        'stop_and_reap_child "$child" "$identity"\n'
        '[[ ! -e "/proc/$child" ]]\n'
    )
    started = time.monotonic()
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "guard-signal-test"],
        check=False,
        capture_output=True,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr.decode()
    assert 1.5 <= elapsed < 4.0


def test_probe_preflight_checks_device_owner_type_and_links() -> None:
    scrub = _probe_directory_scrubber()
    assert "'%D:%i:%U:%y:%n:%p\\n'" in scrub
    assert '"$dev" == "$root_dev"' in scrub
    assert '"$uid" == "${GATE_EXPECTED_UID}"' in scrub
    assert 'f) [[ "$links" == 1 ]]' in scrub
    assert "l)" in scrub and '"$links" == 1' in scrub
    assert "*) return 1" in scrub
    assert "done < /proc/self/mountinfo" in scrub


def test_signal_grace_exceeds_anchored_cleanup_bound() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    probe = (HERE / "probe_registry_gate.sh").read_text()
    guard = (HERE / "podman_guard.sh").read_text()
    assert "child_term_deadline=$((teardown_deadline - 50))" in batch
    assert "child_kill_deadline=$((teardown_deadline - 45))" in batch
    assert "while (( SECONDS < child_term_deadline ))" in batch
    assert "while (( SECONDS < child_kill_deadline ))" in batch
    assert "--kill-after=150s 1560s" in batch
    assert "spawning || cleanup_running || cleanup_in_progress" in batch
    assert "spawn_group_ready=0" in batch
    assert batch.count('wait "$active_pid"') == 2
    assert "--kill-after=3s 12s" in probe
    assert '--kill-after=5s "${timeout_seconds}s"' in probe
    assert "--kill-after=1s 3s" in probe
    assert "/usr/bin/rm -r" not in batch
    assert "/usr/bin/rm -r" not in probe
    assert "/usr/bin/chmod -R" not in batch
    assert "/usr/bin/chmod -R" not in probe
    assert controller.PROBE_CLEANUP_BOUND_SECONDS < controller.OUTER_KILL_GRACE_SECONDS
    assert controller.OUTER_KILL_GRACE_SECONDS < controller.PARENT_TERM_GRACE_SECONDS
    assert controller.SIGNAL_TEARDOWN_BOUND_SECONDS < controller.SIGNAL_LEAD_SECONDS
    assert controller.SIGNAL_TEARDOWN_BOUND_SECONDS == 210
    assert '/usr/bin/timeout --signal=TERM --kill-after=1s "${duration}s"' in batch
    assert '/usr/bin/timeout --signal=TERM --kill-after=1s "${timeout_seconds}s"' in batch
    assert "/usr/bin/sleep 2" in guard
    assert '/usr/bin/kill -KILL -- "$child"' in guard
    assert 'wait "$child" 2>/dev/null' in guard


def test_batch_signal_arms_shared_deadline_before_every_lifecycle_branch() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    early = batch[batch.index("early_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("early_signal()"))]
    assert handler.index('remember_signal "$name"') < handler.index("arm_teardown_deadline")
    assert handler.index("arm_teardown_deadline") < handler.index("if (( publication_started")
    assert handler.index("arm_teardown_deadline") < handler.index("stop_child")
    assert early.index('remember_signal "$1"') < early.index("arm_teardown_deadline")
    assert early.index("arm_teardown_deadline") < early.index("if (( publication_started")


@pytest.mark.parametrize(
    ("state_setup", "expected_action"),
    [
        ("spawning=1", "deferred"),
        ("active_pid=", "cleanup"),
        ("cleanup_running=1", "deferred"),
        ("publication_started=1; publication_in_progress=1", "deferred"),
    ],
)
def test_batch_signal_lifecycle_states_share_deadline(state_setup: str, expected_action: str) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=8; publication_reserve_seconds=2; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1\n"
        "spawning=0; cleanup_running=0; cleanup_in_progress=0; cleanup_exit_running=0; signal_handling=0\n"
        "pending_signal=; pending_signal_status=130; active_pid=; action=none\n"
        + deadline
        + signal
        + stop
        + handler
        + "\ncleanup_private_tree() { action=cleanup; [[ $teardown_deadline -gt 0 && $cleanup_deadline -eq $((teardown_deadline - publication_reserve_seconds)) ]]; }\n"
        + "finish_publication() { action=published; return 0; }\n"
        + state_setup
        + "\nstart=$SECONDS; handle_signal TERM\n"
        + "[[ $pending_signal == TERM && $teardown_deadline -eq $((start + teardown_budget_seconds)) ]]\n"
        + "[[ $cleanup_deadline -eq $((teardown_deadline - publication_reserve_seconds)) ]]\n"
        + f"[[ $action == {'published' if expected_action == 'cleanup' else 'none'} ]]\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "signal-state"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_pre_spawn_signal_budget_is_not_rearmed_after_elapsed_time() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=4; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1\n"
        "spawning=1; cleanup_running=0; cleanup_in_progress=0; cleanup_exit_running=0; signal_handling=0\n"
        "pending_signal=; pending_signal_status=130; active_pid=; observed_deadline=0; observed_remaining=99\n"
        + deadline
        + signal
        + stop
        + handler
        + "\ncleanup_private_tree() { observed_deadline=$teardown_deadline; observed_remaining=$((teardown_deadline - SECONDS)); return 0; }\n"
        + "finish_publication() { return 0; }\n"
        + "handle_signal TERM\noriginal=$teardown_deadline\n/usr/bin/sleep 2\nspawning=0\nhandle_signal TERM\n"
        + "[[ $teardown_deadline -eq $original && $observed_deadline -eq $original && $observed_remaining -le 2 ]]\n"
    )
    started = time.monotonic()
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "signal-budget"], capture_output=True, timeout=5)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr.decode()
    assert elapsed < 3.5


def test_batch_post_wait_empty_pid_cleanup_uses_signal_deadline() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=4; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1\n"
        "spawning=0; cleanup_running=0; cleanup_in_progress=0; cleanup_exit_running=0; signal_handling=0\n"
        "pending_signal=; pending_signal_status=130; active_pid=; cleanup_started=0; publication_remaining=99\n"
        + deadline
        + signal
        + stop
        + handler
        + "\ncleanup_private_tree() { cleanup_started=$SECONDS; /usr/bin/sleep 2; return 0; }\n"
        + "finish_publication() { publication_remaining=$((teardown_deadline - SECONDS)); return 0; }\n"
        + "start=$SECONDS; handle_signal TERM\n"
        + "[[ $cleanup_started -ge $start && $teardown_deadline -eq $((start + teardown_budget_seconds)) ]]\n"
        + "[[ $publication_remaining -ge 1 && $publication_remaining -le 2 ]]\n"
    )
    started = time.monotonic()
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "post-wait-signal"], capture_output=True, timeout=5)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr.decode()
    assert 1.5 <= elapsed < 3.5


def test_batch_cleanup_in_progress_signal_keeps_original_deadline_after_defer() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=4; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=$((SECONDS + 90))\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1\n"
        "spawning=0; cleanup_running=1; cleanup_in_progress=1; cleanup_exit_running=0; signal_handling=0\n"
        "pending_signal=; pending_signal_status=130; active_pid=; publication_remaining=99\n"
        + deadline
        + signal
        + stop
        + handler
        + "\ncleanup_private_tree() { [[ $cleanup_deadline -eq $((teardown_deadline - publication_reserve_seconds)) ]]; return 0; }\n"
        + "finish_publication() { publication_remaining=$((teardown_deadline - SECONDS)); return 0; }\n"
        + "start=$SECONDS; handle_signal TERM\noriginal=$teardown_deadline\n/usr/bin/sleep 2\n"
        + "cleanup_running=0; cleanup_in_progress=0; handle_signal TERM\n"
        + "[[ $teardown_deadline -eq $original && $original -eq $((start + teardown_budget_seconds)) ]]\n"
        + "[[ $publication_remaining -ge 1 && $publication_remaining -le 2 ]]\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "cleanup-signal"], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_publication_after_signal_consumes_only_remaining_total_budget(tmp_path: Path) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    publication = batch[batch.index("arm_teardown_deadline()") : batch.index("block()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=4; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "spawning=0; cleanup_running=0; cleanup_in_progress=0; cleanup_exit_running=0; signal_handling=0\n"
        "pending_signal=; pending_signal_status=130; active_pid=; injected=0\n"
        "expected_digest=sha256:synthetic; expected_result=$1/result.json; GATE_JOB_RESULT=$expected_result; SLURM_JOB_ID=1\n"
        + publication
        + signal
        + stop
        + handler
        + "\ncleanup_private_tree() { return 0; }\n"
        + 'publication_checkpoint() { if (( injected == 0 )) && [[ $1 == parent_after_started ]]; then injected=1; kill -TERM "$$"; /usr/bin/sleep 2; fi; }\n'
        + "publication_child_checkpoint() { :; }\n"
        + 'exec 8>"$2"\n'
        + "trap 'handle_signal TERM' TERM\n"
        + "finish_publication success 0\n"
    )
    started = time.monotonic()
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "publication-total-budget", str(tmp_path), str(log_path)],
        capture_output=True,
        timeout=5,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 143, result.stderr.decode()
    assert elapsed < 3.5
    assert log_path.read_bytes() == b""
    assert not (tmp_path / "result.json").exists()


def test_batch_stubborn_writer_latches_cleanup_unproven() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    stop = stop.replace("/usr/bin/kill", "synthetic_kill").replace("/usr/bin/sleep", "synthetic_sleep")
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=3; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "writer_state=live; cleanup_outcome=sensitive_residue; active_pid=999999; active_group_id=999999\n"
        + deadline
        + stop
        + "\nwriter_pid_live() { return 0; }\nwriter_group_live() { return 0; }\n"
        + "signal_writer() { :; }\nsynthetic_sleep() { SECONDS=$((SECONDS + 1)); }\n"
        + "set +e; stop_child; rc=$?; set -e\n"
        + "[[ $rc == 1 && $active_pid == 999999 && $active_group_id == 999999 && $writer_state == unproven ]]\n"
        + "[[ $cleanup_outcome == live_writer_cleanup_unproven ]]\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "stubborn-writer"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("group_lingers", [False, True])
def test_batch_normal_wait_requires_process_group_quiescence(group_lingers: bool) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    stop = batch[batch.index("stop_child()") : batch.index("handle_signal()")]
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=3; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "writer_state=live; cleanup_outcome=sensitive_residue; active_pid=999999; active_group_id=999999\n"
        + deadline
        + stop
        + f"\nwriter_group_live() {{ return {0 if group_lingers else 1}; }}\n"
        + "writer_pid_live() { return 1; }\nsignal_writer() { :; }\n"
        + "set +e; finish_reaped_writer; rc=$?; set -e\n"
    )
    if group_lingers:
        script += (
            "[[ $rc == 1 && $writer_state == unproven && -z $active_pid ]]\n"
            "[[ $active_group_id == 999999 && $cleanup_outcome == live_writer_cleanup_unproven ]]\n"
        )
    else:
        script += "[[ $rc == 0 && $writer_state == quiesced && -z $active_pid && -z $active_group_id ]]\n"
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "normal-wait"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_batch_spawn_failure_and_normal_wait_route_unproven_writer_to_distinct_result() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    tail = batch[batch.index("set +e\nspawning=1") :]
    assert "writer_state=spawning" in tail
    assert "active_group_id=$active_pid" in tail
    assert "writer_state=live" in tail
    assert tail.count("finish_publication live_writer_cleanup_unproven 1") == 2
    assert "finish_reaped_writer" in tail


@pytest.mark.parametrize("cleanup_entry", ["scrub_batch_contents", "remove_batch_root", "cleanup_private_tree"])
def test_batch_cleanup_refuses_before_mutation_when_writer_is_live(tmp_path: Path, cleanup_entry: str) -> None:
    script = (
        _batch_fd_setup()
        + _batch_cleanup_functions()
        + "\nactive_writer_live() { return 0; }\nmutation=0\n"
        + "cleanup_checkpoint() { mutation=1; }\n"
        + f"set +e; {cleanup_entry}; rc=$?; set -e\n"
        + "[[ $rc == 1 && $mutation == 0 && $writer_state == unproven ]]\n"
        + "[[ $cleanup_outcome == live_writer_cleanup_unproven ]]\n"
        + '[[ $(<"$stdout") == stdout-secret && $(<"$stderr") == stderr-secret ]]\n'
        + '[[ $(<"$local_tools") == tools && -s "$local_scrubber" ]]\n'
        + "exec {check_stdout}>&- {check_stderr}>&-\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "live-cleanup-guard", str(tmp_path), str(HERE / "scrub_private_tree.py")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize(("signal_name", "status"), [("HUP", 129), ("INT", 130), ("TERM", 143)])
def test_batch_signal_stubborn_writer_publishes_only_truthful_category(
    tmp_path: Path, signal_name: str, status: int
) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    deadline = batch[batch.index("arm_teardown_deadline()") : batch.index("publication_checkpoint()")]
    signal = batch[batch.index("remember_signal()") : batch.index("batch_mount_free()")]
    handler = batch[
        batch.index("handle_signal()") : batch.index("trap exit_cleanup EXIT", batch.index("handle_signal()"))
    ]
    events = tmp_path / "events"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=4; publication_reserve_seconds=1; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; cleanup_running=0; cleanup_in_progress=0\n"
        "cleanup_exit_running=0; signal_handling=0; spawning=0; pending_signal=; pending_signal_status=130\n"
        "writer_state=live; cleanup_outcome=sensitive_residue; active_pid=999999; active_group_id=999999\n"
        + deadline
        + signal
        + handler
        + "\nstop_child() { mark_live_writer_cleanup_unproven; return 1; }\n"
        + 'cleanup_private_tree() { printf "cleanup\\n" >> "$event_path"; return 0; }\n'
        + 'finish_publication() { printf "publish:%s\\n" "$1" >> "$event_path"; exit "$2"; }\n'
        + "export event_path=$1\n"
    )
    script += f"handle_signal {signal_name}\n"
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "signal-live-writer", str(events)], capture_output=True
    )
    assert result.returncode == status, result.stderr.decode()
    assert events.read_text().splitlines() == ["publish:live_writer_cleanup_unproven"]


def test_batch_exit_path_never_scrubs_live_writer_and_publishes_once(tmp_path: Path) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    exit_function = batch[batch.index("exit_cleanup()") : batch.index("early_signal()")]
    events = tmp_path / "events"
    script = (
        "set -euo pipefail\n"
        "writer_state=unproven; cleanup_outcome=live_writer_cleanup_unproven; publication_started=0\n"
        "publication_category=; pending_signal=; pending_signal_status=130; cleanup_exit_running=0; active_pid=999999\n"
        "private_fd=-1; stdout_fd=-1; stderr_fd=-1; local_tools_fd=-1; local_scrubber_fd=-1\n"
        + exit_function
        + '\narm_teardown_deadline() { :; }\ncleanup_private_tree() { printf "cleanup\\n" >> "$event_path"; }\n'
        + 'emit() { publication_started=1; publication_category=$1; printf "publish:%s\\n" "$1" >> "$event_path"; }\n'
        + "export event_path=$1\ntrap exit_cleanup EXIT\nexit 7\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "exit-live-writer", str(events)], capture_output=True)
    assert result.returncode == 7, result.stderr.decode()
    assert events.read_text().splitlines() == ["publish:live_writer_cleanup_unproven"]


def test_batch_exit_from_spawning_clears_state_after_successful_stop(tmp_path: Path) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    exit_function = batch[batch.index("exit_cleanup()") : batch.index("early_signal()")]
    events = tmp_path / "events"
    script = (
        "set -euo pipefail\n"
        "writer_state=spawning; spawning=1; cleanup_outcome=sensitive_residue; publication_started=0\n"
        "publication_category=; pending_signal=; pending_signal_status=130; cleanup_exit_running=0\n"
        "active_pid=999999; active_group_id=999999\n"
        "private_fd=-1; stdout_fd=-1; stderr_fd=-1; local_tools_fd=-1; local_scrubber_fd=-1\n"
        + exit_function
        + "\narm_teardown_deadline() { :; }\n"
        + "mark_writer_quiesced() { active_pid=; active_group_id=; spawning=0; writer_state=quiesced; }\n"
        + "stop_child() { mark_writer_quiesced; }\n"
        + 'cleanup_private_tree() { printf "cleanup:%s:%s\\n" "$writer_state" "$spawning" >> "$event_path"; }\n'
        + 'emit() { printf "publish:%s\\n" "$1" >> "$event_path"; }\n'
        + "export event_path=$1\ntrap exit_cleanup EXIT\nexit 7\n"
    )
    result = subprocess.run(["/usr/bin/bash", "-p", "-c", script, "exit-spawning", str(events)], capture_output=True)
    assert result.returncode == 7, result.stderr.decode()
    assert events.read_text().splitlines() == ["cleanup:quiesced:0"]


def test_batch_live_writer_result_survives_pending_signal_and_is_single(tmp_path: Path) -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    functions = batch[batch.index("arm_teardown_deadline()") : batch.index("block()")]
    result_path = tmp_path / "result.json"
    log_path = tmp_path / "slurm.log"
    script = (
        "set -euo pipefail\n"
        "teardown_budget_seconds=10; publication_reserve_seconds=2; teardown_deadline=0; cleanup_deadline=0\n"
        "publication_started=0; publication_in_progress=0; publication_finished=0; publication_rc=1; publication_category=\n"
        "pending_signal=TERM; pending_signal_status=143; writer_state=unproven; spawning=0; active_pid=999999; active_group_id=999999\n"
        "expected_digest=sha256:synthetic; expected_result=$1; GATE_JOB_RESULT=$1; SLURM_JOB_ID=1\n"
        + functions
        + '\nremember_signal() { :; }\nexec 8>"$2"\n'
        + "finish_publication internal 1\n"
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", script, "live-publication", str(result_path), str(log_path)],
        capture_output=True,
        timeout=12,
    )
    assert result.returncode == 143, result.stderr.decode()
    expected = (
        '{"category":"live_writer_cleanup_unproven","image_digest":"sha256:synthetic",'
        '"kind":"k3-registry-direct-pull-gate-v32","platform":"linux/arm64","state":"blocked"}\n'
    )
    assert result_path.read_text() == expected
    assert log_path.read_text() == expected
    assert len(log_path.read_text().splitlines()) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_controller_live_writer_category_forces_absence_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str | None, str]] = []
    monkeypatch.setattr(controller, "prove_queue_absent", lambda job_id: calls.append((job_id, "absence")))
    assert controller.reconcile_live_writer_terminal("internal", "123", "a" * 24) is False
    assert calls == []
    assert controller.reconcile_live_writer_terminal(controller.LIVE_WRITER_CATEGORY, "123", "a" * 24) is True
    assert calls == [("123", "absence")]


def test_wait_terminal_cancels_once_after_two_matching_live_writer_results(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "12345"
    token = "a" * 24
    terminal = {
        "JobIDRaw": job_id,
        "JobName": controller.JOB_NAME,
        "User": controller.OWNER,
        "State": "CANCELLED",
        "ExitCode": "0:15",
        "Elapsed": "00:00:03",
        "Account": controller.ACCOUNT,
        "QOS": controller.QOS,
        "Partition": controller.PARTITION,
        "ReqTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "AllocTRES": "billing=4,cpu=4,gres/gpu=1,mem=16G,node=1",
        "NNodes": "1",
        "ReqCPUS": "4",
        "TimeLimit": controller.WALLTIME,
        "Comment": f"{controller.COMMENT_PREFIX}{token}",
    }
    records: list[dict[str, str]] = [{"State": "RUNNING"}, {"State": "RUNNING"}, terminal, dict(terminal)]
    projection = ((1,) * 9, (2,) * 9, "f" * 64)
    cancellations: list[tuple[str | None, str]] = []
    clock = [0.0]
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(controller, "accounting", lambda _job_id: records.pop(0))
    monkeypatch.setattr(controller, "live_writer_result_projection", lambda _job_id: projection)
    monkeypatch.setattr(controller, "cancel_exact", lambda target, value: cancellations.append((target, value)))
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    observed = controller.wait_terminal(job_id, token)
    assert observed == terminal
    assert cancellations == [(job_id, token)]


def test_terminal_observation_blocks_live_writer_fast_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = terminal_accounting_record()
    records = [{"State": "RUNNING"}, terminal, dict(terminal)]
    projection = ((1,) * 9, (2,) * 9, "f" * 64)
    cancellations: list[tuple[str | None, str]] = []
    clock = [0.0]
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(controller, "accounting", lambda _job_id: records.pop(0))
    monkeypatch.setattr(controller, "live_writer_result_projection", lambda _job_id: projection)
    monkeypatch.setattr(controller, "cancel_exact", lambda target, value: cancellations.append((target, value)))
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert controller.wait_terminal("12345", "a" * 24) == terminal
    assert cancellations == []
    assert records == []


def test_missing_accounting_root_resets_terminal_stability(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = terminal_accounting_record()
    observations: list[dict[str, str] | None] = [terminal, None, dict(terminal), dict(terminal)]
    clock = [0.0]
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(controller, "accounting", lambda _job_id: observations.pop(0))
    monkeypatch.setattr(controller, "live_writer_result_projection", lambda _job_id: None)
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert controller.wait_terminal("12345", "a" * 24) == terminal
    assert observations == []


def test_wait_terminal_preserves_release_terminal_latch_on_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", True)
    monkeypatch.setattr(controller, "INTERRUPTED", True)
    with pytest.raises(controller.GateInterrupted):
        controller.wait_terminal("12345", "a" * 24)
    assert controller.TERMINAL_ACCOUNTING_OBSERVED is True


def test_accounting_shape_and_encoding_are_typed_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = [
        b"one|short\n",
        b"one|short\ntwo|short\n",
        b"\xff\n",
    ]

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, outputs.pop(0), b"")

    monkeypatch.setattr(controller, "run", fake_run)
    for _ in range(3):
        with pytest.raises(controller.AccountingTransient, match="accounting_shape"):
            controller.accounting("12345")


def _accounting_line(record: dict[str, str]) -> bytes:
    fields = (
        "JobIDRaw",
        "JobName",
        "User",
        "Account",
        "QOS",
        "Partition",
        "State",
        "ExitCode",
        "Elapsed",
        "ReqTRES",
        "AllocTRES",
        "NNodes",
        "ReqCPUS",
        "TimeLimit",
        "Comment",
    )
    return ("|".join(record[field] for field in fields) + "\n").encode()


def test_accounting_ignores_known_steps_and_deduplicates_identical_root_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = terminal_accounting_record()
    step = dict(root, JobIDRaw="12345.batch")
    raw = _accounting_line(root) + _accounting_line(step) + _accounting_line(root)
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    assert controller.accounting("12345") == root


def test_accounting_retries_conflicting_duplicate_root_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    first = terminal_accounting_record()
    second = dict(first, Elapsed="00:00:03")
    raw = _accounting_line(first) + _accounting_line(second)
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    with pytest.raises(controller.AccountingTransient, match="accounting_shape"):
        controller.accounting("12345")


def test_accounting_rejects_unrelated_job_row(monkeypatch: pytest.MonkeyPatch) -> None:
    unrelated = dict(terminal_accounting_record(), JobIDRaw="99999")
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, _accounting_line(unrelated), b""),
    )
    with pytest.raises(controller.GateError, match="accounting_unexpected_job"):
        controller.accounting("12345")


def test_wait_terminal_retries_transient_shapes_and_requires_two_identical_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = terminal_accounting_record()
    changed = dict(terminal, Elapsed="00:00:03")
    partial = dict(terminal, AllocTRES="(null)")
    partial_state = dict(terminal, State="(null)")
    observations: list[object] = [
        controller.AccountingTransient("accounting_shape"),
        None,
        partial_state,
        partial,
        terminal,
        changed,
        changed,
    ]
    cancellations: list[tuple[str | None, str]] = []
    clock = [0.0]
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)

    def fake_accounting(_job_id: str) -> dict[str, str] | None:
        value = observations.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value  # type: ignore[return-value]

    monkeypatch.setattr(controller, "accounting", fake_accounting)
    monkeypatch.setattr(controller, "live_writer_result_projection", lambda _job_id: None)
    monkeypatch.setattr(controller, "cancel_exact", lambda target, token: cancellations.append((target, token)))
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    observed = controller.wait_terminal("12345", "a" * 24)
    assert observed == changed
    assert cancellations == []
    assert observations == []
    assert controller.TERMINAL_ACCOUNTING_OBSERVED is True


def test_terminal_accounting_identity_conflict_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = terminal_accounting_record()
    terminal["User"] = "different-owner"
    monkeypatch.setattr(controller, "TERMINAL_ACCOUNTING_OBSERVED", False)
    monkeypatch.setattr(controller, "accounting", lambda _job_id: terminal)
    monkeypatch.setattr(controller, "live_writer_result_projection", lambda _job_id: None)
    with pytest.raises(controller.GateError, match="accounting_identity"):
        controller.wait_terminal("12345", "a" * 24)
    assert controller.TERMINAL_ACCOUNTING_OBSERVED is False


def test_prove_queue_absent_requires_two_owner_census_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    present = [True, False, False]
    names = [{"12345"}, set(), set()]
    clock = [0.0]
    monkeypatch.setattr(controller, "exact_job_in_owner_queue", lambda _job_id: present.pop(0))
    monkeypatch.setattr(controller, "queue_name_ids", lambda: names.pop(0))
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    controller.prove_queue_absent("12345", timeout=10)
    assert present == []
    assert names == []


def test_owner_queue_census_ignores_unrelated_array_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"99999_7|unrelated-array|tianhaowu\n12345|k3-reg-pull-201500-v32|tianhaowu\n"
    monkeypatch.setattr(
        controller,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw, b""),
    )
    assert controller.exact_job_in_owner_queue("12345") is True


def test_prove_queue_absent_rejects_same_name_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "exact_job_in_owner_queue", lambda _job_id: False)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: {"99999"})
    with pytest.raises(controller.GateError, match="queue_identity_conflict"):
        controller.prove_queue_absent("12345", timeout=1)


def test_cleanup_queue_absence_proof_survives_pending_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(controller, "INTERRUPTED", True)
    monkeypatch.setattr(controller, "exact_job_in_owner_queue", lambda _job_id: False)
    monkeypatch.setattr(controller, "queue_name_ids", lambda: set())
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    controller.prove_queue_absent("12345", timeout=5, interruptible=False)
    assert clock[0] == 1


def test_live_writer_fast_cancel_requires_matching_durable_and_public_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    log_root = tmp_path / "logs"
    run_root.mkdir(mode=0o700)
    log_root.mkdir(mode=0o700)
    monkeypatch.setattr(controller, "RUN_ROOT", run_root)
    monkeypatch.setattr(controller, "LOG_ROOT", log_root)
    payload = controller.canonical(
        {
            "category": controller.LIVE_WRITER_CATEGORY,
            "image_digest": controller.IMAGE_DIGEST,
            "kind": "k3-registry-direct-pull-gate-v32",
            "platform": "linux/arm64",
            "state": "blocked",
        }
    )
    durable = run_root / "job_result.json"
    public = log_root / "slurm-12345.log"
    durable.write_bytes(payload)
    durable.chmod(0o400)
    assert controller.live_writer_result_projection("12345") is None
    public.write_bytes(b"partial")
    public.chmod(0o600)
    assert controller.live_writer_result_projection("12345") is None
    public.write_bytes(payload)
    projection = controller.live_writer_result_projection("12345")
    assert projection is not None and projection[2] == controller.digest(payload)


def test_ordinary_source_result_never_authorizes_fast_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_root = tmp_path / "run"
    log_root = tmp_path / "logs"
    run_root.mkdir(mode=0o700)
    log_root.mkdir(mode=0o700)
    monkeypatch.setattr(controller, "RUN_ROOT", run_root)
    monkeypatch.setattr(controller, "LOG_ROOT", log_root)
    payload = controller.canonical(
        {
            "category": "source_spool_hash",
            "image_digest": controller.IMAGE_DIGEST,
            "kind": "k3-registry-direct-pull-gate-v32",
            "platform": "linux/arm64",
            "state": "blocked",
        }
    )
    for path in (run_root / "job_result.json", log_root / "slurm-12345.log"):
        path.write_bytes(payload)
        path.chmod(0o400 if path.parent == run_root else 0o600)
    assert controller.live_writer_result_projection("12345") is None


def test_controller_proves_live_writer_scheduler_absence_before_final_result() -> None:
    source = (HERE / "controller.py").read_text()
    execute = source[source.index("def execute(") : source.index("def audit(")]
    assert execute.index("wait_terminal(job_id, token)") < execute.index("validate_public_results(job_id, success)")
    assert execute.index("reconcile_live_writer_terminal(category, job_id, token)") < execute.index(
        'publish_exclusive(RUN_ROOT, "result.json", result)'
    )


def test_live_writer_category_is_failure_only() -> None:
    payload = {
        "category": controller.LIVE_WRITER_CATEGORY,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    assert controller.validate_result_payload(captured, False)[1] == controller.LIVE_WRITER_CATEGORY
    with pytest.raises(controller.GateError, match="public_log_success"):
        controller.validate_result_payload(captured, True)


def test_worst_case_signal_timing_is_mathematically_nested() -> None:
    global_root_preflight_bound = 3 + 1
    global_directory_preflight_bound = 12 + 3
    directory_mutation_bound = (12 + 3) + (10 + 3) + (15 + 3) + (30 + 5) + (3 + 1)
    postflight_bound = 3 + 1
    exact_file_mutation_bound = (2 + 1) + (5 + 1)
    probe_failure_bound = (
        global_root_preflight_bound
        + global_directory_preflight_bound
        + max(directory_mutation_bound, exact_file_mutation_bound)
        + postflight_bound
    )
    batch_failure_bound = (3 + 1) + max(2 + 1 + 5 + 1, 0) + (3 + 1)
    # A successful sync returns before its soft deadline; a timeout stops the
    # publication chain, so two kill-after tails cannot accumulate.
    publication_success_bound = 2 * 8
    publication_timeout_bound = 8 + 2
    assert directory_mutation_bound == 85
    assert probe_failure_bound == 108
    assert controller.PODMAN_GUARD_SIGNAL_BOUND_SECONDS + probe_failure_bound <= controller.PROBE_CLEANUP_BOUND_SECONDS
    assert batch_failure_bound == 17 <= controller.BATCH_CLEANUP_BOUND_SECONDS
    assert publication_success_bound <= controller.RESULT_PUBLICATION_BOUND_SECONDS
    assert publication_timeout_bound <= controller.RESULT_PUBLICATION_BOUND_SECONDS
    assert controller.PROBE_CLEANUP_BOUND_SECONDS < controller.OUTER_KILL_GRACE_SECONDS
    assert controller.PARENT_TERM_GRACE_SECONDS + controller.PARENT_KILL_REAP_SECONDS == 165
    assert (
        controller.PARENT_TERM_GRACE_SECONDS
        + controller.PARENT_KILL_REAP_SECONDS
        + controller.BATCH_CLEANUP_BOUND_SECONDS
        + controller.RESULT_PUBLICATION_BOUND_SECONDS
        == controller.SIGNAL_TEARDOWN_BOUND_SECONDS
        < controller.SIGNAL_LEAD_SECONDS
    )


def test_probe_has_exact_pull_inspect_remove_sequence_and_no_runtime_entrypoint() -> None:
    text = (HERE / "probe_registry_gate.sh").read_text()
    assert text.count('podman pull --authfile "$auth_path" --platform linux/arm64') == 1
    assert text.count("/usr/bin/podman image inspect") == 1
    assert text.count("/usr/bin/podman image rm --force") == 1
    inspect_at = text.index("/usr/bin/podman image inspect")
    remove_at = text.index("/usr/bin/podman image rm --force")
    failure_at = text.index('if [[ "$DIAG_OUTCOME" != success ]]')
    assert inspect_at < remove_at < failure_at
    for fragment in ("_container_registry_pull", "container_run", "podman run"):
        assert fragment not in text


def test_launcher_arms_parent_death_signal() -> None:
    text = (HERE / "launch.sh").read_text()
    assert "prctl(1,signal.SIGTERM,0,0,0)" in text
    assert "if os.getppid()!=parent" in text


def test_controller_dict_literals_have_no_duplicate_string_keys() -> None:
    tree = ast.parse((HERE / "controller.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        assert len(keys) == len(set(keys)), f"duplicate dict key at line {node.lineno}"


def test_compute_manifest_covers_all_reachable_gate_tools() -> None:
    paths = {line.split("  ", 1)[1] for line in (HERE / "compute_tools.sha256").read_text().splitlines()}
    required = {
        "/usr/bin/basename",
        "/usr/bin/dirname",
        "/usr/bin/printf",
        "/usr/bin/scontrol",
        "/usr/bin/squeue",
        "/usr/bin/srun",
    }
    assert required <= paths


def _compute_manifest_attestation(manifest: Path, entries: int = 33) -> tuple[int, str, bytes]:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    function = batch[batch.index("compute_manifest_attestation()") : batch.index("[[ $# == 0")]
    shell = (
        "set -euo pipefail\n"
        + function
        + '\nif compute_manifest_attestation "$1" "$2"; then rc=0; else rc=$?; fi\n'
        + 'printf "%s" "${COMPUTE_MANIFEST_CATEGORY:-}"\nexit "$rc"\n'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "manifest-attestation", str(manifest), str(entries)],
        capture_output=True,
        check=False,
    )
    return result.returncode, result.stdout.decode("ascii"), result.stderr


def _current_host_manifest_lines() -> list[str]:
    paths = [line.split("  ", 1)[1] for line in (HERE / "compute_tools.sha256").read_text().splitlines()]
    return [f"{hashlib.sha256(Path(path).read_bytes()).hexdigest()}  {path}" for path in paths]


def _manifest_with_mismatches(tmp_path: Path, indices: set[int], *, missing: set[int] | None = None) -> Path:
    lines = _current_host_manifest_lines()
    assert len(lines) == 33
    missing = missing or set()
    for index in indices:
        _expected, path = lines[index].split("  ", 1)
        if index in missing:
            path = f"/usr/bin/v32-definitely-absent-{index}"
        lines[index] = f"{'0' * 64}  {path}"
    manifest = tmp_path / "manifest"
    manifest.write_text("\n".join(lines) + "\n")
    return manifest


def test_compute_manifest_attestation_accepts_exact_synthetic_host_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "current-host-manifest"
    manifest.write_text("\n".join(_current_host_manifest_lines()) + "\n")
    rc, category, stderr = _compute_manifest_attestation(manifest)
    assert (rc, category, stderr) == (0, "", b"")


@pytest.mark.parametrize("index", [0, 16, 32])
def test_compute_manifest_attestation_encodes_single_index(tmp_path: Path, index: int) -> None:
    rc, category, stderr = _compute_manifest_attestation(_manifest_with_mismatches(tmp_path, {index}))
    expected_bitmap = "".join("1" if bit == index else "0" for bit in range(33))
    assert rc == 1
    assert category == f"source_compute_manifest_c01_b{expected_bitmap}"
    assert stderr == b""
    assert controller.valid_compute_manifest_category(category)


def test_compute_manifest_attestation_encodes_multiple_and_missing_without_raw_output(tmp_path: Path) -> None:
    indices = {0, 16, 32}
    rc, category, stderr = _compute_manifest_attestation(_manifest_with_mismatches(tmp_path, indices, missing={16}))
    expected_bitmap = "".join("1" if bit in indices else "0" for bit in range(33))
    assert rc == 1
    assert category == f"source_compute_manifest_c03_b{expected_bitmap}"
    assert stderr == b""
    assert "/usr/bin" not in category
    assert not any(part in category for part in ("absent", "sha256", "stderr"))


def test_compute_manifest_attestation_rejects_malformed_or_wrong_count(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed"
    malformed.write_text("not a manifest\n")
    assert _compute_manifest_attestation(malformed) == (2, "", b"")
    current = tmp_path / "current"
    current.write_text("\n".join(_current_host_manifest_lines()) + "\n")
    assert _compute_manifest_attestation(current, entries=32) == (2, "", b"")


@pytest.mark.parametrize(
    "category",
    [
        "source_spool_identity",
        "source_spool_hash",
        "source_bundle_identity",
        "source_bundle_hash",
        "source_compute_manifest_c03_b100000000000000010000000000000001",
    ],
)
def test_source_phase_categories_are_allowed(category: str) -> None:
    payload = {
        "category": category,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    assert controller.validate_result_payload(captured, False)[1] == category


@pytest.mark.parametrize(
    "category",
    [
        "source_identity",
        "source_compute_manifest_c00_b" + "0" * 33,
        "source_compute_manifest_c01_b" + "0" * 33,
        "source_compute_manifest_c02_b1" + "0" * 32,
        "source_compute_manifest_c01_b1" + "0" * 31,
        "source_compute_manifest_c01_b1" + "0" * 32 + "x",
        "source_compute_manifest_c01_b1" + "0" * 32 + "_suffix",
    ],
)
def test_invalid_source_manifest_categories_are_rejected(category: str) -> None:
    assert not controller.valid_compute_manifest_category(category)
    payload = {
        "category": category,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    with pytest.raises(controller.GateError, match="public_log_contract"):
        controller.validate_result_payload(captured, False)


def test_batch_source_checks_are_split_and_ordered() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    source = batch[batch.index("readonly probe=") : batch.index("qos=${SLURM_JOB_QOS")]
    assert "block source_identity" not in source
    for category in (
        "source_spool_identity",
        "source_spool_hash",
        "source_bundle_identity",
        "source_bundle_hash",
        "source_compute_manifest_c",
    ):
        assert category in source
    assert source.index("source_spool_identity") < source.index("source_spool_hash")
    assert source.index("source_spool_hash") < source.index("source_bundle_identity")
    assert source.index("source_bundle_identity") < source.index("source_bundle_hash")
    assert source.index("source_bundle_hash") < source.index("compute_manifest_attestation")


def test_compute_manifest_is_bound_to_measured_node() -> None:
    batch = (HERE / "run_registry_gate.sbatch").read_text()
    assert '[[ "$node" == g3-128-109 ]]' in batch
    assert "/usr/bin/stat -c '%F:%a:%u:%h'" in batch
    assert "/usr/bin/stat -Lc '%F:%a:%u:%h'" in batch
    assert "\"$path_metadata\" != 'regular file:755:0:1'" in batch
    assert "\"$target_metadata\" != 'regular file:755:0:1'" in batch
    manifest_paths = [line.split("  ", 1)[1] for line in (HERE / "compute_tools.sha256").read_text().splitlines()]
    assert len(manifest_paths) == 33
    assert len(set(manifest_paths)) == 33
    assert "/usr/bin/python3.12" in manifest_paths


def test_all_33_manifest_entries_are_the_exact_fresh_v5_projection(tmp_path: Path) -> None:
    raw = (HERE / "compute_tools.sha256").read_bytes()
    assert len(raw.splitlines()) == 33
    assert hashlib.sha256(raw).hexdigest() == controller.COMPUTE_PROJECTION_SHA256
    controller.validate_compute_probe(mode400_manifest(tmp_path))


@pytest.mark.parametrize(
    ("line", "rc", "expected"),
    [
        ("gate_category=pull_http_401\ngate_cleanup=retained_empty", 2, "pull_http_401"),
        ("gate_category=pull_guard_child\ngate_cleanup=retained_empty", 2, "pull_guard_child"),
        ("gate_category=pull_image_missing\ngate_cleanup=retained_empty", 2, "pull_image_missing"),
        ("gate_category=image_identity\ngate_cleanup=retained_empty", 2, "image_identity"),
        ("gate_category=image_remove\ngate_cleanup=retained_empty", 2, "image_remove"),
        ("gate_category=podman_info_command\ngate_cleanup=retained_empty", 2, "podman_info_command"),
        ("gate_category=podman_info_shape\ngate_cleanup=retained_empty", 2, "podman_info_shape"),
        ("gate_category=podman_store_graphroot\ngate_cleanup=retained_empty", 2, "podman_store_graphroot"),
        ("gate_category=podman_store_runroot\ngate_cleanup=retained_empty", 2, "podman_store_runroot"),
        ("gate_category=podman_store_driver\ngate_cleanup=retained_empty", 2, "podman_store_driver"),
        ("gate_guard_stage=precondition\ngate_cleanup=retained_empty", 125, "registry_pull"),
        ("gate_guard_stage=child\ngate_cleanup=retained_empty", 125, "registry_pull"),
        ("gate_guard_stage=postcondition\ngate_cleanup=retained_empty", 125, "registry_pull"),
        ("gate_category=live_writer_cleanup_unproven", 3, "live_writer_cleanup_unproven"),
        ("gate_category=probe_source_identity", 2, "probe_source_identity"),
        ("unclassified private text", 143, "interrupted"),
        ("unclassified private text", 1, "internal"),
    ],
)
def test_actual_shell_stderr_classification(tmp_path: Path, line: str, rc: int, expected: str) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text(line + "\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            'source "$1"; classify_registry_error_file "$2" "$3"; printf "%s" "$REGISTRY_SAFE_CATEGORY"',
            "classifier-test",
            str(script),
            str(error_file),
            str(rc),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.decode() == expected


@pytest.mark.parametrize(
    "marker",
    [
        "podman_info_command",
        "podman_info_shape",
        "podman_store_graphroot",
        "podman_store_runroot",
        "podman_store_driver",
        "podman_info_image_present",
        "podman_info_image_check",
        "registry_pull",
        "pull_http_401",
        "pull_guard_child",
        "image_identity",
        "image_remove",
    ],
)
def test_post_root_category_requires_positive_cleanup_proof(tmp_path: Path, marker: str) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text(f"gate_category={marker}\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            'source "$1"; classify_registry_error_file "$2" 2; printf "%s" "$REGISTRY_SAFE_CATEGORY"',
            "classifier-cleanup-proof",
            str(script),
            str(error_file),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout == b"private_cleanup_sensitive"
    assert result.stderr == b""


def test_cleanup_failure_marker_precedes_podman_cause(tmp_path: Path) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text(
        "gate_category=podman_store_graphroot\ngate_category=private_cleanup_retained\ngate_cleanup=retained_empty\n"
    )
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            'source "$1"; classify_registry_error_file "$2" 2; printf "%s" "$REGISTRY_SAFE_CATEGORY"',
            "classifier-cleanup-priority",
            str(script),
            str(error_file),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout == b"private_cleanup_retained"
    assert result.stderr == b""


def test_store_mismatch_exit_proves_sensitive_cleanup_before_classification(tmp_path: Path) -> None:
    shell = (
        _probe_cleanup_setup()
        + _probe_cleanup_functions()
        + "\ncleanup_checkpoint() { :; }\n"
        + 'blocked() { /usr/bin/printf "gate_category=%s\\n" "$1" >&2; exit 2; }\n'
        + "trap exit_cleanup EXIT\n"
        + "blocked podman_store_graphroot\n"
    )
    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            shell,
            "store-mismatch-cleanup",
            str(tmp_path),
            str(HERE / "scrub_private_tree.py"),
        ],
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 2, result.stderr.decode()
    assert result.stdout == b""
    assert result.stderr.splitlines() == [
        b"gate_category=podman_store_graphroot",
        b"gate_cleanup=retained_empty",
    ]
    root = tmp_path / "root"
    assert root.is_dir()
    assert not [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]

    error_file = tmp_path / "captured-stderr"
    error_file.write_bytes(result.stderr)
    error_file.chmod(0o600)
    classifier = HERE / "classify_registry_error.sh"
    classified = subprocess.run(
        [
            "/usr/bin/bash",
            "-p",
            "-c",
            'source "$1"; classify_registry_error_file "$2" 2; printf "%s" "$REGISTRY_SAFE_CATEGORY"',
            "store-mismatch-classifier",
            str(classifier),
            str(error_file),
        ],
        check=False,
        capture_output=True,
    )
    assert classified.returncode == 0
    assert classified.stdout == b"podman_store_graphroot"
    assert classified.stderr == b""


def test_exact_retained_stderr_descriptor_surfaces_fixed_pull_category(tmp_path: Path) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text("gate_category=pull_not_authorized\ngate_cleanup=retained_empty\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    shell = (
        'source "$1"; exec {error_fd}<>"$2"; '
        "identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- /proc/self/fd/$error_fd); "
        'classify_registry_error_file "/proc/self/fd/$error_fd" 1 "$identity"; '
        '/usr/bin/printf "%s" "$REGISTRY_SAFE_CATEGORY"'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "descriptor-classifier", str(script), str(error_file)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout == b"pull_not_authorized"


def test_retained_stderr_descriptor_rejects_wrong_inode_binding(tmp_path: Path) -> None:
    error_file = tmp_path / "stderr"
    error_file.write_text("ERROR: private registry login failed with category=authentication\n")
    error_file.chmod(0o600)
    script = HERE / "classify_registry_error.sh"
    shell = (
        'source "$1"; exec {error_fd}<>"$2"; '
        'if classify_registry_error_file "/proc/self/fd/$error_fd" 1 "0:0:600:656177:1"; then exit 1; fi'
    )
    result = subprocess.run(
        ["/usr/bin/bash", "-p", "-c", shell, "descriptor-classifier", str(script), str(error_file)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize(
    "category",
    [
        "pull_mint_broker",
        "pull_authfile_lookup",
        "pull_guard_precondition",
        "pull_guard_child",
        "pull_guard_postcondition",
        "pull_http_400",
        "pull_http_401",
        "pull_http_403",
        "pull_http_404",
        "pull_http_other4xx",
        "pull_http_5xx",
        "pull_expired",
        "pull_not_authorized",
        "pull_denied",
        "pull_auth_challenge",
        "pull_config",
        "pull_writeback",
        "pull_tls",
        "pull_proxy",
        "pull_transport",
        "pull_timeout",
        "pull_image_missing",
        "pull_platform",
        "pull_storage",
        "pull_empty_125",
        "pull_empty_other",
        "pull_unknown",
        "image_identity",
        "image_remove",
    ],
)
def test_fixed_pull_categories_are_allowed_only_as_failures(category: str) -> None:
    payload = {
        "category": category,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    assert controller.validate_result_payload(captured, False)[1] == category
    payload["state"] = "complete"
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    with pytest.raises(controller.GateError, match="public_log_success"):
        controller.validate_result_payload(captured, True)


def test_public_success_log_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "LOG_ROOT", tmp_path)
    path = tmp_path / "slurm-12345.log"
    payload = {
        "category": SUCCESS_CATEGORY,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "complete",
    }
    path.write_bytes(controller.canonical(payload))
    path.chmod(0o600)
    captured = controller.stable_file(path, mode=0o600, maximum=4096)
    observed, category = controller.validate_result_payload(captured, True)
    assert observed == controller.digest(path.read_bytes())
    assert category == SUCCESS_CATEGORY


@pytest.mark.parametrize(
    "category",
    [
        "pull_permanent",
        "pull_arbitrary",
        "pull_http_418_raw_detail",
        "login_authentication",
        "direct_pull_o_success",
    ],
)
def test_non_allowlisted_pull_categories_are_rejected(category: str) -> None:
    payload = {
        "category": category,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    with pytest.raises(controller.GateError):
        controller.validate_result_payload(captured, False)


def test_success_cannot_be_accepted_as_failure() -> None:
    payload = {
        "category": SUCCESS_CATEGORY,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "blocked",
    }
    raw = controller.canonical(payload)
    captured = controller.Capture(raw, controller.digest(raw), (0,) * 9)
    with pytest.raises(controller.GateError, match="public_log_failure"):
        controller.validate_result_payload(captured, False)


def test_controller_normalizes_completed_gate_to_success() -> None:
    text = (HERE / "controller.py").read_text()
    assert 'final_category = category if not success else "success"' in text


def test_public_log_rejects_extra_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controller, "LOG_ROOT", tmp_path)
    path = tmp_path / "slurm-12345.log"
    payload = {
        "category": SUCCESS_CATEGORY,
        "image_digest": controller.IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v32",
        "platform": "linux/arm64",
        "state": "complete",
        "raw": "forbidden",
    }
    path.write_bytes(controller.canonical(payload))
    path.chmod(0o600)
    with pytest.raises(controller.GateError, match="public_log_contract"):
        captured = controller.stable_file(path, mode=0o600, maximum=4096)
        controller.validate_result_payload(captured, True)


def test_pending_is_not_launch_eligible() -> None:
    payload = controller.pending_contract({"controller": "f" * 64})
    assert payload["launch_eligible"] is False
    assert payload["state"] == "pending_independent_approval"
    assert payload["source_bound"] is True
    assert payload["approval_template"]["state"] == "approved_once"


def test_pending_bytes_are_canonical_for_current_bundle() -> None:
    hashes = {
        key: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        for key, (name, _mode) in controller.BUNDLE_FILES.items()
        if key != "pending"
    }
    assert (HERE / "pending.json").read_bytes() == controller.canonical(controller.pending_contract(hashes))


def test_controller_has_no_task_or_model_execution_imports() -> None:
    text = (HERE / "controller.py").read_text()
    assert "harbor" not in text.lower()
    assert "container_run(" not in text
    assert "podman run" not in text


def test_no_approval_is_shipped() -> None:
    assert not any("approval" in path.name for path in HERE.iterdir())
