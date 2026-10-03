from __future__ import annotations

import finalize_kimi_tb4_sandoq_small_v4_recovery as recovery
import pytest


def _row(task: str, *, reward: float | None, turns: int, error_type: str | None = None) -> dict:
    nodes = [
        {
            "sampled": True,
            "message": {"role": "assistant", "content": "done", "reasoning_content": "reasoning"},
            "model_io": {"response": {"kind": "exact_provider_json"}},
            "usage": {"completion_tokens": 3},
        }
        for _ in range(turns)
    ]
    error = (
        []
        if error_type is None
        else [{"type": error_type, "message": "redacted failure", "traceback": "redacted traceback"}]
    )
    return {
        "id": f"trace-{task}",
        "task": {"name": f"terminal-bench/{task}"},
        "is_completed": True,
        "stop_condition": "agent_completed" if error_type is None else "error",
        "nodes": nodes,
        "rewards": {} if reward is None else {"solved": reward},
        "metrics": {},
        "info": (
            {"terminal_bench_verifier": {"mode": "separate"}}
            if error_type is None
            else ({"terminal_bench_artifacts": {"sha256": "a" * 64}} if turns else {})
        ),
        "errors": error,
    }


def _body(*rows: dict) -> bytes:
    return b"".join(recovery.split.canonical_json(row) for row in rows)


def _exec_transport_error_row(*, stop_condition: str = "agent_completed") -> dict:
    row = _row("transport", reward=None, turns=1, error_type="SandboxError")
    row["stop_condition"] = stop_condition
    row["info"] = {
        "terminal_bench_artifacts": {
            "bytes": 8,
            "sha256": "a" * 64,
            "captured": {"main": ["/workspace/output"]},
            "missing": [],
            "collect": [
                {
                    "attempts": 1,
                    "exit_code": 0,
                    "output_tail": "",
                    "service": "main",
                }
            ],
        }
    }
    detail = sorted(recovery.POST_AGENT_EXEC_TRANSPORT_FAILURES)[0]
    row["errors"] = [
        {
            "type": "SandboxError",
            "message": (
                "terminal-bench/transport: verifier VMVM failed after 3 attempts: "
                + "; ".join(f"attempt {attempt}: Sandoq exec failed: {detail}" for attempt in range(1, 4))
            ),
            "traceback": ('in solved\nin _score_separate\nin run\nraise SandboxError(f"Sandoq exec failed: {error}")'),
        }
    ]
    return row


def _artifact_write_transport_error_row() -> dict:
    row = _row("artifact-write", reward=None, turns=1, error_type="SandboxError")
    row["stop_condition"] = "agent_completed"
    row["info"] = {
        "terminal_bench_artifacts": {
            "bytes": 8,
            "sha256": "a" * 64,
            "captured": {"main": ["/workspace/output"]},
            "missing": [],
            "collect": [
                {
                    "attempts": 1,
                    "exit_code": 0,
                    "output_tail": "",
                    "service": "main",
                }
            ],
            "persistence": {},
        }
    }
    write = f"write '{recovery.POST_AGENT_ARTIFACT_WRITE_PATH}': "
    http_500 = recovery.POST_AGENT_ARTIFACT_WRITE_HTTP_500_DETAIL
    message = (
        "terminal-bench/artifact-write: verifier VMVM failed after 3 attempts: "
        f"attempt 1: {write}OCI runner /v1/exec failed on assignment-{'a' * 32}: {http_500}; "
        f"attempt 2: {write}{recovery.POST_AGENT_ARTIFACT_WRITE_TRANSPORT_DETAIL}; "
        f"attempt 3: {write}OCI runner /v1/exec failed on assignment-{'b' * 32}: {http_500}"
    )
    root = "/execution"
    row["errors"] = [
        {
            "type": "SandboxError",
            "message": message,
            "traceback": (
                f'Traceback (most recent call last):\n  File "{root}/deps/verifiers/verifiers/v1/'
                'rollout.py", line 273, in run\n  File "'
                f'{root}/deps/verifiers/verifiers/v1/taskset.py"'
                ', line 143, in score\n  File "'
                f'{root}/user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py"'
                ', line 4833, in solved\n  File "'
                f'{root}/user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py"'
                ", line 4776, in _score_separate\n    raise SandboxError(\n"
                f"verifiers.v1.errors.SandboxError: {message}\n"
            ),
        }
    ]
    return row


def test_fixed_denominator_audit_keeps_clean_rows_and_marks_errors_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: [])
    clean = _row("clean", reward=1.0, turns=1)
    zero_model = _row("zero", reward=None, turns=0, error_type="SandboxError")
    model_bearing = _row("bearing", reward=None, turns=2, error_type="HarnessError")

    summary, rows = recovery._audit_supported_rows(
        _body(clean, zero_model, model_bearing),
        ("clean", "zero", "bearing"),
        {"clean": "separate", "zero": "separate", "bearing": "separate"},
    )

    assert summary["passes"] == 1
    assert summary["clean_scored_rows"] == 1
    assert summary["zero_model_error_zeroes"] == 1
    assert summary["model_bearing_error_zeroes"] == 1
    assert summary["execution_error_zeroes"] == 2
    assert summary["error_type_counts"] == {"HarnessError": 1, "SandboxError": 1}
    assert rows["clean"] == clean
    assert rows["zero"]["rewards"] == {"solved": 0}
    assert rows["bearing"]["rewards"] == {"solved": 0}
    assert rows["zero"]["info"]["diagnostic_evaluation_disposition"]["zero_model"] is True
    assert rows["bearing"]["info"]["diagnostic_evaluation_disposition"]["trainable"] is False


