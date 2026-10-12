from __future__ import annotations

import copy
import inspect
from pathlib import Path

import finalize_kimi_tb4_sandoq_small_v8_supersession as v8
import pytest


def _event(name: str, assignment: str | None = None, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 2,
        "record_type": "pool_event",
        "event": name,
        "slurm_job_id": v8.EXECUTION_SLURM_JOB_ID,
    }
    if assignment is not None:
        value["assignment_id"] = assignment
    value.update(updates)
    return value


def _released(assignment: str, reason: str) -> dict[str, object]:
    if reason == "initialization_failure":
        return _event(
            "assignment_released",
            assignment,
            reason=reason,
            status="poisoned",
            poisoned=True,
            nested_recycle_verified=False,
            outer_deletion_verified_http_status=404,
            shell_failure_status="initialization_command_failed",
            error="opaque",
        )
    if reason == "managed_shell_lost":
        return _event(
            "assignment_released",
            assignment,
            reason=reason,
            status="poisoned",
            poisoned=True,
            nested_recycle_verified=False,
            outer_deletion_verified_http_status=404,
            shell_failure_status="managed_shell_command_outcome_unknown",
            error="opaque",
        )
    if reason == "gateway_command_outcome_unknown":
        return _event(
            "assignment_released",
            assignment,
            reason=reason,
            status="poisoned",
            poisoned=True,
            nested_recycle_verified=False,
            outer_deletion_verified_http_status=404,
            shell_failure_status="transport_error",
            outer_retired=False,
            shell_deleted=False,
            managed_shell_recovery_count=0,
            cleanup_gateway_retry_count=0,
            cleanup_gateway_retry_exhausted_count=0,
            retirement_reason=None,
            error="opaque",
        )
    return _event(
        "assignment_released",
        assignment,
        reason="rollout_complete",
        status="retired",
        poisoned=False,
        nested_recycle_verified=True,
        outer_deletion_verified_http_status=404,
        shell_failure_status=None,
        error=None,
    )


def _body(*events: dict[str, object]) -> bytes:
    return b"".join(v8.split.canonical_json(event) for event in events)


def _post_agent_row() -> dict[str, object]:
    return {
        "errors": [{"type": "SandboxError"}],
        "info": {"terminal_bench_artifacts": {}},
    }


def _valid_lifecycle() -> tuple[bytes, dict[str, object], dict[str, dict[str, object]]]:
    events = [
        _event("pool_started"),
        _event("pool_recovery_completed"),
        _event("assignment_acquired", "main"),
        _event("assignment_ready", "main"),
        _released("main", "rollout_complete"),
    ]
    for index in range(v8.VERIFIER_ATTEMPTS * v8.PROVISIONING_ATTEMPTS):
        assignment = f"verifier-{index}"
        events.extend(
            [
                _event("assignment_acquired", assignment),
                _released(assignment, "initialization_failure"),
            ]
        )
    events.append(_event("pool_drained"))
    return (
        _body(*events),
        {
            "zero_model_error_zeroes": 0,
            "post_agent_verifier_sandbox_error_zeroes": 1,
            "pre_model_sandoq_provisioning_error_zeroes": 0,
        },
        {"task": _post_agent_row()},
    )


def test_v8_supersession_binds_the_immutable_execution() -> None:
    assert v8.SCHEMA_VERSION == 2
    assert v8.EXECUTION_SOURCE_REVISION == "02ced99650a33f6c548e47569d18587ae4a71a08"
    assert v8.EXECUTION_VERIFIERS_COMMIT == "36b0dff6c18affb3d40b7c46d5836381d568050b"
    assert v8.EXECUTION_SLURM_JOB_ID == "1607011"
    assert v8.EXECUTION_PLAN_SHA256 == "af936100b1cb06e021f98de9900d235a9175e716fd9e9432298889f9ea9d6150"
    assert v8.OUTPUT_NAME != v8.v7.OUTPUT_NAME
    assert v8.SUPERSESSION_SOURCE_FILES
    assert all(path.startswith("user/tianhaowu/terminal_bench_vmvm/") for path in v8.SUPERSESSION_SOURCE_FILES)
    assert "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_miniswe246_union.py" in v8.SUPERSESSION_SOURCE_FILES


