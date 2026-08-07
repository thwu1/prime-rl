from __future__ import annotations

import copy
from pathlib import Path

import materialize_known_cost_postrun_authority as authority
import pytest


def _partition_intent(design: str) -> dict[str, object]:
    all_filenames = list(authority.expected_arm_filenames())
    eligible = all_filenames if design == "full_30_arm_grid" else list(authority.launch.SMOKE_ARM_FILENAMES)
    return {
        "preregistered_decision": {
            "eligible_design": design,
            "eligible_arm_count": len(eligible),
            "eligible_arm_filenames": eligible,
        },
        "eligible_runs": [{"arm_filename": filename} for filename in eligible],
        "arm_inventory": [
            {
                "arm_filename": filename,
                "decision_status": "eligible" if filename in eligible else "excluded",
            }
            for filename in all_filenames
        ],
    }


def _arm_inventory(tmp_path: Path) -> list[dict[str, object]]:
    return [
        {
            "arm_filename": filename,
            "eligible": True,
            "job_name": f"known-cost-job-{index:02d}",
            "output_dir": str((tmp_path / "runs" / f"arm-{index:02d}").resolve()),
        }
        for index, filename in enumerate(authority.expected_arm_filenames())
    ]


def test_exact_full_and_smoke_partitions_are_supported() -> None:
    full_design, full = authority._validate_design_partition(_partition_intent("full_30_arm_grid"))
    smoke_design, smoke = authority._validate_design_partition(_partition_intent("four_arm_smoke_screen"))

    assert full_design == "full_30_arm_grid"
    assert full == authority.expected_arm_filenames()
    assert smoke_design == "four_arm_smoke_screen"
    assert smoke == tuple(authority.launch.SMOKE_ARM_FILENAMES)

    malformed = copy.deepcopy(_partition_intent("full_30_arm_grid"))
    malformed["eligible_runs"].pop()
    with pytest.raises(ValueError, match="eligible-run"):
        authority._validate_design_partition(malformed)


def test_recorded_historical_launch_validator_is_replayed_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_validator = (
        tmp_path
        / "old-control"
        / "user"
        / "tianhaowu"
        / "rsci"
        / authority.REPOSITORY_PATHS["launch_validator_helpers"].name
    )
    old_validator.parent.mkdir(parents=True)
    old_validator.write_text("# historical validator\n", encoding="utf-8")
    old_validator.chmod(0o444)
    tokenizer = tmp_path / "tokenizer"
    tokenizer.write_text("tokenizer\n", encoding="utf-8")
    run_root = tmp_path / "run-root"
    intent_path = run_root / authority.launch.INTENT_NAME
    intent = {
        "schema_version": authority.launch.SCHEMA_VERSION,
        "artifact_type": authority.launch.ARTIFACT_TYPE,
        "study_id": authority.STUDY_ID,
        "inputs": {
            "run_root": str(run_root.resolve()),
            "tokenizer_path": str(tokenizer.resolve()),
        },
        "implementation": authority.file_identity(old_validator),
        **_partition_intent("full_30_arm_grid"),
    }
    intent["payload_without_self_hash_sha256"] = authority.canonical_json_sha256(intent)
    intent_path.parent.mkdir(parents=True)
    intent_path.write_bytes(authority.canonical_json_bytes(intent))
    intent_path.chmod(0o444)
    expected_summary = {
        "command": "validate",
        "intent": authority.file_identity(intent_path),
        "eligible_design": "full_30_arm_grid",
        "eligible_arm_count": 30,
        "submission_performed": False,
    }
    calls = []

    def replay(path: Path, arguments: list[str]) -> dict[str, object]:
        calls.append((path, arguments))
        return expected_summary

    monkeypatch.setattr(authority.launch, "_run_exact_validator", replay)
    validated = authority._validated_initial_intent(intent_path)

    assert validated["eligible_design"] == "full_30_arm_grid"
    assert calls == [
        (
            old_validator.resolve(),
            ["validate", "--intent", str(intent_path.resolve()), "--tokenizer", str(tokenizer.resolve())],
        )
    ]


