from __future__ import annotations

from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v10 as v10
import pytest


def test_v10_contract_binds_v9_execution_and_enables_only_length_policy() -> None:
    contract = v10.execution_contract("1608879")

    assert contract.source_revision == "820d5167443913ed5bb2b3d72e16de442caa696a"
    assert contract.verifiers_commit == "36b0dff6c18affb3d40b7c46d5836381d568050b"
    assert contract.plan_sha256 == "234af70091d5d93c73a3fba82d7215c92ba2f56704507158a91e97f001b1be4e"
    assert contract.slurm_job_id == "1608879"
    assert contract.output_name == "full-denominator-supersession-v3"
    assert contract.allow_exact_length_benchmark_passes is True
    assert contract.allow_post_agent_exec_transport_errors is True
    assert v10.engine._validated_execution_contract(contract) is contract
    assert v10.SUPERSESSION_SOURCE_FILES[0].endswith(
        "finalize_kimi_tb4_sandoq_small_v10.py"
    )


@pytest.mark.parametrize(
    "job_id",
    ["", "0", "-1", "1.0", "123:4", " 123", "123 ", "1234567"],
)
def test_v10_contract_rejects_noncanonical_job_ids(job_id: str) -> None:
    with pytest.raises(v10.V10FinalizationError, match="execution_slurm_job_id_invalid"):
        v10.execution_contract(job_id)


def test_v10_wrapper_passes_only_the_bound_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v10.engine, "finalize", fake_finalize)
    result = v10.finalize(
        plan_path=Path("/private/v9-plan.json"),
        plan_sha256=v10.EXECUTION_PLAN_SHA256,
        run_dir=Path("/private/v9-run"),
        supersession_source_revision="a" * 40,
        execution_slurm_job_id="1608879",
    )

    assert result == {"state": "test"}
    assert captured == {
        "plan_path": Path("/private/v9-plan.json"),
        "plan_sha256": v10.EXECUTION_PLAN_SHA256,
        "run_dir": Path("/private/v9-run"),
        "supersession_source_revision": "a" * 40,
        "execution_contract": v10.execution_contract("1608879"),
    }
