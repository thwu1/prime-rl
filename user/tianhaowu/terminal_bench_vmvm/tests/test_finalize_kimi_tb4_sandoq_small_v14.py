from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v13 as v13
import finalize_kimi_tb4_sandoq_small_v14 as v14
import pytest


def test_v14_contract_is_exactly_bound_and_only_v14_opts_in() -> None:
    contract = v14.execution_contract(v14.EXECUTION_SLURM_JOB_ID)

    assert contract.source_revision == "3a39b16535d4f77ba16336086441373756e29eda"
    assert contract.plan_sha256 == "41fc96375ca18a1e1004a4b327953c25090df5539a80da347e85b2e6a00848b6"
    assert contract.slurm_job_id == "1618064"
    assert contract.plan_verifier == "capacity-bound-v10"
    assert contract.execution_project_root == str(v14.EXECUTION_PROJECT_ROOT)
    assert contract.concurrency == 16
    assert contract.require_persisted_verifier_artifacts is True
    assert contract.allow_exact_length_benchmark_passes is True
    assert contract.allow_post_agent_exec_transport_errors is True
    assert contract.allow_post_agent_artifact_write_transport_errors is True
    assert contract.allow_pre_ready_managed_shell_provisioning_failures is True
    assert contract.stock_endpoint_identifier == "tianhaowu-kimi-k3-stock-rollout-20260928-v4"
    assert contract.stock_source_spec_sha256 == "bf15fcaa7979bfef74dd58421ea7e68ef2166f424fc6043f1853d4f829c53f06"
    assert contract.stock_endpoint_bundle_sha256 == "b09a14dc0fa6b67fea3987098eabb4b1660a3fdbbdc49988b8d063db028a8054"
    assert v14.engine._validated_execution_contract(contract) is contract

    assert (
        v13.execution_contract(v13.EXECUTION_SLURM_JOB_ID).allow_pre_ready_managed_shell_provisioning_failures is False
    )


def test_v14_opt_in_requires_capacity_bound_persisted_execution() -> None:
    contract = v14.execution_contract(v14.EXECUTION_SLURM_JOB_ID)
    for changed in (
        replace(contract, plan_verifier="legacy-small-full"),
        replace(contract, require_persisted_verifier_artifacts=False),
        replace(contract, execution_project_root=None),
        replace(contract, allow_pre_ready_managed_shell_provisioning_failures=1),
    ):
        with pytest.raises(v14.engine.V8SupersessionError, match="execution_contract_invalid"):
            v14.engine._validated_execution_contract(changed)


@pytest.mark.parametrize("job_id", ["", "0", "1617454", "1618064 ", "1618064:0"])
def test_v14_contract_rejects_any_other_job(job_id: str) -> None:
    with pytest.raises(v14.V14FinalizationError, match="execution_slurm_job_id_invalid"):
        v14.execution_contract(job_id)


def test_v14_wrapper_passes_only_exact_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v14.engine, "finalize", fake_finalize)
    result = v14.finalize(
        plan_path=v14.EXECUTION_PLAN,
        plan_sha256=v14.EXECUTION_PLAN_SHA256,
        run_dir=v14.EXECUTION_RUN_DIR,
        supersession_source_revision="a" * 40,
        execution_slurm_job_id=v14.EXECUTION_SLURM_JOB_ID,
    )
    assert result == {"state": "test"}
    assert captured["execution_contract"] == v14.execution_contract(v14.EXECUTION_SLURM_JOB_ID)
    for plan_path, plan_sha256, run_dir in (
        (Path("/private/wrong-plan.json"), v14.EXECUTION_PLAN_SHA256, v14.EXECUTION_RUN_DIR),
        (v14.EXECUTION_PLAN, "0" * 64, v14.EXECUTION_RUN_DIR),
        (v14.EXECUTION_PLAN, v14.EXECUTION_PLAN_SHA256, Path("/private/wrong-run")),
    ):
        with pytest.raises(v14.V14FinalizationError, match="execution_artifact_binding_invalid"):
            v14.finalize(
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                run_dir=run_dir,
                supersession_source_revision="a" * 40,
                execution_slurm_job_id=v14.EXECUTION_SLURM_JOB_ID,
            )


def test_v14_batch_wrapper_is_hard_bound_and_does_not_submit() -> None:
    wrapper = (Path(v14.__file__).resolve().parent / "run_finalize_kimi_tb4_sandoq_small_v14.sbatch").read_text()
    assert f"expected_producer_job={v14.EXECUTION_SLURM_JOB_ID}" in wrapper
    assert f"execution_revision={v14.EXECUTION_SOURCE_REVISION}" in wrapper
    assert f"plan_sha256={v14.EXECUTION_PLAN_SHA256}" in wrapper
    assert f"plan={v14.EXECUTION_PLAN}" in wrapper
    assert f"run_dir={v14.EXECUTION_RUN_DIR}" in wrapper
    assert "producer_not_terminal" in wrapper
    assert "v14_output_not_fresh" in wrapper
    assert "KIMI_V14_EXPECTED_PRODUCER_JOB_ID" in wrapper
    assert "KIMI_V14_SUPERSESSION_SOURCE_REVISION" in wrapper
    assert "sbatch " not in wrapper
