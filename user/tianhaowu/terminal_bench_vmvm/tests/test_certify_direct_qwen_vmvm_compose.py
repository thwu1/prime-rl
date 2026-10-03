from __future__ import annotations

import json
import os
from pathlib import Path

import certify_direct_qwen_vmvm_compose as certificate
import pytest

IDENTITY_SHA256 = "a" * 64


def _nonces(*values: str) -> frozenset[str]:
    return frozenset(values)


def _receipt(
    *,
    compose: bool,
    nonce: str = "1" * 32,
    cleanup_pass: int = 1,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "vmvm-runtime-cleanup",
        "runtime_instance_nonce": nonce,
        "cleanup_pass": cleanup_pass,
        "state": "passed",
        "attempted": 1,
        "failures": 0,
        "host_tunnel_count": 0,
        "host_tunnels_closed": 0,
        "network_firewall_present": True,
        "network_firewall_cleanup_completed": True,
        "session_present": compose,
        "session_stop_completed": True,
        "fifo_present": not compose,
        "fifo_cleanup_completed": True,
        "compose_present": compose,
        "compose_teardown_completed": True,
        "compose_directory_cleanup_completed": True,
        "container_present": not compose,
        "container_teardown_completed": True,
        "internal_network_present": True,
        "internal_network_teardown_completed": True,
        "ssh_master_stop_completed": True,
        "lease_process_was_alive": True,
        "lease_sigterm_sent": True,
        "lease_wait_completed": True,
        "lease_exit_code": 0,
        "lease_sigkill_used": False,
        "release_on_exit_completed": True,
        "remote_deletion_verified": False,
        "eval_run_identity_sha256": IDENTITY_SHA256,
    }


def _private_run(tmp_path: Path, records: list[dict[str, object]]) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    control = run_dir / "control"
    control.mkdir(parents=True)
    os.chmod(run_dir, 0o700)
    os.chmod(control, 0o700)
    receipt = control / "vmvm_cleanup_receipts.jsonl"
    receipt.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    os.chmod(receipt, 0o600)
    return run_dir, receipt


def test_private_cleanup_receipts_account_for_agent_and_separate_verifier(tmp_path: Path) -> None:
    run_dir, receipt = _private_run(
        tmp_path,
        [_receipt(compose=True), _receipt(compose=False, nonce="2" * 32)],
    )

    result = certificate._read_private_cleanup_receipts(
        receipt,
        run_dir=run_dir,
        expected_identity_sha256=IDENTITY_SHA256,
        expected_runtime_nonces=_nonces("1" * 32, "2" * 32),
        verifier_mode="separate",
    )

    assert result == {
        "state": "passed",
        "runtime_instances": 2,
        "cleanup_passes": 2,
        "agent_runtime_instances": 1,
        "verifier_runtime_instances": 1,
        "verifier_mode": "separate",
        "compose_runtime_instances": 1,
        "local_cleanup_failures": 0,
        "release_on_exit_completed": 2,
        "remote_deletion_verified": False,
    }


@pytest.mark.parametrize(
    ("mutate", "expected_count"),
    [
        (lambda rows: rows.append(_receipt(compose=False)), 2),
        (lambda rows: rows[0].update(state="failed", failures=1), 2),
        (lambda rows: rows[0].update(eval_run_identity_sha256="b" * 64), 2),
        (lambda rows: rows[0].update(lease_sigkill_used=True), 2),
        (lambda rows: rows[0].update(remote_deletion_verified=True), 2),
        (lambda rows: rows[0].update(attempted=True), 2),
        (lambda rows: rows[0].update(failures=False), 2),
        (lambda rows: rows[0].update(lease_exit_code=False), 2),
        (lambda rows: rows[1].update(session_stop_completed=False), 2),
    ],
)
def test_private_cleanup_receipts_reject_tampering(
    tmp_path: Path,
    mutate,
    expected_count: int,
) -> None:
    rows = [_receipt(compose=True), _receipt(compose=False, nonce="2" * 32)]
    mutate(rows)
    run_dir, receipt = _private_run(tmp_path, rows)

    with pytest.raises(certificate.VmvmComposeCertificateError):
        certificate._read_private_cleanup_receipts(
            receipt,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
            expected_runtime_nonces=_nonces("1" * 32, "2" * 32) if expected_count == 2 else _nonces("1" * 32),
            verifier_mode="separate",
        )


def test_private_cleanup_receipts_require_private_regular_file(tmp_path: Path) -> None:
    run_dir, receipt = _private_run(tmp_path, [_receipt(compose=True)])
    os.chmod(receipt, 0o644)

    with pytest.raises(certificate.VmvmComposeCertificateError, match="^vmvm_cleanup_receipt_invalid$"):
        certificate._read_private_cleanup_receipts(
            receipt,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
            expected_runtime_nonces=_nonces("1" * 32),
            verifier_mode="shared",
        )


