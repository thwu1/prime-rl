import copy
import fcntl
import hashlib
import json
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import audit_oracle_repair_canary as auditor
import pytest
from audit_oracle_repair_canary import CanaryAuditError, audit_canary, main
from build_oracle_repair_canary import build_canary_manifest

SOURCE_COMMIT = "a" * 40
CANARY_COMMIT = "b" * 40
SOURCE_VERIFIERS_COMMIT = "c" * 40
CANARY_VERIFIERS_COMMIT = "e" * 40
SOURCE_VMVM_SHA256 = "d" * 64
CANARY_VMVM_SHA256 = "f" * 64
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ordered_sha256(slugs: list[str]) -> str:
    return hashlib.sha256("".join(f"{slug}\n" for slug in slugs).encode()).hexdigest()


def _write_oracle(
    oracle: Path,
    identity: dict[str, Any],
    row_specs: list[tuple[str, bool, str]],
) -> list[dict[str, Any]]:
    statuses = oracle / "tasks"
    statuses.mkdir(parents=True)
    (oracle / ".writer.lock").touch()
    identity_sha256 = _canonical_sha256(identity)
    (oracle / "run_identity.json").write_text(
        json.dumps(
            {
                "identity": identity,
                "run_identity_sha256": identity_sha256,
                "schema_version": 1,
            },
            sort_keys=True,
        )
        + "\n"
    )
    rows = []
    network_semantics = identity["network_semantics"]
    for index, (slug, valid, reason) in enumerate(row_specs):
        row = {
            "attempts": 1,
            "elapsed_sec": float(index + 1),
            "error": None if valid else f"secret-error-{index}",
            "error_type": None if valid else "SecretFailure",
            "image": f"registry.invalid/secret-image-{index}@sha256:" + str(index) * 64,
            "index": index,
            "infrastructure_failures": [],
            "name": f"secret-name-{index}",
            "oracle_network_semantics": network_semantics,
            "reason": reason,
            "run_identity_sha256": identity_sha256,
            "slug": slug,
            "valid": valid,
        }
        rows.append(row)
        (statuses / f"{slug}.json").write_text(json.dumps(row, sort_keys=True) + "\n")
    (oracle / "results.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    reasons = Counter(row["reason"] for row in rows)
    passed = sum(row["valid"] for row in rows)
    (oracle / "summary.json").write_text(
        json.dumps(
            {
                "completed": len(rows),
                "finished_at": 1234.5,
                "oracle_network_semantics": network_semantics,
                "pass_rate": passed / len(rows),
                "passed": passed,
                "reasons": dict(reasons),
                "run_identity_sha256": identity_sha256,
                "selected": len(rows),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return rows


def _source_fixture(
    tmp_path: Path,
    *,
    prime_rl_commit: str = SOURCE_COMMIT,
    verifiers_commit: str = SOURCE_VERIFIERS_COMMIT,
    vmvm_tb_v2_sha256: str = SOURCE_VMVM_SHA256,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    slugs = [f"secret-task-{index}" for index in range(8)]
    identity = {
        "acceptance": {"minimum_pass_rate": 0.9, "minimum_valid": 7},
        "dataset": {
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
            "path": "/private/dataset",
            "revision": "2" * 40,
        },
        "execution": {
            "infra_retries": 2,
            "lease_ttl": "60s",
            "max_concurrent": 8,
            "max_session_buffer_size": 67_108_864,
            "resource_multiplier": 1.0,
            "runtime_image": "python:3.12-slim",
            "runtime_workdir": "/app",
            "session_timeout_sec": 10_800.0,
            "setup_timeout_sec": 3_600.0,
            "tenant_id": "fake-tenant",
            "timeout_multiplier": 1.0,
            "vacli_container_privileged": True,
            "vacli_image_pull_timeout_seconds": 3_600,
            "vacli_lease_retries": 20,
            "vacli_max_concurrent_leases": 4,
            "vacli_max_pull_retries": 20,
            "validate_timeout_sec": 10_800.0,
            "verifier_runtime_retries": 2,
        },
        "images": {
            "manifest": {"path": "/private/images.json", "sha256": "3" * 64},
            "prefix": "registry.invalid/private",
            "tag": "private-tag",
            "use_declared_images": False,
            "enable_compose": True,
        },
        "network_semantics": {
            "schema_version": 1,
            "trusted_reference_solution": "public",
            "verifier": "declared",
        },
        "schema_version": 1,
        "selection": {
            "count": len(slugs),
            "limit": None,
            "offset": 0,
            "ordered_task_slugs_sha256": _ordered_sha256(slugs),
            "task_file": {"path": None, "sha256": None},
        },
        "source": {
            "prime_rl_commit": prime_rl_commit,
            "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
            "verifiers_commit": verifiers_commit,
            "vmvm_tb_v2_sha256": vmvm_tb_v2_sha256,
        },
    }
    specifications = []
    nonvalid = {1: "invalid", 4: "error", 6: "timeout"}
    for index, slug in enumerate(slugs):
        reason = nonvalid.get(index, "valid")
        specifications.append((slug, reason == "valid", reason))
    oracle = tmp_path / "source-oracle"
    return oracle, identity, _write_oracle(oracle, identity, specifications)


def _builder_artifacts(
    tmp_path: Path,
    source: Path,
    *,
    controls: int = 2,
) -> tuple[Path, Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    task_file = artifacts / "canary.tasks.txt"
    receipt = artifacts / "canary.receipt.json"
    build_canary_manifest(
        source,
        task_file,
        receipt,
        expected_total=8,
        control_count=controls,
        seed="fixed-seed",
    )
    return task_file, receipt


def _canary_fixture(
    tmp_path: Path,
    source_identity: dict[str, Any],
    source_rows: list[dict[str, Any]],
    task_file: Path,
    *,
    recovered: int = 2,
    regress_control: bool = False,
    mutate_identity: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    tasks = task_file.read_text().splitlines()
    source_by_slug = {row["slug"]: row for row in source_rows}
    identity = copy.deepcopy(source_identity)
    identity["selection"] = {
        "count": len(tasks),
        "limit": None,
        "offset": 0,
        "ordered_task_slugs_sha256": _ordered_sha256(tasks),
        "task_file": {
            "path": str(task_file.resolve()),
            "sha256": hashlib.sha256(task_file.read_bytes()).hexdigest(),
        },
    }
    identity["source"] = {
        **identity["source"],
        "prime_rl_commit": CANARY_COMMIT,
        "verifiers_commit": CANARY_VERIFIERS_COMMIT,
        "vmvm_tb_v2_sha256": CANARY_VMVM_SHA256,
    }
    if mutate_identity is not None:
        mutate_identity(identity)

    specifications = []
    recovered_so_far = 0
    regressed = False
    for slug in tasks:
        before = source_by_slug[slug]
        if before["valid"]:
            valid = not regress_control or regressed
            regressed = regressed or not valid
        else:
            valid = recovered_so_far < recovered
            recovered_so_far += int(valid)
        specifications.append((slug, valid, "valid" if valid else "invalid"))
    canary = tmp_path / "canary-oracle"
    return canary, _write_oracle(canary, identity, specifications)


def _inputs(
    tmp_path: Path,
    *,
    recovered: int = 2,
    regress_control: bool = False,
    mutate_identity: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path, Path, Path, list[dict[str, Any]], list[dict[str, Any]]]:
    source, identity, source_rows = _source_fixture(tmp_path)
    task_file, receipt = _builder_artifacts(tmp_path, source)
    canary, canary_rows = _canary_fixture(
        tmp_path,
        identity,
        source_rows,
        task_file,
        recovered=recovered,
        regress_control=regress_control,
        mutate_identity=mutate_identity,
    )
    return source, receipt, task_file, canary, source_rows, canary_rows


def _audit(
    source: Path,
    receipt: Path,
    task_file: Path,
    canary: Path,
    certificate: Path,
    *,
    minimum_recovered: int = 2,
    expected_source_prime_rl_commit: str = SOURCE_COMMIT,
    expected_source_verifiers_commit: str = SOURCE_VERIFIERS_COMMIT,
    expected_source_vmvm_tb_v2_sha256: str = SOURCE_VMVM_SHA256,
    expected_verifiers_commit: str = CANARY_VERIFIERS_COMMIT,
    expected_vmvm_tb_v2_sha256: str = CANARY_VMVM_SHA256,
) -> dict[str, Any]:
    return audit_canary(
        source,
        receipt,
        task_file,
        canary,
        certificate,
        expected_source_prime_rl_commit=expected_source_prime_rl_commit,
        expected_source_verifiers_commit=expected_source_verifiers_commit,
        expected_source_vmvm_tb_v2_sha256=expected_source_vmvm_tb_v2_sha256,
        expected_prime_rl_commit=CANARY_COMMIT,
        expected_verifiers_commit=expected_verifiers_commit,
        expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        expected_total=8,
        control_count=2,
        minimum_recovered=minimum_recovered,
        seed="fixed-seed",
    )


def test_audits_transitions_confidentially_and_writes_self_hashed_certificate(tmp_path: Path) -> None:
    source, receipt, task_file, canary, source_rows, canary_rows = _inputs(tmp_path)
    certificate = tmp_path / "audit.json"

    summary = _audit(source, receipt, task_file, canary, certificate)

    assert summary["ok"] is True
    assert summary["state"] == "passed"
    assert summary["control_regressions"] == 0
    assert summary["recovered"] == 2
    assert summary["repair_candidates"] == 3
    assert summary["reason_counts"]["canary"] == {"invalid": 1, "valid": 4}
    assert stat.S_IMODE(certificate.stat().st_mode) == 0o600
    envelope = json.loads(certificate.read_text())
    assert envelope["audit_sha256"] == _canonical_sha256(envelope["audit"])
    assert envelope["audit"]["contracts"]["source_oracle_source"] == {
        "prime_rl_commit": SOURCE_COMMIT,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": SOURCE_VERIFIERS_COMMIT,
        "vmvm_tb_v2_sha256": SOURCE_VMVM_SHA256,
    }
    assert envelope["audit"]["contracts"]["canary_source"] == {
        "prime_rl_commit": CANARY_COMMIT,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": CANARY_VERIFIERS_COMMIT,
        "vmvm_tb_v2_sha256": CANARY_VMVM_SHA256,
    }
    assert envelope["audit"]["transitions"] == {
        "source_nonvalid_to_nonvalid": 1,
        "source_nonvalid_to_valid": 2,
        "source_valid_to_nonvalid": 0,
        "source_valid_to_valid": 2,
    }
    aggregate_text = certificate.read_text() + json.dumps(summary, sort_keys=True)
    private_values = [row["slug"] for row in source_rows]
    private_values.extend(row["name"] for row in source_rows)
    private_values.extend(row["error"] for row in source_rows if row["error"] is not None)
    private_values.extend(row["name"] for row in canary_rows)
    assert not any(value in aggregate_text for value in private_values)
    assert _audit(source, receipt, task_file, canary, certificate)["published"] is False


@pytest.mark.parametrize(
    ("recovered", "regress_control", "minimum_recovered", "expected_regressions"),
    [(1, False, 2, 0), (3, True, 2, 1), (3, False, 4, 0)],
)
def test_publishes_failed_certificate_for_gate_failure(
    tmp_path: Path,
    recovered: int,
    regress_control: bool,
    minimum_recovered: int,
    expected_regressions: int,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(
        tmp_path,
        recovered=recovered,
        regress_control=regress_control,
    )
    certificate = tmp_path / "audit.json"

    summary = _audit(
        source,
        receipt,
        task_file,
        canary,
        certificate,
        minimum_recovered=minimum_recovered,
    )

    assert summary["ok"] is False
    assert summary["state"] == "failed"
    assert summary["control_regressions"] == expected_regressions
    assert json.loads(certificate.read_text())["audit"]["state"] == "failed"


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda identity: identity["selection"]["task_file"].update(sha256="0" * 64),
            "canary_selection_identity_invalid",
        ),
        (lambda identity: identity["source"].update(prime_rl_commit="e" * 40), "canary_source_contract_invalid"),
        (
            lambda identity: identity["source"].update(verifiers_commit="1" * 40),
            "canary_source_contract_invalid",
        ),
        (
            lambda identity: identity["source"].update(vmvm_tb_v2_sha256="2" * 64),
            "canary_source_contract_invalid",
        ),
        (lambda identity: identity["dataset"].update(revision="f" * 40), "canary_benchmark_contract_invalid"),
        (lambda identity: identity["images"].update(tag="changed"), "canary_benchmark_contract_invalid"),
        (
            lambda identity: identity["execution"].update(validate_timeout_sec=20_000.0),
            "canary_benchmark_contract_invalid",
        ),
        (
            lambda identity: identity["network_semantics"].update(trusted_reference_solution="declared"),
            "canary_benchmark_contract_invalid",
        ),
        (
            lambda identity: identity["network_semantics"].update(schema_version=True),
            "canary_run_identity_invalid",
        ),
    ],
)
def test_rejects_mismatched_canary_identity(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    error: str,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path, mutate_identity=mutation)
    certificate = tmp_path / "audit.json"

    with pytest.raises(CanaryAuditError, match=f"^{error}$"):
        _audit(source, receipt, task_file, canary, certificate)
    assert not certificate.exists()


@pytest.mark.parametrize(
    ("expected_verifiers_commit", "expected_vmvm_tb_v2_sha256"),
    [
        ("1" * 40, CANARY_VMVM_SHA256),
        (CANARY_VERIFIERS_COMMIT, "2" * 64),
    ],
)
def test_rejects_unreviewed_execution_source_pin(
    tmp_path: Path,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    certificate = tmp_path / "audit.json"

    with pytest.raises(CanaryAuditError, match="^canary_source_contract_invalid$"):
        _audit(
            source,
            receipt,
            task_file,
            canary,
            certificate,
            expected_verifiers_commit=expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        )
    assert not certificate.exists()


@pytest.mark.parametrize(
    ("prime_rl_commit", "verifiers_commit", "vmvm_tb_v2_sha256"),
    [
        ("1" * 40, SOURCE_VERIFIERS_COMMIT, SOURCE_VMVM_SHA256),
        (SOURCE_COMMIT, "2" * 40, SOURCE_VMVM_SHA256),
        (SOURCE_COMMIT, SOURCE_VERIFIERS_COMMIT, "3" * 64),
    ],
)
def test_rejects_fully_self_consistent_rebuilt_source_with_untrusted_pin(
    tmp_path: Path,
    prime_rl_commit: str,
    verifiers_commit: str,
    vmvm_tb_v2_sha256: str,
) -> None:
    source, identity, source_rows = _source_fixture(
        tmp_path,
        prime_rl_commit=prime_rl_commit,
        verifiers_commit=verifiers_commit,
        vmvm_tb_v2_sha256=vmvm_tb_v2_sha256,
    )
    task_file, receipt = _builder_artifacts(tmp_path, source)
    canary, _ = _canary_fixture(tmp_path, identity, source_rows, task_file)
    certificate = tmp_path / "audit.json"

    with pytest.raises(CanaryAuditError, match="^source_provenance_mismatch$"):
        _audit(source, receipt, task_file, canary, certificate)
    assert not certificate.exists()


@pytest.mark.parametrize(
    ("expected_verifiers_commit", "expected_vmvm_tb_v2_sha256", "error"),
    [
        ("not-a-revision", CANARY_VMVM_SHA256, "expected_verifiers_commit_invalid"),
        (CANARY_VERIFIERS_COMMIT, "not-a-sha256", "expected_vmvm_tb_v2_sha256_invalid"),
    ],
)
def test_rejects_malformed_execution_source_pin(
    tmp_path: Path,
    expected_verifiers_commit: str,
    expected_vmvm_tb_v2_sha256: str,
    error: str,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)

    with pytest.raises(CanaryAuditError, match=f"^{error}$"):
        _audit(
            source,
            receipt,
            task_file,
            canary,
            tmp_path / "audit.json",
            expected_verifiers_commit=expected_verifiers_commit,
            expected_vmvm_tb_v2_sha256=expected_vmvm_tb_v2_sha256,
        )


@pytest.mark.parametrize(
    ("keyword", "value", "error"),
    [
        ("expected_source_prime_rl_commit", "not-a-revision", "expected_source_prime_rl_commit_invalid"),
        (
            "expected_source_verifiers_commit",
            "not-a-revision",
            "expected_source_verifiers_commit_invalid",
        ),
        (
            "expected_source_vmvm_tb_v2_sha256",
            "not-a-sha256",
            "expected_source_vmvm_tb_v2_sha256_invalid",
        ),
    ],
)
def test_rejects_malformed_trusted_source_pin(
    tmp_path: Path,
    keyword: str,
    value: str,
    error: str,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)

    with pytest.raises(CanaryAuditError, match=f"^{error}$"):
        _audit(source, receipt, task_file, canary, tmp_path / "audit.json", **{keyword: value})


def test_rejects_tampered_builder_artifacts(tmp_path: Path) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    lines = task_file.read_text().splitlines()
    task_file.write_text("\n".join(reversed(lines)) + "\n")

    with pytest.raises(CanaryAuditError, match="^builder_task_file_mismatch$"):
        _audit(source, receipt, task_file, canary, tmp_path / "task-tamper.json")

    source, receipt, task_file, canary, _, _ = _inputs(tmp_path / "receipt-case")
    envelope = json.loads(receipt.read_text())
    envelope["receipt"]["counts"]["selected"] += 1
    receipt.write_text(json.dumps(envelope, sort_keys=True) + "\n")
    with pytest.raises(CanaryAuditError, match="^builder_receipt_invalid$"):
        _audit(source, receipt, task_file, canary, tmp_path / "receipt-tamper.json")


def test_malformed_source_contract_has_stable_error(tmp_path: Path) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    identity_path = source / "run_identity.json"
    envelope = json.loads(identity_path.read_text())
    envelope["identity"]["source"]["prime_rl_commit"] = None
    envelope["run_identity_sha256"] = _canonical_sha256(envelope["identity"])
    identity_path.write_text(json.dumps(envelope, sort_keys=True) + "\n")

    with pytest.raises(CanaryAuditError, match="^source_run_identity_invalid$"):
        _audit(source, receipt, task_file, canary, tmp_path / "audit.json")


def test_rejects_active_writer_and_incomplete_canary_universe(tmp_path: Path) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    certificate = tmp_path / "audit.json"

    with (canary / ".writer.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(CanaryAuditError, match="^canary_writer_active$"):
            _audit(source, receipt, task_file, canary, certificate)

    status = next((canary / "tasks").iterdir())
    status.unlink()
    with pytest.raises(CanaryAuditError, match="^canary_output_invalid$"):
        _audit(source, receipt, task_file, canary, certificate)
    assert not certificate.exists()


def test_rechecks_private_artifact_mode_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    certificate = tmp_path / "audit.json"
    original = auditor._transition_counts

    def make_task_file_public(*args: Any, **kwargs: Any) -> tuple[dict[str, int], dict[str, Any]]:
        transitions = original(*args, **kwargs)
        task_file.chmod(0o644)
        return transitions

    monkeypatch.setattr(auditor, "_transition_counts", make_task_file_public)
    with pytest.raises(CanaryAuditError, match="^source_changed$"):
        _audit(source, receipt, task_file, canary, certificate)
    assert not certificate.exists()


def test_cli_reports_aggregates_only_and_uses_gate_exit_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, receipt, task_file, canary, source_rows, canary_rows = _inputs(tmp_path, recovered=1)
    certificate = tmp_path / "audit.json"

    exit_status = main(
        [
            str(source),
            str(receipt),
            str(task_file),
            str(canary),
            str(certificate),
            "--expected-source-prime-rl-commit",
            SOURCE_COMMIT,
            "--expected-source-verifiers-commit",
            SOURCE_VERIFIERS_COMMIT,
            "--expected-source-vmvm-tb-v2-sha256",
            SOURCE_VMVM_SHA256,
            "--expected-prime-rl-commit",
            CANARY_COMMIT,
            "--expected-verifiers-commit",
            CANARY_VERIFIERS_COMMIT,
            "--expected-vmvm-tb-v2-sha256",
            CANARY_VMVM_SHA256,
            "--expected-total",
            "8",
            "--controls",
            "2",
            "--minimum-recovered",
            "2",
            "--seed",
            "fixed-seed",
        ]
    )

    assert exit_status == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    output = json.loads(captured.out)
    assert output["ok"] is False
    assert output["recovered"] == 1
    private_values = [row["slug"] for row in source_rows]
    private_values.extend(row["name"] for row in source_rows)
    private_values.extend(row["error"] for row in source_rows if row["error"] is not None)
    private_values.extend(row["name"] for row in canary_rows)
    assert not any(value in captured.out for value in private_values)


def test_rejects_conflicting_write_once_certificate(tmp_path: Path) -> None:
    source, receipt, task_file, canary, _, _ = _inputs(tmp_path)
    certificate = tmp_path / "audit.json"
    certificate.write_text("unrelated\n")
    certificate.chmod(0o600)

    with pytest.raises(CanaryAuditError, match="^audit_certificate_already_exists$"):
        _audit(source, receipt, task_file, canary, certificate)
    assert certificate.read_text() == "unrelated\n"