def test_v8_assignment_lifecycle_accepts_only_bound_pre_ready_failures() -> None:
    body, trace, rows = _valid_lifecycle()
    result = v8._assignment_lifecycle_audit(
        body,
        expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        trace_audit=trace,
        rows=rows,
        verifier_modes={"task": "separate"},
    )

    assert result == {
        "schema_version": 1,
        "state": "passed",
        "event_log_sha256": v8.recovery._sha256(body),
        "assignments_acquired": 28,
        "assignments_ready": 1,
        "assignment_releases": 28,
        "assignment_cancellations": 0,
        "release_reason_counts": {
            "initialization_failure": 27,
            "rollout_complete": 1,
        },
        "initialization_failure_status_counts": {"initialization_command_failed": 27},
        "required_error_source_initialization_failures": 27,
        "unattributed_initialization_failures": 0,
        "managed_shell_recoveries": 0,
        "managed_shell_abandonments": 0,
        "minimum_ready_terminal": 1,
        "maximum_ready_terminal": 4,
    }


def test_v8_assignment_lifecycle_accepts_exact_managed_shell_loss() -> None:
    body = _body(
        _event("pool_started"),
        _event("pool_recovery_completed"),
        _event("assignment_acquired", "main"),
        _event("assignment_ready", "main"),
        _event("managed_shell_recovered", "main"),
        _event("managed_shell_operation_abandoned", "main"),
        _released("main", "managed_shell_lost"),
        _event("pool_drained"),
    )
    result = v8._assignment_lifecycle_audit(
        body,
        expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        trace_audit={
            "zero_model_error_zeroes": 0,
            "post_agent_verifier_sandbox_error_zeroes": 0,
            "pre_model_sandoq_provisioning_error_zeroes": 0,
        },
        rows={"task": _post_agent_row()},
        verifier_modes={"task": "separate"},
    )
    assert result["release_reason_counts"] == {"managed_shell_lost": 1}
    assert result["managed_shell_recoveries"] == 1
    assert result["managed_shell_abandonments"] == 1


def test_v10_assignment_lifecycle_binds_three_exec_transport_failures() -> None:
    events = [
        _event("pool_started"),
        _event("pool_recovery_completed"),
        _event("assignment_acquired", "agent"),
        _event("assignment_ready", "agent"),
        _released("agent", "rollout_complete"),
    ]
    for index in range(v8.VERIFIER_ATTEMPTS):
        assignment = f"verifier-{index}"
        release = _released(assignment, "managed_shell_lost")
        release["shell_failure_status"] = "managed_shell_recovery_failed"
        events.extend(
            [
                _event("assignment_acquired", assignment),
                _event("assignment_ready", assignment),
                _event(
                    "managed_shell_recovery_failed",
                    assignment,
                    error_type="RuntimeError",
                ),
                release,
            ]
        )
    events.append(_event("pool_drained"))
    result = v8._assignment_lifecycle_audit(
        _body(*events),
        expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        trace_audit={
            "zero_model_error_zeroes": 0,
            "post_agent_verifier_sandbox_error_zeroes": 1,
            "post_agent_verifier_provisioning_error_zeroes": 0,
            "post_agent_verifier_exec_transport_error_zeroes": 1,
            "pre_model_sandoq_provisioning_error_zeroes": 0,
        },
        rows={"task": _post_agent_row()},
        verifier_modes={"task": "separate"},
    )

    assert result["required_exec_transport_ready_terminals"] == 3
    assert result["managed_shell_recovery_failures"] == 3
    assert result["release_reason_counts"] == {
        "managed_shell_lost": 3,
        "rollout_complete": 1,
    }