def test_private_cleanup_receipts_reject_hard_link(tmp_path: Path) -> None:
    run_dir, receipt = _private_run(tmp_path, [_receipt(compose=True)])
    os.link(receipt, tmp_path / "alias.jsonl")

    with pytest.raises(certificate.VmvmComposeCertificateError, match="^vmvm_cleanup_receipt_invalid$"):
        certificate._read_private_cleanup_receipts(
            receipt,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
            expected_runtime_nonces=_nonces("1" * 32),
            verifier_mode="shared",
        )


@pytest.mark.parametrize(
    ("mode", "attempts", "failures"),
    [
        ("shared", 1, []),
        ("separate", 1, []),
        ("separate", 2, ["first verifier runtime failed"]),
    ],
)
def test_verifier_mode_is_validated_without_deriving_runtime_count_from_trace(
    tmp_path: Path,
    mode: str,
    attempts: int,
    failures: list[str],
) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps(
            {
                "info": {
                    "terminal_bench_verifier": {
                        "mode": mode,
                        "attempts": attempts,
                        "infrastructure_failures": failures,
                    }
                }
            }
        )
        + "\n"
    )

    assert certificate._verifier_mode_from_results(results) == mode


def test_private_lifecycle_receipts_are_authoritative_for_runtime_instances(
    tmp_path: Path,
) -> None:
    run_dir, _receipt_path = _private_run(tmp_path, [_receipt(compose=True)])
    lifecycle = run_dir / "control" / "vmvm_runtime_lifecycle.jsonl"
    lifecycle.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "vmvm-runtime-created",
                "runtime_instance_nonce": "1" * 32,
                "eval_run_identity_sha256": IDENTITY_SHA256,
            },
            sort_keys=True,
        )
        + "\n"
    )
    lifecycle.chmod(0o600)

    assert certificate._read_private_lifecycle_receipts(
        lifecycle,
        run_dir=run_dir,
        expected_identity_sha256=IDENTITY_SHA256,
    ) == _nonces("1" * 32)


@pytest.mark.parametrize("mutation", ["duplicate", "foreign", "hardlink"])
def test_private_lifecycle_receipts_reject_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    run_dir, _receipt_path = _private_run(tmp_path, [_receipt(compose=True)])
    lifecycle = run_dir / "control" / "vmvm_runtime_lifecycle.jsonl"
    value = {
        "schema_version": 1,
        "kind": "vmvm-runtime-created",
        "runtime_instance_nonce": "1" * 32,
        "eval_run_identity_sha256": IDENTITY_SHA256,
    }
    values = [value]
    if mutation == "duplicate":
        values.append(value)
    elif mutation == "foreign":
        value["eval_run_identity_sha256"] = "b" * 64
    lifecycle.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in values))
    lifecycle.chmod(0o600)
    if mutation == "hardlink":
        os.link(lifecycle, tmp_path / "lifecycle-alias.jsonl")

    with pytest.raises(certificate.VmvmComposeCertificateError):
        certificate._read_private_lifecycle_receipts(
            lifecycle,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
        )


def test_private_cleanup_receipts_accept_reentrant_final_pass(tmp_path: Path) -> None:
    final_pass = _receipt(compose=False, cleanup_pass=2)
    final_pass.update(
        network_firewall_present=False,
        internal_network_present=False,
    )
    run_dir, receipt = _private_run(
        tmp_path,
        [
            _receipt(compose=True, cleanup_pass=1),
            final_pass,
        ],
    )

    result = certificate._read_private_cleanup_receipts(
        receipt,
        run_dir=run_dir,
        expected_identity_sha256=IDENTITY_SHA256,
        expected_runtime_nonces=_nonces("1" * 32),
        verifier_mode="shared",
    )

    assert result["runtime_instances"] == 1
    assert result["cleanup_passes"] == 2


def test_private_cleanup_receipts_reject_nonconsecutive_reentrant_passes(
    tmp_path: Path,
) -> None:
    run_dir, receipt = _private_run(
        tmp_path,
        [
            _receipt(compose=True, cleanup_pass=1),
            _receipt(compose=True, cleanup_pass=3),
        ],
    )

    with pytest.raises(
        certificate.VmvmComposeCertificateError,
        match="^vmvm_cleanup_receipt_count_invalid$",
    ):
        certificate._read_private_cleanup_receipts(
            receipt,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
            expected_runtime_nonces=_nonces("1" * 32),
            verifier_mode="shared",
        )


def test_cleanup_receipts_must_exactly_match_lifecycle_nonces(tmp_path: Path) -> None:
    run_dir, receipt = _private_run(tmp_path, [_receipt(compose=True)])

    with pytest.raises(
        certificate.VmvmComposeCertificateError,
        match="^vmvm_cleanup_receipt_count_invalid$",
    ):
        certificate._read_private_cleanup_receipts(
            receipt,
            run_dir=run_dir,
            expected_identity_sha256=IDENTITY_SHA256,
            expected_runtime_nonces=_nonces("1" * 32, "2" * 32),
            verifier_mode="separate",
        )