def test_fixed_denominator_audit_rejects_malformed_or_scored_error_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: [])
    scored_error = _row("bad", reward=None, turns=1, error_type="SandboxError")
    scored_error["rewards"] = {"solved": 0}
    with pytest.raises(recovery.V4RecoveryError, match="error_row_invalid"):
        recovery._audit_supported_rows(
            _body(scored_error),
            ("bad",),
            {"bad": "separate"},
        )

    malformed = _row("bad", reward=None, turns=1, error_type="SandboxError")
    malformed["errors"][0]["opaque"] = True
    with pytest.raises(recovery.V4RecoveryError, match="error_row_invalid"):
        recovery._audit_supported_rows(
            _body(malformed),
            ("bad",),
            {"bad": "separate"},
        )


def test_exact_length_policy_counts_benchmark_pass_but_excludes_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("length", reward=1.0, turns=1)
    problems = [
        "node_0_finish_reason_invalid",
        "node_0_model_io_response_finish_reason_invalid",
    ]
    monkeypatch.setattr(recovery.audit_traces, "_audit_trace", lambda *args, **kwargs: problems)
    monkeypatch.setattr(
        recovery.audit_traces,
        "_exact_length_termination_nodes",
        lambda *args, **kwargs: (0,),
    )

    summary, rows = recovery._audit_supported_rows(
        _body(row),
        ("length",),
        {"length": "separate"},
        allow_nontrainable_scored_rows=True,
        allow_exact_length_benchmark_rows=True,
    )

    assert summary["passes"] == 1
    assert summary["benchmark_valid_passes"] == 1
    assert summary["trainable_passes"] == 0
    assert summary["benchmark_invalid_passing_rows"] == 0
    assert summary["exact_length_nontrainable_passing_rows"] == 1
    assert rows["length"]["info"]["diagnostic_evaluation_disposition"]["trainable"] is False
    assert rows["length"]["nodes"] == row["nodes"]


