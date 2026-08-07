from __future__ import annotations

import json
from pathlib import Path

import materialize_known_cost_promotion as promotion
import pytest


def _initial_smoke_intent() -> dict:
    filenames = list(promotion._expected_arm_filenames())
    smoke = list(promotion.SMOKE_ARM_FILENAMES)
    return {
        "schema_version": promotion.launch.SCHEMA_VERSION,
        "artifact_type": promotion.launch.ARTIFACT_TYPE,
        "study_id": promotion.STUDY_ID,
        "preregistered_decision": {
            "eligible_design": "four_arm_smoke_screen",
            "eligible_arm_count": 4,
            "eligible_arm_filenames": smoke,
        },
        "eligible_runs": [{"arm_filename": filename} for filename in smoke],
        "arm_inventory": [
            {
                "arm_filename": filename,
                "decision_status": "eligible" if filename in smoke else "excluded",
            }
            for filename in filenames
        ],
    }


def _target(clock_type: str, target: int, value: float) -> dict:
    return {
        "clock_type": clock_type,
        "target": target,
        "value": value,
        "passes": value >= 0.02,
    }


def _decision(first_values: list[float], second_values: list[float]) -> dict:
    per_dose = []
    qualifying = []
    for dose, values in zip(promotion.SMOKE_DOSES, (first_values, second_values), strict=True):
        targets = [
            _target(clock_type, target, value)
            for (clock_type, target), value in zip(
                promotion.REQUIRED_SMOKE_CLOCKS,
                values,
                strict=True,
            )
        ]
        passes_all = all(target["passes"] for target in targets)
        if passes_all:
            qualifying.append(dose)
        per_dose.append(
            {
                "nominal_p": dose,
                "targets": targets,
                "passes_all_required_clocks": passes_all,
            }
        )
    return {
        "rule_id": promotion.RESULT_RULE_ID,
        "constants": {
            "block_seed": 20260808,
            "doses": list(promotion.SMOKE_DOSES),
            "threshold": 0.02,
            "comparison": "D_A = L_A(persistent_tag_T) - L_A(hidden_group_G)",
            "L_definition": "mean(selected two tags) - mean(unselected four tags), paired by source",
            "operation_band": "op21_40",
            "required_clocks": [
                {"clock_type": clock_type, "target": target} for clock_type, target in promotion.REQUIRED_SMOKE_CLOCKS
            ],
            "require_same_dose_across_all_clocks": True,
            "threshold_uses_unrounded_values": True,
        },
        "per_dose": per_dose,
        "qualifying_doses": qualifying,
        "proceed_to_full_grid": bool(qualifying),
        "applicable": True,
        "decision_status": "proceed_to_full_grid" if qualifying else "stop_after_smoke",
    }


def test_authority_requires_exact_smoke_partition_and_freezes_remaining_26() -> None:
    intent = _initial_smoke_intent()

    promotion._validate_initial_smoke_partition(intent)
    remaining = promotion.remaining_arm_filenames()

    assert len(remaining) == 26
    assert not set(remaining) & set(promotion.SMOKE_ARM_FILENAMES)
    assert set(remaining) | set(promotion.SMOKE_ARM_FILENAMES) == set(promotion._expected_arm_filenames())

    full = {**intent, "preregistered_decision": {**intent["preregistered_decision"]}}
    full["preregistered_decision"]["eligible_design"] = "full_30_arm_grid"
    with pytest.raises(ValueError, match="only for the four-arm smoke decision"):
        promotion._validate_initial_smoke_partition(full)

    changed = _initial_smoke_intent()
    first_remaining = promotion.remaining_arm_filenames()[0]
    next(item for item in changed["arm_inventory"] if item["arm_filename"] == first_remaining)["decision_status"] = (
        "eligible"
    )
    with pytest.raises(ValueError, match="partition is wrong"):
        promotion._validate_initial_smoke_partition(changed)