def test_v12_assignment_lifecycle_binds_exact_artifact_write_attempts() -> None:
    events = [
        _event("pool_started"),
        _event("pool_recovery_completed"),
        _event("assignment_acquired", "agent"),
        _event("assignment_ready", "agent"),
        _released("agent", "rollout_complete"),
    ]
    for index, reason in enumerate(("rollout_complete", "gateway_command_outcome_unknown", "rollout_complete")):
        assignment = f"verifier-{index}"
        events.extend(
            [
                _event("assignment_acquired", assignment),
                _event("assignment_ready", assignment),
                _released(assignment, reason),
            ]
        )
    events.append(_event("pool_drained"))
    result = v8._assignment_lifecycle_audit(
        _body(*events),
        expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        trace_audit={
            "zero_model_error_zeroes": 0,
            "post_agent_verifier_sandbox_error_zeroes": 1,
            "post_agent_verifier_provisioning_error_zeroes": 0,
            "post_agent_verifier_exec_transport_error_zeroes": 0,
            "post_agent_verifier_artifact_write_transport_error_zeroes": 1,
            "pre_model_sandoq_provisioning_error_zeroes": 0,
        },
        rows={"task": _post_agent_row()},
        verifier_modes={"task": "separate"},
    )

    assert result["required_artifact_write_ready_terminals"] == 3
    assert result["required_artifact_write_gateway_unknown_terminals"] == 1
    assert result["release_reason_counts"] == {
        "gateway_command_outcome_unknown": 1,
        "rollout_complete": 3,
    }

    changed = copy.deepcopy(events)
    gateway = next(event for event in changed if event.get("reason") == "gateway_command_outcome_unknown")
    gateway["shell_failure_status"] = "unknown"
    with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_invalid"):
        v8._assignment_lifecycle_audit(
            _body(*changed),
            expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
            trace_audit={
                "zero_model_error_zeroes": 0,
                "post_agent_verifier_sandbox_error_zeroes": 1,
                "post_agent_verifier_provisioning_error_zeroes": 0,
                "post_agent_verifier_exec_transport_error_zeroes": 0,
                "post_agent_verifier_artifact_write_transport_error_zeroes": 1,
                "pre_model_sandoq_provisioning_error_zeroes": 0,
            },
            rows={"task": _post_agent_row()},
            verifier_modes={"task": "separate"},
        )


def test_v8_assignment_lifecycle_fails_closed_on_corruption() -> None:
    body, trace, rows = _valid_lifecycle()
    decoded = [copy.deepcopy(event) for event in map(v8.json.loads, body.splitlines())]
    cases: list[list[dict[str, object]]] = []

    wrong_job = copy.deepcopy(decoded)
    wrong_job[0]["slurm_job_id"] = "999"
    cases.append(wrong_job)
    ready_initialization_failure = copy.deepcopy(decoded)
    ready_initialization_failure.insert(5, _event("assignment_ready", "verifier-0"))
    cases.append(ready_initialization_failure)
    unknown_status = copy.deepcopy(decoded)
    next(event for event in unknown_status if event.get("reason") == "initialization_failure")[
        "shell_failure_status"
    ] = "unknown"
    cases.append(unknown_status)
    missing_terminal = copy.deepcopy(decoded[:-1])
    cases.append(missing_terminal)
    release_failure = copy.deepcopy(decoded)
    release_failure.append(_event("assignment_release_failed", "main"))
    cases.append(release_failure)
    unknown_event = copy.deepcopy(decoded)
    unknown_event.append(_event("unknown_event"))
    cases.append(unknown_event)

    for events in cases:
        with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_invalid"):
            v8._assignment_lifecycle_audit(
                _body(*events),
                expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
                trace_audit=trace,
                rows=rows,
                verifier_modes={"task": "separate"},
            )


def test_v8_post_agent_policy_is_exact_and_nontrainable() -> None:
    trace = {
        "post_agent_verifier_sandbox_error_zeroes": 2,
        "post_agent_verifier_sandbox_error_model_io_turns": 17,
        "post_agent_verifier_sandbox_error_row_set_sha256": "a" * 64,
    }
    assert v8._post_agent_verifier_policy(trace) == {
        "schema_version": 1,
        "state": "enforced",
        "error_type": "SandboxError",
        "stop_condition": "agent_completed",
        "verifier_mode": "separate",
        "verifier_attempts": 3,
        "provisioning_attempts_per_verifier": 9,
        "requires_artifact_manifest": True,
        "requires_exact_model_io_audit": True,
        "requires_assignment_lifecycle_proof": True,
        "counted_as_zero": True,
        "trainable": False,
        "rows": 2,
        "model_io_turns": 17,
        "row_set_sha256": "a" * 64,
    }
    for key, invalid in (
        ("post_agent_verifier_sandbox_error_zeroes", -1),
        ("post_agent_verifier_sandbox_error_model_io_turns", True),
        ("post_agent_verifier_sandbox_error_row_set_sha256", "a" * 40),
    ):
        changed = {**trace, key: invalid}
        with pytest.raises(v8.V8SupersessionError, match="post_agent_verifier_policy_invalid"):
            v8._post_agent_verifier_policy(changed)


