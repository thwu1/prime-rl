from __future__ import annotations

from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v8_supersession as v8
import finalize_kimi_tb4_sandoq_small_v9 as v9
import pytest


def test_v9_contract_binds_execution_and_shared_audit_engine() -> None:
    contract = v9.execution_contract("1234567")

    assert contract == v8.ExecutionContract(
        source_revision="820d5167443913ed5bb2b3d72e16de442caa696a",
        verifiers_commit="36b0dff6c18affb3d40b7c46d5836381d568050b",
        slurm_job_id="1234567",
        plan_sha256="234af70091d5d93c73a3fba82d7215c92ba2f56704507158a91e97f001b1be4e",
        output_name="full-denominator-supersession-v2",
        supersession_reason="fixed-denominator-exact-transport-v9-post-agent-verifier-zero",
        supersession_source_files=v9.SUPERSESSION_SOURCE_FILES,
    )
    assert v9.SUPERSESSION_SOURCE_FILES[0].endswith(
        "finalize_kimi_tb4_sandoq_small_v9.py"
    )
    assert set(v8.SUPERSESSION_SOURCE_FILES) < set(v9.SUPERSESSION_SOURCE_FILES)
    assert v8._validated_execution_contract(contract) is contract


@pytest.mark.parametrize("job_id", ["", "0", "-1", "1.0", "123:4", " 123", "123 "])
def test_v9_contract_rejects_noncanonical_job_ids(job_id: str) -> None:
    with pytest.raises(v9.V9FinalizationError, match="execution_slurm_job_id_invalid"):
        v9.execution_contract(job_id)


def test_v9_wrapper_passes_only_the_bound_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "test"}

    monkeypatch.setattr(v9.engine, "finalize", fake_finalize)
    result = v9.finalize(
        plan_path=Path("/private/v9-plan.json"),
        plan_sha256=v9.EXECUTION_PLAN_SHA256,
        run_dir=Path("/private/v9-run"),
        supersession_source_revision="a" * 40,
        execution_slurm_job_id="7654321",
    )

    assert result == {"state": "test"}
    assert captured == {
        "plan_path": Path("/private/v9-plan.json"),
        "plan_sha256": v9.EXECUTION_PLAN_SHA256,
        "run_dir": Path("/private/v9-run"),
        "supersession_source_revision": "a" * 40,
        "execution_contract": v9.execution_contract("7654321"),
    }


def test_v8_default_contract_remains_immutable() -> None:
    assert v8.V8_EXECUTION_CONTRACT == v8.ExecutionContract(
        source_revision=v8.EXECUTION_SOURCE_REVISION,
        verifiers_commit=v8.EXECUTION_VERIFIERS_COMMIT,
        slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        plan_sha256=v8.EXECUTION_PLAN_SHA256,
        output_name=v8.OUTPUT_NAME,
        supersession_reason=v8.SUPERSESSION_REASON,
        supersession_source_files=v8.SUPERSESSION_SOURCE_FILES,
    )
