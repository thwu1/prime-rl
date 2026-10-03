from __future__ import annotations

from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v12 as v12
import finalize_kimi_tb4_sandoq_small_v13 as v13
import pytest


def test_v13_contract_is_exactly_bound_and_preserves_v12_policy() -> None:
    contract = v13.execution_contract(v13.EXECUTION_SLURM_JOB_ID)

    assert contract.source_revision == "3a39b16535d4f77ba16336086441373756e29eda"
    assert contract.plan_sha256 == "41fc96375ca18a1e1004a4b327953c25090df5539a80da347e85b2e6a00848b6"
    assert contract.slurm_job_id == "1618064"
    assert contract.plan_verifier == "capacity-bound-v10"
    assert contract.execution_project_root == str(v13.EXECUTION_PROJECT_ROOT)
    assert contract.concurrency == 16
    assert contract.require_persisted_verifier_artifacts is True
    assert contract.allow_exact_length_benchmark_passes is True
    assert contract.allow_post_agent_exec_transport_errors is True
    assert contract.allow_post_agent_artifact_write_transport_errors is True
    assert contract.stock_endpoint_identifier == "tianhaowu-kimi-k3-stock-rollout-20260928-v4"
    assert contract.stock_source_spec_sha256 == "bf15fcaa7979bfef74dd58421ea7e68ef2166f424fc6043f1853d4f829c53f06"
    assert contract.stock_endpoint_bundle_sha256 == "b09a14dc0fa6b67fea3987098eabb4b1660a3fdbbdc49988b8d063db028a8054"
    assert v13.engine._validated_execution_contract(contract) is contract

    legacy = v12.execution_contract(v12.EXECUTION_SLURM_JOB_ID)
    assert legacy.source_revision == v12.EXECUTION_SOURCE_REVISION
    assert legacy.plan_sha256 == v12.EXECUTION_PLAN_SHA256
    assert legacy.slurm_job_id == v12.EXECUTION_SLURM_JOB_ID


@pytest.mark.parametrize("job_id", ["", "0", "1617454", "1618064 ", "1618064:0"])
def test_v13_contract_rejects_any_other_job(job_id: str) -> None:
    with pytest.raises(v13.V13FinalizationError, match="execution_slurm_job_id_invalid"):
        v13.execution_contract(job_id)


def test_v13_wrapper_passes_only_exact_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v13.engine, "finalize", fake_finalize)
    result = v13.finalize(
        plan_path=v13.EXECUTION_PLAN,
        plan_sha256=v13.EXECUTION_PLAN_SHA256,
        run_dir=v13.EXECUTION_RUN_DIR,
        supersession_source_revision="a" * 40,
        execution_slurm_job_id=v13.EXECUTION_SLURM_JOB_ID,
    )
    assert result == {"state": "test"}
    assert captured["execution_contract"] == v13.execution_contract(v13.EXECUTION_SLURM_JOB_ID)
    for plan_path, plan_sha256, run_dir in (
        (Path("/private/wrong-plan.json"), v13.EXECUTION_PLAN_SHA256, v13.EXECUTION_RUN_DIR),
        (v13.EXECUTION_PLAN, "0" * 64, v13.EXECUTION_RUN_DIR),
        (v13.EXECUTION_PLAN, v13.EXECUTION_PLAN_SHA256, Path("/private/wrong-run")),
    ):
        with pytest.raises(v13.V13FinalizationError, match="execution_artifact_binding_invalid"):
            v13.finalize(
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                run_dir=run_dir,
                supersession_source_revision="a" * 40,
                execution_slurm_job_id=v13.EXECUTION_SLURM_JOB_ID,
            )


def test_v13_batch_wrapper_is_hard_bound_and_does_not_submit() -> None:
    wrapper = (Path(v13.__file__).resolve().parent / "run_finalize_kimi_tb4_sandoq_small_v13.sbatch").read_text()
    assert f"expected_producer_job={v13.EXECUTION_SLURM_JOB_ID}" in wrapper
    assert f"execution_revision={v13.EXECUTION_SOURCE_REVISION}" in wrapper
    assert f"plan_sha256={v13.EXECUTION_PLAN_SHA256}" in wrapper
    assert f"plan={v13.EXECUTION_PLAN}" in wrapper
    assert f"run_dir={v13.EXECUTION_RUN_DIR}" in wrapper
    assert "producer_not_terminal" in wrapper
    assert "v13_output_not_fresh" in wrapper
    assert "KIMI_V13_EXPECTED_PRODUCER_JOB_ID" in wrapper
    assert "KIMI_V13_SUPERSESSION_SOURCE_REVISION" in wrapper
    assert "sbatch " not in wrapper