def test_pre_rl_observation_covers_all_30_jobs_and_start_markers_under_stage1_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "dispatch"
    state_root.mkdir()
    (state_root / authority.stage1_dispatch.STATE_LOCK_NAME).touch()
    monkeypatch.setattr(authority.launch, "REQUIRED_DISPATCH_STATE_ROOT", state_root)
    arms = _arm_inventory(tmp_path)
    queried_at = "2026-08-08T00:00:00Z"
    start_time = "2026-07-09T00:00:00"
    names = sorted(str(arm["job_name"]) for arm in arms)
    name_filter = ",".join(names)

    monkeypatch.setattr(
        authority.stage1_dispatch,
        "scheduler_snapshot",
        lambda **kwargs: {
            "queried_at": queried_at,
            "start_time": start_time,
            "squeue_command": [
                "squeue",
                "--noheader",
                "--name",
                name_filter,
                f"--format={authority.stage1_dispatch.SQUEUE_FORMAT}",
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
                f"--format={authority.stage1_dispatch.SACCT_FORMAT}",
            ],
            "sacct_stdout_sha256": "b" * 64,
            "records": [],
        },
    )

    observation = authority._capture_pre_rl_observation(arms)

    assert len(observation["state_and_run_scan"]["all_arm_start_markers"]) == 30
    assert observation["scheduler_scan"]["job_names"] == names
    assert authority._validate_pre_rl_observation(observation, arms) == observation

    contaminated = copy.deepcopy(observation)
    contaminated["state_and_run_scan"]["all_arm_start_markers"].pop(
        next(iter(contaminated["state_and_run_scan"]["all_arm_start_markers"]))
    )
    with pytest.raises(ValueError, match="30-arm inventory"):
        authority._validate_pre_rl_observation(contaminated, arms)


def test_pre_rl_observation_rejects_any_existing_start_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "dispatch"
    state_root.mkdir()
    (state_root / authority.stage1_dispatch.STATE_LOCK_NAME).touch()
    monkeypatch.setattr(authority.launch, "REQUIRED_DISPATCH_STATE_ROOT", state_root)
    arms = _arm_inventory(tmp_path)
    first_output = Path(str(arms[0]["output_dir"]))
    (first_output / "weights").mkdir(parents=True)

    with pytest.raises(ValueError, match="before arm .* starts"):
        authority._pre_rl_state_scan(arms)


def test_authority_is_canonical_read_only_and_write_once(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    path = run_root / authority.AUTHORITY_NAME
    payload = {
        "inputs": {"run_root": str(run_root.resolve())},
        "value": 1,
    }

    identity = authority.write_authority(path, payload)

    assert identity == authority.file_identity(path)
    assert path.read_bytes() == authority.canonical_json_bytes(payload)
    assert path.stat().st_mode & 0o222 == 0
    assert authority.write_authority(path, payload) == identity
    with pytest.raises(FileExistsError):
        authority.write_authority(path, {**payload, "value": 2})


def test_recorded_implementation_must_match_authority_bytes(tmp_path: Path) -> None:
    implementations = {}
    for name in authority.REPOSITORY_PATHS:
        path = tmp_path / f"{name}.py"
        path.write_text(f"# {name}\n", encoding="utf-8")
        implementations[name] = authority.file_identity(path)
    artifact = {"postrun_control_source": {"implementations": implementations}}
    analyzer_path = Path(implementations["result_analyzer"]["path"])

    assert (
        authority.validate_recorded_implementation(
            artifact,
            name="result_analyzer",
            implementation_path=analyzer_path,
        )
        == implementations["result_analyzer"]
    )
    analyzer_path.write_text("# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="authority-pinned"):
        authority.validate_recorded_implementation(
            artifact,
            name="result_analyzer",
            implementation_path=analyzer_path,
        )


def test_postrun_authority_inventory_pins_training_completion_consumer_and_replay() -> None:
    assert authority.REPOSITORY_PATHS["training_replay"].name == "analyze_masked_verifier_attempts.py"
    assert authority.REPOSITORY_PATHS["training_readout_consumer"].name == "analyze_known_cost_training_readouts.py"
    assert (
        authority.REPOSITORY_PATHS["training_completion_materializer"].name
        == "materialize_known_cost_training_completion.py"
    )
    assert authority.REPOSITORY_PATHS["stage1_dispatcher"].name == "dispatch_known_cost_boundary.py"
    assert (
        authority.REPOSITORY_PATHS["promoted_eval_authority"].name
        == "materialize_known_cost_promoted_eval_authority.py"
    )