def test_initial_intent_runs_its_own_recorded_read_only_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run-root"
    validator = tmp_path / "pinned-source" / "user" / "tianhaowu" / "rsci" / "materialize_known_cost_boundary_launch.py"
    validator.parent.mkdir(parents=True)
    validator.write_text("# pinned validator\n", encoding="utf-8")
    validator.chmod(0o444)
    intent = {
        **_initial_smoke_intent(),
        "inputs": {
            "run_root": str(run_root.resolve()),
            "tokenizer_path": str((tmp_path / "tokenizer").resolve()),
        },
        "implementation": promotion.file_identity(validator),
    }
    intent["payload_without_self_hash_sha256"] = promotion.canonical_json_sha256(intent)
    intent_path = run_root / promotion.launch.INTENT_NAME
    run_root.mkdir()
    intent_path.write_bytes(promotion.canonical_json_bytes(intent))
    intent_path.chmod(0o444)
    calls = []

    def validate(path: Path, arguments: list[str]) -> dict:
        calls.append((path, arguments))
        return {
            "command": "validate",
            "intent": promotion.file_identity(intent_path),
            "eligible_design": "four_arm_smoke_screen",
            "eligible_arm_count": 4,
            "submission_performed": False,
        }

    monkeypatch.setattr(promotion, "_run_recorded_validator", validate)

    result = promotion._validated_initial_intent(intent_path)

    assert result["validator"] == promotion.file_identity(validator)
    assert calls == [
        (
            validator.resolve(),
            [
                "validate",
                "--intent",
                str(intent_path.resolve()),
                "--tokenizer",
                str((tmp_path / "tokenizer").resolve()),
            ],
        )
    ]


def test_bound_preflight_accepts_canonical_object_order(tmp_path: Path) -> None:
    expected = promotion._expected_arm_filenames()
    report = {
        "config_audit": {
            "arm_count": len(expected),
            "arms": {filename: {} for filename in expected},
        }
    }
    report["payload_without_self_hash_sha256"] = promotion.canonical_json_sha256(report)
    path = tmp_path / "report.json"
    path.write_bytes(promotion.canonical_json_bytes(report))

    _, canonical = promotion.read_canonical_json(path)
    assert tuple(canonical["config_audit"]["arms"]) != expected
    initial = {
        "intent": {
            "production_preflight": {
                "report": promotion.file_identity(path),
            }
        }
    }

    validated = promotion._validated_bound_preflight(initial)

    assert set(validated["arms"]) == set(expected)


def test_pre_rl_observation_binds_stage1_lock_markers_and_zero_scheduler_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "stage1-state"
    state_root.mkdir()
    (state_root / promotion.stage1_dispatch.STATE_LOCK_NAME).touch()
    monkeypatch.setattr(promotion.launch, "REQUIRED_DISPATCH_STATE_ROOT", state_root)
    intent = _initial_smoke_intent()
    for index, run in enumerate(intent["eligible_runs"]):
        output_dir = tmp_path / f"smoke-{index}"
        output_dir.mkdir()
        run.update(
            {
                "output_dir": str(output_dir.resolve()),
                "job_name": f"rsci-smoke-{index}",
            }
        )
    names = sorted(run["job_name"] for run in intent["eligible_runs"])
    name_filter = ",".join(names)
    start_time = "2026-07-08T00:00:00"
    observation = {
        "schema_version": 1,
        "observed_at": "2026-08-07T00:00:00Z",
        "initial_dispatch_lock": str(state_root / promotion.stage1_dispatch.STATE_LOCK_NAME),
        "lock_held_through_authority_write": True,
        "state_and_run_scan": {
            "initial_dispatch_state_root": str(state_root),
            "initial_dispatch_state_root_exists": True,
            "state_root_entries": [promotion.stage1_dispatch.STATE_LOCK_NAME],
            "smoke_run_start_markers": {
                run["arm_filename"]: {
                    "output_dir": run["output_dir"],
                    "start_markers": [],
                }
                for run in intent["eligible_runs"]
            },
        },
        "scheduler_scan": {
            "job_names": names,
            "start_time": start_time,
            "squeue_command": [
                "squeue",
                "--noheader",
                "--name",
                name_filter,
                f"--format={promotion.stage1_dispatch.SQUEUE_FORMAT}",
            ],
            "squeue_stdout_sha256": "a" * 64,
            "sacct_command": [
                "sacct",
                "--noheader",
                "--parsable2",
                "--allocations",
                "--name",
                name_filter,
                "--starttime",
                start_time,
                f"--format={promotion.stage1_dispatch.SACCT_FORMAT}",
            ],
            "sacct_stdout_sha256": "b" * 64,
            "matching_job_count": 0,
        },
    }
    canonical_observation = json.loads(promotion.canonical_json_bytes(observation))

    assert promotion._validate_pre_rl_observation(canonical_observation, intent) == canonical_observation

    observed_job = {
        **canonical_observation,
        "scheduler_scan": {**canonical_observation["scheduler_scan"]},
    }
    observed_job["scheduler_scan"]["matching_job_count"] = 1
    with pytest.raises(ValueError, match="zero exact smoke jobs"):
        promotion._validate_pre_rl_observation(observed_job, intent)