def test_v10_post_agent_policy_distinguishes_exec_transport_zeroes() -> None:
    trace = {
        "post_agent_verifier_sandbox_error_zeroes": 2,
        "post_agent_verifier_sandbox_error_model_io_turns": 17,
        "post_agent_verifier_sandbox_error_row_set_sha256": "a" * 64,
        "post_agent_verifier_provisioning_error_zeroes": 1,
        "post_agent_verifier_provisioning_error_row_set_sha256": "b" * 64,
        "post_agent_verifier_exec_transport_error_zeroes": 1,
        "post_agent_verifier_exec_transport_error_row_set_sha256": "c" * 64,
    }

    policy = v8._post_agent_verifier_policy(trace)

    assert policy["schema_version"] == 2
    assert policy["infrastructure_zeroes"] == 2
    assert policy["provisioning_exhaustion_zeroes"] == 1
    assert policy["exec_transport_exhaustion_zeroes"] == 1
    assert policy["exec_transport_attempts_per_row"] == 3
    assert policy["counted_as_zero"] is True
    assert policy["trainable"] is False


def test_v12_post_agent_policy_distinguishes_artifact_write_transport_zeroes() -> None:
    trace = {
        "post_agent_verifier_sandbox_error_zeroes": 3,
        "post_agent_verifier_sandbox_error_model_io_turns": 168,
        "post_agent_verifier_sandbox_error_row_set_sha256": "a" * 64,
        "post_agent_verifier_provisioning_error_zeroes": 1,
        "post_agent_verifier_provisioning_error_row_set_sha256": "b" * 64,
        "post_agent_verifier_exec_transport_error_zeroes": 1,
        "post_agent_verifier_exec_transport_error_row_set_sha256": "c" * 64,
        "post_agent_verifier_artifact_write_transport_error_zeroes": 1,
        "post_agent_verifier_artifact_write_transport_error_row_set_sha256": "d" * 64,
    }

    policy = v8._post_agent_verifier_policy(trace)

    assert policy["schema_version"] == 3
    assert policy["artifact_write_transport_exhaustion_zeroes"] == 1
    assert policy["artifact_write_attempts_per_row"] == 3
    assert policy["requires_persisted_artifact_reopen"] is True
    assert policy["trainable"] is False


def test_v8_pre_model_provisioning_policy_and_lifecycle_source_bound() -> None:
    trace = {
        "pre_model_sandoq_provisioning_error_zeroes": 1,
        "pre_model_sandoq_provisioning_error_row_set_sha256": "b" * 64,
    }
    assert v8._pre_model_sandoq_provisioning_policy(trace) == {
        "schema_version": 1,
        "state": "enforced",
        "error_type": "SandboxError",
        "stop_condition": "error",
        "phase": "agent-runtime-provisioning",
        "provisioning_attempts": 9,
        "requires_empty_model_trace": True,
        "requires_assignment_lifecycle_proof": True,
        "counted_as_zero": True,
        "trainable": False,
        "rows": 1,
        "row_set_sha256": "b" * 64,
    }

    body, lifecycle_trace, rows = _valid_lifecycle()
    lifecycle_trace["pre_model_sandoq_provisioning_error_zeroes"] = 1
    lifecycle_trace["zero_model_error_zeroes"] = 1
    with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_invalid"):
        v8._assignment_lifecycle_audit(
            body,
            expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
            trace_audit=lifecycle_trace,
            rows=rows,
            verifier_modes={"task": "separate"},
        )


