from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v14 as v14
import finalize_kimi_tb4_sandoq_small_v15 as v15
import pytest


def test_v15_contract_is_exactly_bound_and_only_v15_uses_v5() -> None:
    contract = v15.execution_contract(v15.EXECUTION_SLURM_JOB_ID)

    assert contract.source_revision == "3a39b16535d4f77ba16336086441373756e29eda"
    assert contract.plan_sha256 == "b89f0892079718fd3aeef7a349831bccf54d5f7385befc299bf898b63800fdcc"
    assert contract.slurm_job_id == "1621240"
    assert contract.plan_verifier == "capacity-bound-v10"
    assert contract.execution_project_root == str(v15.EXECUTION_PROJECT_ROOT)
    assert contract.concurrency == 16
    assert contract.require_persisted_verifier_artifacts is True
    assert contract.allow_exact_length_benchmark_passes is True
    assert contract.allow_post_agent_exec_transport_errors is True
    assert contract.allow_post_agent_artifact_write_transport_errors is True
    assert contract.allow_pre_ready_managed_shell_provisioning_failures is True
    assert contract.stock_endpoint_identifier == "tianhaowu-kimi-k3-stock-rollout-20260929-v5"
    assert contract.stock_source_spec_sha256 == "62055fd847186c47863a01a7f084c7ae950dfa492a5133551d84e71d6e5fbdf9"
    assert contract.stock_endpoint_bundle_sha256 == "56cd938cf32c10f1ee4c580745f71e8862ec3a6186e3f725b510cd4d37fafd5e"
    assert v15.engine._validated_execution_contract(contract) is contract

    v14_contract = v14.execution_contract(v14.EXECUTION_SLURM_JOB_ID)
    assert v14_contract.slurm_job_id == "1618064"
    assert v14_contract.stock_endpoint_identifier == "tianhaowu-kimi-k3-stock-rollout-20260928-v4"


def test_v15_opt_in_requires_capacity_bound_persisted_execution() -> None:
    contract = v15.execution_contract(v15.EXECUTION_SLURM_JOB_ID)
    for changed in (
        replace(contract, plan_verifier="legacy-small-full"),
        replace(contract, require_persisted_verifier_artifacts=False),
        replace(contract, execution_project_root=None),
        replace(contract, allow_pre_ready_managed_shell_provisioning_failures=1),
    ):
        with pytest.raises(v15.engine.V8SupersessionError, match="execution_contract_invalid"):
            v15.engine._validated_execution_contract(changed)


@pytest.mark.parametrize("job_id", ["", "0", "1618064", "1621240 ", "1621240:0"])
def test_v15_contract_rejects_any_other_job(job_id: str) -> None:
    with pytest.raises(v15.V15FinalizationError, match="execution_slurm_job_id_invalid"):
        v15.execution_contract(job_id)


def test_v15_wrapper_passes_only_exact_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v15.engine, "finalize", fake_finalize)
    result = v15.finalize(
        plan_path=v15.EXECUTION_PLAN,
        plan_sha256=v15.EXECUTION_PLAN_SHA256,
        run_dir=v15.EXECUTION_RUN_DIR,
        supersession_source_revision="a" * 40,
        execution_slurm_job_id=v15.EXECUTION_SLURM_JOB_ID,
    )
    assert result == {"state": "test"}
    assert captured["execution_contract"] == v15.execution_contract(v15.EXECUTION_SLURM_JOB_ID)
    for plan_path, plan_sha256, run_dir in (
        (Path("/private/wrong-plan.json"), v15.EXECUTION_PLAN_SHA256, v15.EXECUTION_RUN_DIR),
        (v15.EXECUTION_PLAN, "0" * 64, v15.EXECUTION_RUN_DIR),
        (v15.EXECUTION_PLAN, v15.EXECUTION_PLAN_SHA256, Path("/private/wrong-run")),
    ):
        with pytest.raises(v15.V15FinalizationError, match="execution_artifact_binding_invalid"):
            v15.finalize(
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                run_dir=run_dir,
                supersession_source_revision="a" * 40,
                execution_slurm_job_id=v15.EXECUTION_SLURM_JOB_ID,
            )


def test_v15_batch_wrapper_is_hard_bound_and_does_not_submit() -> None:
    wrapper = (Path(v15.__file__).resolve().parent / "run_finalize_kimi_tb4_sandoq_small_v15.sbatch").read_text()
    assert f"expected_producer_job={v15.EXECUTION_SLURM_JOB_ID}" in wrapper
    assert f"execution_revision={v15.EXECUTION_SOURCE_REVISION}" in wrapper
    assert f"plan_sha256={v15.EXECUTION_PLAN_SHA256}" in wrapper
    assert f"plan={v15.EXECUTION_PLAN}" in wrapper
    assert f"run_dir={v15.EXECUTION_RUN_DIR}" in wrapper
    assert "producer_not_terminal" in wrapper
    assert "v15_output_not_fresh" in wrapper
    assert "KIMI_V15_EXPECTED_PRODUCER_JOB_ID" in wrapper
    assert "KIMI_V15_SUPERSESSION_SOURCE_REVISION" in wrapper
    assert "sbatch " not in wrapper
