import importlib.util
import json
from pathlib import Path

import pytest

RUN_ORACLE = Path(__file__).parents[1] / "run_oracle.py"
SPEC = importlib.util.spec_from_file_location("terminal_bench_vmvm_run_oracle", RUN_ORACLE)
assert SPEC is not None and SPEC.loader is not None
run_oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_oracle)


def test_oracle_network_semantics_are_immutable_and_resumable(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }

    assert run_oracle._bind_oracle_network_semantics(tmp_path, "public") == expected
    assert json.loads((tmp_path / "oracle_network_semantics.json").read_text()) == expected
    assert run_oracle._bind_oracle_network_semantics(tmp_path, "public") == expected

    with pytest.raises(SystemExit, match="semantics mismatch"):
        run_oracle._bind_oracle_network_semantics(tmp_path, "declared")


def test_oracle_network_semantics_reject_unlabeled_results(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "legacy.json").write_text("{}\n")

    with pytest.raises(SystemExit, match="no immutable network-semantics label"):
        run_oracle._bind_oracle_network_semantics(tmp_path, "declared")


def test_oracle_summary_contains_network_semantics() -> None:
    semantics = run_oracle._oracle_network_semantics("public")
    summary = run_oracle._summary(
        [{"valid": True, "reason": "valid"}, {"valid": False, "reason": "invalid"}],
        2,
        semantics,
    )

    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["oracle_network_semantics"] == semantics
