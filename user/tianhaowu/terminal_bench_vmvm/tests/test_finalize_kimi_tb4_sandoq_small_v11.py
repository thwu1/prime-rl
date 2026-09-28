from __future__ import annotations

import hashlib
import json
from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v11 as v11
import pytest
from terminal_bench_vmvm import taskset


def test_v11_contract_binds_fresh_c16_execution() -> None:
    contract = v11.execution_contract(v11.EXECUTION_SLURM_JOB_ID)

    assert contract.source_revision == v11.EXECUTION_SOURCE_REVISION
    assert contract.plan_sha256 == v11.EXECUTION_PLAN_SHA256
    assert contract.plan_verifier == "capacity-bound-v10"
    assert contract.execution_project_root == str(v11.EXECUTION_PROJECT_ROOT)
    assert contract.concurrency == 16
    assert contract.supported_tasks == 52
    assert contract.stock_endpoint_identifier == v11.STOCK_ENDPOINT_IDENTIFIER
    assert contract.completion_marker_name == "v10_execution_completion.json"
    assert contract.require_persisted_verifier_artifacts is True
    assert v11.engine._validated_execution_contract(contract) is contract
    assert "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py" in (
        contract.supersession_source_files
    )


@pytest.mark.parametrize("job_id", ["", "0", "1611914", "1612350 ", "1612350:0"])
def test_v11_contract_rejects_any_other_job(job_id: str) -> None:
    with pytest.raises(v11.V11FinalizationError, match="execution_slurm_job_id_invalid"):
        v11.execution_contract(job_id)


def test_v11_wrapper_passes_only_exact_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v11.engine, "finalize", fake_finalize)
    result = v11.finalize(
        plan_path=v11.EXECUTION_PLAN,
        plan_sha256=v11.EXECUTION_PLAN_SHA256,
        run_dir=v11.EXECUTION_RUN_DIR,
        supersession_source_revision="a" * 40,
        execution_slurm_job_id=v11.EXECUTION_SLURM_JOB_ID,
    )
    assert result == {"state": "test"}
    assert captured["execution_contract"] == v11.execution_contract(
        v11.EXECUTION_SLURM_JOB_ID
    )
    with pytest.raises(v11.V11FinalizationError, match="execution_artifact_binding_invalid"):
        v11.finalize(
            plan_path=Path("/private/wrong-plan.json"),
            plan_sha256=v11.EXECUTION_PLAN_SHA256,
            run_dir=v11.EXECUTION_RUN_DIR,
            supersession_source_revision="a" * 40,
            execution_slurm_job_id=v11.EXECUTION_SLURM_JOB_ID,
        )


def test_v11_reopens_exact_persisted_artifacts(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    payloads = {"main": b"artifact"}
    aggregate = hashlib.sha256(b"main\0artifact").hexdigest()
    capture = {"bytes": 8, "sha256": aggregate, "captured": [], "missing": [], "collect": []}
    persistence = taskset._persist_verifier_artifacts(
        tmp_path,
        "trace-1",
        payloads,
        capture,
    )
    row = {
        "id": "trace-1",
        "stop_condition": "agent_completed",
        "rewards": {"solved": 1.0},
        "info": {"terminal_bench_artifacts": {**capture, "persistence": persistence}},
    }
    audit = v11.engine._persisted_verifier_artifact_audit(
        json.dumps(row).encode() + b"\n",
        tmp_path,
    )
    assert audit["state"] == "reopened-and-verified"
    assert audit["rows"] == audit["required_rows"] == 1
    assert audit["payloads"] == 1
    assert audit["bytes"] == 8

    del row["info"]["terminal_bench_artifacts"]
    with pytest.raises(
        v11.engine.V8SupersessionError,
        match="persisted_verifier_artifacts_missing",
    ):
        v11.engine._persisted_verifier_artifact_audit(
            json.dumps(row).encode() + b"\n",
            tmp_path,
        )


def test_v11_requires_exact_completion_and_dynamic_stock_identity(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    contract = v11.execution_contract(v11.EXECUTION_SLURM_JOB_ID)
    completion = {
        "execution_revision": v11.EXECUTION_SOURCE_REVISION,
        "job_id": v11.EXECUTION_SLURM_JOB_ID,
        "plan_sha256": v11.EXECUTION_PLAN_SHA256,
        "stage": "tb4-miniswe246-sandoq-small-v10-c16",
        "state": "completed-awaiting-v11-certification",
    }
    marker = tmp_path / "v10_execution_completion.json"
    marker.write_bytes(v11.engine.split.canonical_json(completion))
    marker.chmod(0o600)
    held = v11.engine.split._HeldArtifactSet.create()
    try:
        audited = v11.engine._execution_completion_audit(tmp_path, contract, held)
        assert audited is not None
        assert audited[0] == completion
        held.revalidate()
    finally:
        held.close()

    identity = {
        "deployment": {
            "spec_sha256": v11.STOCK_SOURCE_SPEC_SHA256,
            "endpoint_bundle_sha256": v11.STOCK_ENDPOINT_BUNDLE_SHA256,
            "router": {
                "policy": "consistent_hash",
                "capacity_profile": "sandoq-stock-single-c64-v1",
                "endpoint_identifier": v11.STOCK_ENDPOINT_IDENTIFIER,
                "worker_count": 1,
                "provider_concurrency": 64,
                "per_worker_capacity": 64,
            },
        }
    }
    v11.engine._validate_execution_stock_identity(identity, contract)
    identity["deployment"]["router"]["endpoint_identifier"] = "wrong"
    with pytest.raises(v11.engine.V8SupersessionError, match="stock_identity_invalid"):
        v11.engine._validate_execution_stock_identity(identity, contract)


def test_v11_batch_wrapper_is_hard_bound_and_does_not_submit() -> None:
    wrapper = (
        Path(v11.__file__).resolve().parent
        / "run_finalize_kimi_tb4_sandoq_small_v11.sbatch"
    ).read_text()
    assert f"expected_producer_job={v11.EXECUTION_SLURM_JOB_ID}" in wrapper
    assert f"execution_revision={v11.EXECUTION_SOURCE_REVISION}" in wrapper
    assert f"plan_sha256={v11.EXECUTION_PLAN_SHA256}" in wrapper
    assert f"plan={v11.EXECUTION_PLAN}" in wrapper
    assert f"run_dir={v11.EXECUTION_RUN_DIR}" in wrapper
    assert "producer_not_terminal" in wrapper
    assert "v11_output_not_fresh" in wrapper
    assert "sbatch " not in wrapper
