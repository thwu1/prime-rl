from __future__ import annotations

from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v11 as v11
import finalize_kimi_tb4_sandoq_small_v12 as v12
import pytest


def test_v12_contract_is_exactly_bound_and_only_v12_enables_new_policy() -> None:
    contract = v12.execution_contract(v12.EXECUTION_SLURM_JOB_ID)

    assert contract.source_revision == v12.EXECUTION_SOURCE_REVISION
    assert contract.plan_sha256 == v12.EXECUTION_PLAN_SHA256
    assert contract.slurm_job_id == "1612350"
    assert contract.plan_verifier == "capacity-bound-v10"
    assert contract.execution_project_root == str(v12.EXECUTION_PROJECT_ROOT)
    assert contract.concurrency == 16
    assert contract.require_persisted_verifier_artifacts is True
    assert contract.allow_post_agent_exec_transport_errors is True
    assert contract.allow_post_agent_artifact_write_transport_errors is True
    assert v12.engine._validated_execution_contract(contract) is contract
    assert v11.execution_contract(v11.EXECUTION_SLURM_JOB_ID).allow_post_agent_artifact_write_transport_errors is False


@pytest.mark.parametrize("job_id", ["", "0", "1611914", "1612350 ", "1612350:0"])
def test_v12_contract_rejects_any_other_job(job_id: str) -> None:
    with pytest.raises(v12.V12FinalizationError, match="execution_slurm_job_id_invalid"):
        v12.execution_contract(job_id)


def test_v12_wrapper_passes_only_exact_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v12.engine, "finalize", fake_finalize)
    result = v12.finalize(
        plan_path=v12.EXECUTION_PLAN,
        plan_sha256=v12.EXECUTION_PLAN_SHA256,
        run_dir=v12.EXECUTION_RUN_DIR,
        supersession_source_revision="a" * 40,
        execution_slurm_job_id=v12.EXECUTION_SLURM_JOB_ID,
    )
    assert result == {"state": "test"}
    assert captured["execution_contract"] == v12.execution_contract(v12.EXECUTION_SLURM_JOB_ID)
    with pytest.raises(v12.V12FinalizationError, match="execution_artifact_binding_invalid"):
        v12.finalize(
            plan_path=Path("/private/wrong-plan.json"),
            plan_sha256=v12.EXECUTION_PLAN_SHA256,
            run_dir=v12.EXECUTION_RUN_DIR,
            supersession_source_revision="a" * 40,
            execution_slurm_job_id=v12.EXECUTION_SLURM_JOB_ID,
        )


def test_v12_batch_wrapper_is_hard_bound_and_does_not_submit() -> None:
    wrapper = (Path(v12.__file__).resolve().parent / "run_finalize_kimi_tb4_sandoq_small_v12.sbatch").read_text()
    assert f"expected_producer_job={v12.EXECUTION_SLURM_JOB_ID}" in wrapper
    assert f"execution_revision={v12.EXECUTION_SOURCE_REVISION}" in wrapper
    assert f"plan_sha256={v12.EXECUTION_PLAN_SHA256}" in wrapper
    assert f"plan={v12.EXECUTION_PLAN}" in wrapper
    assert f"run_dir={v12.EXECUTION_RUN_DIR}" in wrapper
    assert "producer_not_terminal" in wrapper
    assert "v12_output_not_fresh" in wrapper
    assert "sbatch " not in wrapper