def test_pre_rl_helper_must_content_match_initial_recorded_dispatcher(tmp_path: Path) -> None:
    initial_dispatcher = tmp_path / "initial_dispatcher.py"
    promotion_dispatcher = tmp_path / "promotion_dispatcher.py"
    initial_dispatcher.write_text("# exact stage1 helper\n", encoding="utf-8")
    promotion_dispatcher.write_text("# exact stage1 helper\n", encoding="utf-8")
    intent = {
        "control_plane_source": {
            "implementations": {
                "dispatcher": promotion.file_identity(initial_dispatcher),
            }
        }
    }

    assert (
        promotion._validate_stage1_dispatcher_content(intent, promotion_dispatcher)["sha256"]
        == promotion.file_identity(initial_dispatcher)["sha256"]
    )

    promotion_dispatcher.write_text("# changed helper semantics\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stage1 dispatcher helper content differs"):
        promotion._validate_stage1_dispatcher_content(intent, promotion_dispatcher)


def test_smoke_spending_rule_requires_one_same_dose_to_pass_all_four_clocks() -> None:
    proceed = _decision(
        [0.021, 0.025, 0.020, 0.031],
        [0.010, 0.030, 0.040, 0.050],
    )
    stopped = _decision(
        [0.021, 0.025, 0.019, 0.031],
        [0.010, 0.030, 0.040, 0.019],
    )

    assert promotion._validate_smoke_spend_decision(proceed)["qualifying_doses"] == [0.0125]
    assert promotion._validate_smoke_spend_decision(stopped)["proceed_to_full_grid"] is False

    mixed_dose_hack = _decision(
        [0.021, 0.025, 0.019, 0.031],
        [0.010, 0.030, 0.040, 0.019],
    )
    mixed_dose_hack["qualifying_doses"] = [0.0125]
    mixed_dose_hack["proceed_to_full_grid"] = True
    with pytest.raises(ValueError, match="qualifying doses are inconsistent"):
        promotion._validate_smoke_spend_decision(mixed_dose_hack)

    wrong_pass = _decision([0.021] * 4, [0.0] * 4)
    wrong_pass["per_dose"][0]["targets"][0]["passes"] = False
    with pytest.raises(ValueError, match="pass flag is inconsistent"):
        promotion._validate_smoke_spend_decision(wrong_pass)


def test_promotion_artifacts_are_canonical_read_only_and_write_once(tmp_path: Path) -> None:
    run_root = tmp_path / "run-root"
    authority = {
        "inputs": {"run_root": str(run_root.resolve())},
        "value": 1,
    }
    path = run_root / promotion.AUTHORITY_NAME

    identity = promotion.write_promotion_authority(path, authority)

    assert identity == promotion.file_identity(path)
    assert path.read_bytes() == promotion.canonical_json_bytes(authority)
    assert path.stat().st_mode & 0o222 == 0
    assert promotion.write_promotion_authority(path, authority) == identity
    with pytest.raises(FileExistsError, match="different immutable artifact"):
        promotion.write_promotion_authority(path, {**authority, "value": 2})