def test_exact_length_policy_rejects_every_unrecognized_trace_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("bad", reward=1.0, turns=1)
    monkeypatch.setattr(
        recovery.audit_traces,
        "_audit_trace",
        lambda *args, **kwargs: ["node_0_model_io_response_message_mismatch"],
    )
    monkeypatch.setattr(
        recovery.audit_traces,
        "_exact_length_termination_nodes",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(recovery.V4RecoveryError, match="provider_trace_audit_failed"):
        recovery._audit_supported_rows(
            _body(row),
            ("bad",),
            {"bad": "separate"},
            allow_nontrainable_scored_rows=True,
            allow_exact_length_benchmark_rows=True,
        )


@pytest.mark.parametrize("stop_condition", ["agent_completed", "max_total_tokens"])
def test_exec_transport_exhaustion_is_an_exact_nontrainable_infrastructure_zero(
    monkeypatch: pytest.MonkeyPatch,
    stop_condition: str,
) -> None:
    row = _exec_transport_error_row(stop_condition=stop_condition)
    assert recovery._post_agent_verifier_exec_transport_error(
        row,
        verifier_mode="separate",
        verifier_attempts=3,
    )
    monkeypatch.setattr(
        recovery.audit_traces,
        "_audit_trace",
        lambda *args, **kwargs: ["trace_has_errors"],
    )

    summary, rows = recovery._audit_supported_rows(
        _body(row),
        ("transport",),
        {"transport": "separate"},
        allow_nontrainable_scored_rows=True,
        audit_error_model_io=True,
        allow_post_agent_verifier_sandbox_errors=True,
        post_agent_verifier_attempts=3,
        audit_pre_model_sandoq_provisioning_errors=True,
        sandoq_provisioning_attempts=9,
        allow_exact_length_benchmark_rows=True,
        allow_post_agent_exec_transport_errors=True,
    )

    assert summary["passes"] == 0
    assert summary["scored_rows"] == 0
    assert summary["execution_error_zeroes"] == 1
    assert summary["post_agent_verifier_exec_transport_error_zeroes"] == 1
    disposition = rows["transport"]["info"]["diagnostic_evaluation_disposition"]
    assert disposition["infrastructure_class"] == "separate-verifier-exec-transport-exhausted"
    assert disposition["trainable"] is False
    assert rows["transport"]["rewards"] == {"solved": 0}


@pytest.mark.parametrize(
    ("mutation", "mode", "attempts"),
    [
        ("reward", "separate", 3),
        ("stop", "separate", 3),
        ("message", "separate", 3),
        ("artifact", "separate", 3),
        ("traceback", "separate", 3),
        ("none", "shared", 3),
        ("none", "separate", 2),
    ],
)
def test_exec_transport_exhaustion_rejects_broader_shapes(
    mutation: str,
    mode: str,
    attempts: int,
) -> None:
    row = _exec_transport_error_row()
    if mutation == "reward":
        row["rewards"] = {"solved": 0}
    elif mutation == "stop":
        row["stop_condition"] = "error"
    elif mutation == "message":
        row["errors"][0]["message"] += " unexpected"
    elif mutation == "artifact":
        row["info"]["terminal_bench_artifacts"]["opaque"] = True
    elif mutation == "traceback":
        row["errors"][0]["traceback"] = "raise SandboxError"

    assert not recovery._post_agent_verifier_exec_transport_error(
        row,
        verifier_mode=mode,
        verifier_attempts=attempts,
    )


def test_artifact_write_transport_exhaustion_is_exact_persisted_infrastructure_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _artifact_write_transport_error_row()
    assert recovery._post_agent_verifier_artifact_write_transport_error(
        row,
        verifier_mode="separate",
        verifier_attempts=3,
        execution_project_root="/execution",
    )
    monkeypatch.setattr(
        recovery.audit_traces,
        "_audit_trace",
        lambda *args, **kwargs: ["trace_has_errors"],
    )

    summary, rows = recovery._audit_supported_rows(
        _body(row),
        ("artifact-write",),
        {"artifact-write": "separate"},
        allow_nontrainable_scored_rows=True,
        audit_error_model_io=True,
        allow_post_agent_verifier_sandbox_errors=True,
        post_agent_verifier_attempts=3,
        audit_pre_model_sandoq_provisioning_errors=True,
        sandoq_provisioning_attempts=9,
        allow_exact_length_benchmark_rows=True,
        allow_post_agent_exec_transport_errors=True,
        allow_post_agent_artifact_write_transport_errors=True,
        require_persisted_verifier_artifacts=True,
        execution_project_root="/execution",
    )

    assert summary["post_agent_verifier_artifact_write_transport_error_zeroes"] == 1
    assert summary["post_agent_verifier_exec_transport_error_zeroes"] == 0
    disposition = rows["artifact-write"]["info"]["diagnostic_evaluation_disposition"]
    assert disposition["infrastructure_class"] == ("separate-verifier-artifact-write-transport-exhausted")
    assert disposition["trainable"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "shared",
        "attempts",
        "stop",
        "reward",
        "no-persistence",
        "write-path",
        "http-body",
        "transport-replay",
        "same-assignment",
        "traceback-root",
        "traceback-message",
    ],
)
def test_artifact_write_transport_exhaustion_rejects_every_broader_shape(
    mutation: str,
) -> None:
    row = _artifact_write_transport_error_row()
    mode = "separate"
    attempts = 3
    root = "/execution"
    if mutation == "shared":
        mode = "shared"
    elif mutation == "attempts":
        attempts = 2
    elif mutation == "stop":
        row["stop_condition"] = "max_total_tokens"
    elif mutation == "reward":
        row["rewards"] = {"solved": 0}
    elif mutation == "no-persistence":
        del row["info"]["terminal_bench_artifacts"]["persistence"]
    elif mutation == "write-path":
        row["errors"][0]["message"] = row["errors"][0]["message"].replace(
            "terminal-bench-artifacts-0.tgz",
            "other.tgz",
            1,
        )
    elif mutation == "http-body":
        row["errors"][0]["message"] = row["errors"][0]["message"].replace(
            "argument list too long",
            "other failure",
            1,
        )
    elif mutation == "transport-replay":
        row["errors"][0]["message"] = row["errors"][0]["message"].replace(
            "was not replayed",
            "was replayed",
        )
    elif mutation == "same-assignment":
        row["errors"][0]["message"] = row["errors"][0]["message"].replace(
            "assignment-" + "b" * 32,
            "assignment-" + "a" * 32,
        )
    elif mutation == "traceback-root":
        root = "/wrong"
    elif mutation == "traceback-message":
        row["errors"][0]["traceback"] += "unexpected"

    assert not recovery._post_agent_verifier_artifact_write_transport_error(
        row,
        verifier_mode=mode,
        verifier_attempts=attempts,
        execution_project_root=root,
    )


def test_legacy_contract_diff_is_only_truthful_v4_fields() -> None:
    legacy = recovery._legacy_contracts()
    assert legacy["model_io_response_kind"] == "normalized_stream_response"
    assert "verifier_runtime_retries" not in legacy
    assert "retry_shared_verifier_scoring" not in legacy
    assert "provisioning_retries" not in legacy
    current = recovery.plan_module._contracts()
    assert current["model_io_response_kind"] == "exact_provider_json"
    assert current["verifier_runtime_retries"] == 2
    assert current["retry_shared_verifier_scoring"] is True
    assert current["provisioning_retries"] == 8