def _mixed_pre_model_lifecycle(
    *,
    initialization_failures: int = 8,
    managed_shell_losses: int = 1,
    ready_loss: bool = False,
    recovery_error_type: str = "RuntimeError",
    release_status: str = "poisoned",
) -> tuple[bytes, dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    digest = "a" * 64
    requested_image = f"internal.registry/agent@sha256:{digest}"
    events = [_event("pool_started"), _event("pool_recovery_completed")]
    for index in range(initialization_failures):
        assignment = f"init-{index}"
        events.extend(
            [
                _event("assignment_acquired", assignment, requested_image=requested_image),
                _released(assignment, "initialization_failure"),
            ]
        )
    for index in range(managed_shell_losses):
        assignment = f"lost-{index}"
        release = _released(assignment, "managed_shell_lost")
        release["shell_failure_status"] = "managed_shell_recovery_failed"
        release["status"] = release_status
        events.append(_event("assignment_acquired", assignment, requested_image=requested_image))
        if ready_loss:
            events.append(_event("assignment_ready", assignment))
        events.extend(
            [
                _event(
                    "managed_shell_recovery_failed",
                    assignment,
                    error_type=recovery_error_type,
                ),
                release,
            ]
        )
    events.append(_event("pool_drained"))
    trace = {
        "zero_model_error_zeroes": 1,
        "post_agent_verifier_sandbox_error_zeroes": 0,
        "post_agent_verifier_provisioning_error_zeroes": 0,
        "post_agent_verifier_exec_transport_error_zeroes": 0,
        "post_agent_verifier_artifact_write_transport_error_zeroes": 0,
        "pre_model_sandoq_provisioning_error_zeroes": 1,
    }
    rows = {
        "task": {
            "errors": [{"type": "SandboxError"}],
            "info": {
                "diagnostic_evaluation_disposition": {
                    "kind": "pre-model-sandoq-provisioning-error-counted-as-zero",
                }
            },
        }
    }
    images = {
        "task": {
            "agent": f"public.registry/agent@sha256:{digest}",
            "verifier": f"public.registry/verifier@sha256:{'b' * 64}",
        }
    }
    return _body(*events), trace, rows, images


def test_v14_assignment_lifecycle_accepts_only_digest_bound_mixed_pre_model_attempts() -> None:
    body, trace, rows, images = _mixed_pre_model_lifecycle()
    with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_invalid"):
        v8._assignment_lifecycle_audit(
            body,
            expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
            trace_audit=trace,
            rows=rows,
            verifier_modes={"task": "shared"},
        )

    result = v8._assignment_lifecycle_audit(
        body,
        expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
        trace_audit=trace,
        rows=rows,
        verifier_modes={"task": "shared"},
        allow_pre_ready_managed_shell_provisioning_failures=True,
        task_images=images,
    )
    assert result["release_reason_counts"] == {
        "initialization_failure": 8,
        "managed_shell_lost": 1,
    }
    assert result["required_error_source_initialization_failures"] == 8
    assert result["unattributed_initialization_failures"] == 0
    assert result["pre_model_attempt_attribution"] == {
        "schema_version": 1,
        "state": "image-digest-bound",
        "rows": 1,
        "required_attempts": 9,
        "initialization_failures": 8,
        "pre_ready_managed_shell_losses": 1,
        "pre_model_image_set_sha256": v8.recovery._sha256(
            v8.split.canonical_json(
                [
                    {
                        "agent_image_sha256": "a" * 64,
                        "required_attempts": 9,
                        "rows": 1,
                    }
                ]
            )
        ),
    }


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"initialization_failures": 7}, "assignment_lifecycle_image_binding_invalid"),
        ({"managed_shell_losses": 2}, "assignment_lifecycle_image_binding_invalid"),
        ({"ready_loss": True}, "assignment_lifecycle_image_binding_invalid"),
        ({"recovery_error_type": "ValueError"}, "assignment_lifecycle_invalid"),
        ({"release_status": "retired"}, "assignment_lifecycle_invalid"),
    ],
)
def test_v14_mixed_pre_model_attempts_reject_count_ready_and_status_tamper(
    updates: dict[str, object],
    error: str,
) -> None:
    body, trace, rows, images = _mixed_pre_model_lifecycle(**updates)
    with pytest.raises(v8.V8SupersessionError, match=error):
        v8._assignment_lifecycle_audit(
            body,
            expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
            trace_audit=trace,
            rows=rows,
            verifier_modes={"task": "shared"},
            allow_pre_ready_managed_shell_provisioning_failures=True,
            task_images=images,
        )


