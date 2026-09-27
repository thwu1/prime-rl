from __future__ import annotations

import copy
import inspect
from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v7 as v7
import pytest


def test_v7_finalizer_is_the_full_stage_entrypoint() -> None:
    workflow = Path(v7.__file__).resolve().parent
    launcher = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()
    assert 'python3 "$workflow_dir/finalize_kimi_tb4_sandoq_small_v7.py"' in launcher
    assert '--expected-slurm-job-id "$SLURM_JOB_ID"' in launcher


def test_v7_finalizer_requires_every_exact_transport_and_error_audit_gate() -> None:
    source = inspect.getsource(v7.finalize)
    assert "audit_error_model_io=True" in source
    assert "expected_records=plan_module.SUPPORTED_TASKS" in source
    assert 'expected_schema="logical-exact-once-v1"' in source
    assert "expected_summary_records=plan_module.SUPPORTED_TASKS" in source
    assert "allow_terminal_upstream_statuses=True" in source
    assert "_router_transport_binding" in source
    assert v7.OUTPUT_NAME == "full-denominator"


def test_v7_finalizer_rejects_nonstock_identity() -> None:
    identity = {
        "deployment": {
            "spec_sha256": v7.plan_module.STOCK_SOURCE_SPEC_SHA256,
            "endpoint_bundle_sha256": v7.plan_module.STOCK_ENDPOINT_BUNDLE_SHA256,
            "router": {
                "capacity_profile": "sandoq-stock-single-c64-v1",
                "endpoint_identifier": v7.plan_module.STOCK_ENDPOINT_IDENTIFIER,
                "worker_count": 1,
                "provider_concurrency": 64,
                "per_worker_capacity": 64,
            },
        }
    }
    v7._validate_stock_identity(identity)
    changed = copy.deepcopy(identity)
    changed["deployment"]["router"]["capacity_profile"] = "sandoq-c64-w2-v1"
    with pytest.raises(v7.V7FinalizeError, match="stock_identity_invalid"):
        v7._validate_stock_identity(changed)
