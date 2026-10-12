import json
import os
from pathlib import Path

import summarize_qwen_sandoq_diagnostic as diagnostic


def test_summary_is_aggregate_only_and_explicitly_noncertifying(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    task_file = private / "task.txt"
    task_file.write_text("opaque-task\n")
    results = private / "results.jsonl"
    results.write_text(json.dumps({"task": {"slug": "opaque-task"}, "rewards": {"solved": 1}}) + "\n")
    cleanup = private / "cleanup.json"
    cleanup.write_text(
        json.dumps(
            {
                "kind": "sandoq-pool-cleanup",
                "state": "passed",
                "failures": 0,
            }
        )
    )
    output = private / "summary.json"
    observed_contracts = []

    def summarize(*_args, **kwargs):
        observed_contracts.append(kwargs["model_io_contract"])
        return (
            {
                "traces": 1,
                "trace_failures": 0,
                "model_io_turns": 2,
                "problem_counts": {},
            },
            False,
        )

    monkeypatch.setattr(diagnostic, "_summarize_traces", summarize)

    value = diagnostic.summarize(results, task_file, cleanup, output)

    assert value == {
        "schema_version": 1,
        "kind": "qwen-sandoq-noncertifying-diagnostic",
        "certifying": False,
        "state": "passed",
        "traces": 1,
        "model_io_turns": 2,
        "trace_failures": 0,
        "problem_counts": {},
        "reward": 1.0,
        "cleanup_verified": True,
    }
    assert observed_contracts == [diagnostic.QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT]
    assert "opaque-task" not in output.read_text()
    metadata = output.stat()
    assert metadata.st_mode & 0o777 == 0o600
    assert metadata.st_nlink == 1
    assert metadata.st_uid == os.getuid()