def test_v14_mixed_pre_model_attempts_reject_wrong_or_unbound_image() -> None:
    body, trace, rows, images = _mixed_pre_model_lifecycle()
    for changed_images in (
        {"task": {"agent": f"public.registry/agent@sha256:{'c' * 64}", "verifier": images["task"]["verifier"]}},
        {"task": {"agent": "public.registry/agent:mutable", "verifier": images["task"]["verifier"]}},
        {},
    ):
        with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_image_binding_invalid"):
            v8._assignment_lifecycle_audit(
                body,
                expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
                trace_audit=trace,
                rows=rows,
                verifier_modes={"task": "shared"},
                allow_pre_ready_managed_shell_provisioning_failures=True,
                task_images=changed_images,
            )

    events = [copy.deepcopy(event) for event in map(v8.json.loads, body.splitlines())]
    first_acquired = next(event for event in events if event.get("event") == "assignment_acquired")
    first_acquired["requested_image"] = "internal.registry/agent:mutable"
    with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_image_binding_invalid"):
        v8._assignment_lifecycle_audit(
            _body(*events),
            expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
            trace_audit=trace,
            rows=rows,
            verifier_modes={"task": "shared"},
            allow_pre_ready_managed_shell_provisioning_failures=True,
            task_images=images,
        )


def test_v14_mixed_pre_model_attempts_reject_ambiguous_selected_image_role() -> None:
    body, trace, rows, images = _mixed_pre_model_lifecycle()
    rows["other"] = {"errors": [], "info": {}}
    for changed_images in (
        {
            **images,
            "other": {
                "agent": images["task"]["agent"],
                "verifier": f"public.registry/verifier@sha256:{'c' * 64}",
            },
        },
        {
            **images,
            "other": {
                "agent": f"public.registry/agent@sha256:{'c' * 64}",
                "verifier": images["task"]["agent"],
            },
        },
    ):
        with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_image_binding_invalid"):
            v8._assignment_lifecycle_audit(
                body,
                expected_slurm_job_id=v8.EXECUTION_SLURM_JOB_ID,
                trace_audit=trace,
                rows=rows,
                verifier_modes={"task": "shared", "other": "shared"},
                allow_pre_ready_managed_shell_provisioning_failures=True,
                task_images=changed_images,
            )


def test_v14_image_manifest_is_held_and_digest_bound(tmp_path: Path) -> None:
    path = tmp_path / "images.json"
    body = v8.split.canonical_json(
        {
            "images": {
                "task": {
                    "agent": f"public.registry/agent@sha256:{'a' * 64}",
                    "verifier": f"public.registry/verifier@sha256:{'b' * 64}",
                }
            },
            "schema_version": 1,
            "source": "synthetic-test",
        }
    )
    path.write_bytes(body)
    plan = {"source": {"image_manifest": v8.ordinary._artifact_bytes(path, body)}}
    held = v8.split._HeldArtifactSet.create()
    try:
        assert v8._validated_task_images(plan, held) == {
            "task": {
                "agent": f"public.registry/agent@sha256:{'a' * 64}",
                "verifier": f"public.registry/verifier@sha256:{'b' * 64}",
            }
        }
    finally:
        held.close()

    changed = copy.deepcopy(plan)
    changed["source"]["image_manifest"]["sha256"] = "0" * 64
    held = v8.split._HeldArtifactSet.create()
    try:
        with pytest.raises(v8.V8SupersessionError, match="assignment_lifecycle_image_binding_invalid"):
            v8._validated_task_images(changed, held)
    finally:
        held.close()


