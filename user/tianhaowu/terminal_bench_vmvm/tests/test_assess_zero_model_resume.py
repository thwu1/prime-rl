from __future__ import annotations

import json
from pathlib import Path

import pytest

from assess_zero_model_resume import ResumeAssessmentError, assess


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path.resolve()


def _good(index: int) -> dict:
    return {
        "task": {"idx": index},
        "errors": [],
        "nodes": [{"message": {"role": "assistant"}}],
        "rewards": {"solved": 0},
        "metrics": {},
        "info": {},
    }


def _zero_model_error(index: int) -> dict:
    return {
        "task": {"idx": index},
        "errors": ["redacted"],
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "info": {},
    }


def test_complete_results_need_no_resume(tmp_path: Path) -> None:
    assert assess(_write(tmp_path / "results.jsonl", [_good(0), _good(1)]), 2) == {
        "state": "complete",
        "observed_rows": 2,
        "zero_model_error_rows": 0,
        "missing_rows": 0,
    }


def test_missing_and_zero_model_errors_are_retryable(tmp_path: Path) -> None:
    assert assess(_write(tmp_path / "results.jsonl", [_good(0), _zero_model_error(1)]), 3) == {
        "state": "resume_required",
        "observed_rows": 2,
        "zero_model_error_rows": 1,
        "missing_rows": 1,
    }


@pytest.mark.parametrize("field,value", [("nodes", [{}]), ("rewards", {"solved": 0}), ("info", {"x": 1})])
def test_model_bearing_or_ambiguous_error_is_not_retryable(
    tmp_path: Path, field: str, value: object
) -> None:
    row = _zero_model_error(0)
    row[field] = value
    with pytest.raises(ResumeAssessmentError, match="model_bearing_error_not_retryable"):
        assess(_write(tmp_path / "results.jsonl", [row]), 1)


def test_duplicate_task_index_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ResumeAssessmentError, match="resume_results_invalid"):
        assess(_write(tmp_path / "results.jsonl", [_good(0), _good(0)]), 2)