def test_v14_pre_model_policy_is_opt_in_and_v8_policy_is_unchanged() -> None:
    trace = {
        "pre_model_sandoq_provisioning_error_zeroes": 1,
        "pre_model_sandoq_provisioning_error_row_set_sha256": "b" * 64,
    }
    legacy = v8._pre_model_sandoq_provisioning_policy(trace)
    assert legacy["schema_version"] == 1
    assert "accepted_attempt_release_classes" not in legacy
    assert v8._pre_model_sandoq_provisioning_policy(
        trace,
        allow_pre_ready_managed_shell_provisioning_failures=True,
    ) == {
        **legacy,
        "schema_version": 2,
        "accepted_attempt_release_classes": [
            "initialization_failure",
            "pre_ready_managed_shell_recovery_failed",
        ],
        "pre_ready_managed_shell_loss_requires_recovery_failed": True,
        "requires_agent_image_digest_binding": True,
        "requires_exact_attempt_count_per_row": True,
    }


def test_exact_length_policy_separates_benchmark_and_training_passes() -> None:
    trace = {
        "passes": 7,
        "benchmark_valid_passes": 7,
        "trainable_passes": 6,
        "benchmark_invalid_passing_rows": 0,
        "trace_invalid_scored_rows": 3,
        "trace_invalid_passing_rows": 1,
        "trace_invalid_row_set_sha256": "a" * 64,
        "model_bearing_error_zeroes": 1,
        "exact_length_nontrainable_scored_rows": 3,
        "exact_length_nontrainable_passing_rows": 1,
        "exact_length_nontrainable_nodes": 4,
        "exact_length_nontrainable_row_set_sha256": "a" * 64,
        "exact_length_error_zero_rows": 1,
        "exact_length_error_zero_nodes": 1,
        "exact_length_error_zero_row_set_sha256": "b" * 64,
    }

    policy = v8._exact_length_benchmark_policy(trace)

    assert v8._exact_length_gate_met(trace) is True
    assert policy["benchmark_valid_passes"] == 7
    assert policy["trainable_passes"] == 6
    assert policy["nontrainable_passing_rows"] == 1
    assert policy["trainable"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("benchmark_invalid_passing_rows", 1),
        ("benchmark_valid_passes", 6),
        ("trainable_passes", 7),
        ("exact_length_nontrainable_passing_rows", 4),
        ("exact_length_nontrainable_nodes", 2),
        ("exact_length_error_zero_rows", 2),
        ("exact_length_nontrainable_row_set_sha256", "a" * 40),
    ],
)
def test_exact_length_policy_fails_closed(key: str, value: object) -> None:
    trace = {
        "passes": 7,
        "benchmark_valid_passes": 7,
        "trainable_passes": 6,
        "benchmark_invalid_passing_rows": 0,
        "trace_invalid_scored_rows": 3,
        "trace_invalid_passing_rows": 1,
        "trace_invalid_row_set_sha256": "a" * 64,
        "model_bearing_error_zeroes": 1,
        "exact_length_nontrainable_scored_rows": 3,
        "exact_length_nontrainable_passing_rows": 1,
        "exact_length_nontrainable_nodes": 4,
        "exact_length_nontrainable_row_set_sha256": "a" * 64,
        "exact_length_error_zero_rows": 1,
        "exact_length_error_zero_nodes": 1,
        "exact_length_error_zero_row_set_sha256": "b" * 64,
    }
    trace[key] = value

    with pytest.raises(v8.V8SupersessionError, match="exact_length_benchmark_policy_invalid"):
        v8._exact_length_benchmark_policy(trace)


def test_v8_finalizer_enforces_new_audit_and_certificate_fields() -> None:
    source = inspect.getsource(v8.finalize)
    assert "allow_post_agent_verifier_sandbox_errors=True" in source
    assert "post_agent_verifier_attempts=VERIFIER_ATTEMPTS" in source
    assert "audit_pre_model_sandoq_provisioning_errors=True" in source
    assert "sandoq_provisioning_attempts=PROVISIONING_ATTEMPTS" in source
    assert '"post_agent_verifier_error_policy"' in source
    assert '"pre_model_sandoq_provisioning_error_policy"' in source
    assert '"sandoq_assignment_lifecycle"' in source
    assert '"excluded_post_agent_verifier_sandbox_error_rows"' in source
    assert '"post_agent_verifier_sandbox_error_rows_are_trainable": False' in source
    assert '"results_mutated": False' in source
