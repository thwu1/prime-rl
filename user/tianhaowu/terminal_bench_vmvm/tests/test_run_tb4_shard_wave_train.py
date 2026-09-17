from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import threading
from pathlib import Path

import pytest
import run_tb4_shard_wave_train as train
from inference_route_guard import RouteBinding
from launch_tb4_shard_wave import EXPECTED_TMUX_TARGET, PinnedArtifact
from tb4_shard_workflow import PlannedShard


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact(path: Path, payload: bytes) -> PinnedArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return PinnedArtifact(path=path.resolve(), sha256=_digest(payload), raw=None)


def _prepared(tmp_path: Path, *, count: int = 5) -> train.PreparedTrain:
    project = tmp_path / "project"
    project.mkdir()
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir(mode=0o700)
    plan_artifact = _artifact(plan_dir / "plan.json", b"plan\n")
    plan_artifact.path.chmod(0o600)
    shards: list[PlannedShard] = []
    for index in range(count):
        config = plan_dir / f"shard-{index:03d}.toml"
        manifest = plan_dir / f"shard-{index:03d}.tasks.txt"
        config.write_bytes(f"config-{index}\n".encode())
        manifest.write_bytes(f"private-case-{index}\n".encode())
        config.chmod(0o600)
        manifest.chmod(0o600)
        shards.append(
            PlannedShard(
                index=index,
                task_count=1,
                task_manifest=manifest.resolve(),
                task_manifest_sha256=_digest(manifest.read_bytes()),
                config=config.resolve(),
                config_sha256=_digest(config.read_bytes()),
                tasks=frozenset({f"private-case-{index}"}),
            )
        )
    deployment_spec = _artifact(tmp_path / "spec.yaml", b"spec\n")
    readiness = _artifact(tmp_path / "readiness.json", b"readiness\n")
    proxy_info = _artifact(tmp_path / "proxy.json", b"proxy\n")
    smoke = _artifact(tmp_path / "smoke.json", b"smoke\n")
    archive = _artifact(tmp_path / "dataset.tar", b"archive\n")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    generation = {
        "schema_version": 2,
        "coordinator": {"slurm_job_id": "10", "started_at": "2026-01-01T00:00:00Z"},
        "proxy": {"slurm_job_id": "11", "first_ready_at": "2026-01-01T00:00:01Z"},
        "routes": [
            {
                "slurm_job_id": "12",
                "started_at": "2026-01-01T00:00:02Z",
                "backend_sha256": f"backend-sha256:{'a' * 64}",
            }
        ],
    }
    endpoint = {
        "schema_version": 1,
        "deployment_id": "deployment-test",
        "model": "Kimi-K3",
        "authority_sha256": "b" * 64,
        "proxy_info": {"path": str(proxy_info.path), "sha256": proxy_info.sha256},
    }
    policy = {
        "schema_version": 1,
        "request_timeout": 7200,
        "num_retries": 0,
        "proxy_litellm_config": {
            "path": str(tmp_path / "proxy-policy.yaml"),
            "sha256": "c" * 64,
        },
    }
    config = train.WaveTrainConfig(
        controller_root=tmp_path / "controller",
        project_dir=project,
        project_revision="1" * 40,
        plan_path=plan_artifact.path,
        plan_sha256=plan_artifact.sha256,
        deployment_id="deployment-test",
        deployment_spec_path=deployment_spec.path,
        deployment_spec_sha256=deployment_spec.sha256,
        readiness_path=readiness.path,
        readiness_sha256=readiness.sha256,
        proxy_info_path=proxy_info.path,
        proxy_info_sha256=proxy_info.sha256,
        smoke_checkpoint_path=smoke.path,
        smoke_checkpoint_sha256=smoke.sha256,
        dataset_archive_path=archive.path,
        dataset_archive_sha256=archive.sha256,
        dataset_content_sha256="d" * 64,
        shard_count=count,
        wave_size=4,
        poll_interval_seconds=1,
    )
    route = RouteBinding(
        deployment_id="deployment-test",
        deployment_spec=deployment_spec.path,
        deployment_spec_sha256=deployment_spec.sha256,
        readiness_checkpoint=readiness.path,
        readiness_checkpoint_sha256=readiness.sha256,
        proxy_info=proxy_info.path,
        proxy_info_sha256=proxy_info.sha256,
        expected_model="Kimi-K3",
        endpoint=endpoint,
        proxy_policy=policy,
        expected_routes=1,
        route_generation=generation,
        minimum_coord_ticks_completed=1,
    )
    return train.PreparedTrain(
        config=config,
        controller_root=config.controller_root.resolve(),
        project=project.resolve(),
        plan_artifact=plan_artifact,
        plan={
            "plan_sha256": "e" * 64,
            "base_config": {"semantics_sha256": "f" * 64},
        },
        shards=tuple(shards),
        selected_indices=tuple(range(count)),
        revisions={"prime_rl": "1" * 40, "verifiers": "2" * 40, "renderers": "3" * 40},
        deployment_spec=deployment_spec,
        readiness=readiness,
        proxy_info=proxy_info,
        smoke=smoke,
        dataset_path=dataset.resolve(),
        dataset_archive=archive,
        generation_sha256=_digest(train.canonical_json(generation)),
        route_binding=route,
    )


class _Harness:
    def __init__(self) -> None:
        self.waves: dict[Path, dict] = {}
        self.launched: list[tuple[int, ...]] = []
        self.events: list[tuple[str, tuple[int, ...]]] = []
        self.scheduler_state = "COMPLETED"
        self.scheduler_exit_code: str | None = "0:0"

    def command(self, arguments, **_kwargs):
        assert arguments[0] == "tmux"
        return subprocess.CompletedProcess(arguments, 0, EXPECTED_TMUX_TARGET + "\n", "")

    def launch(
        self,
        prepared: train.PreparedTrain,
        wave_number: int,
        indices: tuple[int, ...],
        output_root: Path,
        _stop_requested,
    ) -> dict:
        self.events.append(("launch", indices))
        self.launched.append(indices)
        output_root.mkdir(mode=0o700)
        jobs = [
            {
                "shard_index": index,
                "slurm_job_id": str(10_000 + index),
                "output_dir": str(output_root / f"shard-{index:03d}-attempt-001"),
            }
            for index in indices
        ]
        wave = {"state": "submitted", "wave_sha256": f"{wave_number + 1:064x}", "jobs": jobs}
        self.waves[output_root] = wave
        return wave

    def load(
        self,
        _prepared: train.PreparedTrain,
        _wave_number: int,
        _indices: tuple[int, ...],
        output_root: Path,
        _allow_recovering: bool,
    ) -> dict:
        return self.waves[output_root]

    def scheduler(self, job_ids) -> dict[str, train.SchedulerObservation]:
        self.events.append(("poll", tuple(int(job_id) - 10_000 for job_id in job_ids)))
        return {
            job_id: train.SchedulerObservation(self.scheduler_state, self.scheduler_exit_code) for job_id in job_ids
        }

    def validate(
        self,
        prepared: train.PreparedTrain,
        shard: PlannedShard,
        job,
    ) -> train.ShardEvidence:
        self.events.append(("validate", (shard.index,)))
        return train.ShardEvidence(
            shard_index=shard.index,
            slurm_job_id=job["slurm_job_id"],
            supported=True,
            solved=1 if shard.index == 0 else 0,
            artifacts={"results": f"{shard.index + 20:064x}"},
            eval_run_identity_sha256=f"{shard.index + 30:064x}",
            guard_success_receipt_sha256=f"{shard.index + 40:064x}",
            route_generation_sha256=prepared.generation_sha256,
        )


def _drive(prepared: train.PreparedTrain, harness: _Harness, **overrides):
    values = {
        "ambient_env": {"TMUX_PANE": "%1"},
        "command_runner": harness.command,
        "launch_callback": harness.launch,
        "wave_loader": harness.load,
        "scheduler_reader": harness.scheduler,
        "shard_validator": harness.validate,
        "route_verifier": lambda _prepared: None,
    }
    values.update(overrides)
    return train.drive_train(prepared, **values)


def test_sequential_waves_are_disjoint_and_prior_wave_is_validated(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()

    state = _drive(prepared, harness)

    assert state["state"] == "complete"
    assert harness.launched == [(0, 1, 2, 3), (4,)]
    second_launch = harness.events.index(("launch", (4,)))
    assert all(harness.events.index(("validate", (index,))) < second_launch for index in range(4))
    assert len(state["completed_waves"]) == 2
    assert stat.S_IMODE((prepared.controller_root / "train.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((prepared.controller_root / "state.json").stat().st_mode) == 0o600
    for number in range(2):
        assert stat.S_IMODE((prepared.controller_root / f"wave-{number:03d}/completion.json").stat().st_mode) == 0o600
    metadata = b"".join(
        path.read_bytes() for path in prepared.controller_root.rglob("*.json") if path.name != "wave.json"
    )
    assert b"private-case" not in metadata


class _StopAfterWait:
    def __init__(self) -> None:
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, _timeout: float) -> bool:
        self.stopped = True
        return True


def test_restart_observes_submitted_wave_without_relaunch(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()
    harness.scheduler_state = "RUNNING"
    harness.scheduler_exit_code = None

    interrupted = _drive(prepared, harness, stop_event=_StopAfterWait())

    assert interrupted["state"] == "interrupted"
    assert harness.launched == [(0, 1, 2, 3)]
    harness.scheduler_state = "COMPLETED"
    harness.scheduler_exit_code = "0:0"
    completed = _drive(prepared, harness, stop_event=threading.Event())
    assert completed["state"] == "complete"
    assert harness.launched == [(0, 1, 2, 3), (4,)]


def test_failed_job_stops_train_and_never_launches_next_wave(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()
    harness.scheduler_state = "FAILED"
    harness.scheduler_exit_code = "1:0"

    with pytest.raises(train.WaveTrainError, match="shard_job_failed"):
        _drive(prepared, harness)

    state = json.loads((prepared.controller_root / "state.json").read_text())
    assert state["state"] == "failed"
    assert state["failure"] == "shard_job_failed"
    assert harness.launched == [(0, 1, 2, 3)]


def test_missing_guarded_artifacts_stops_train(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()

    def reject(*_args):
        raise train.WaveTrainError("shard_guarded_artifacts_invalid")

    with pytest.raises(train.WaveTrainError, match="shard_guarded_artifacts_invalid"):
        _drive(prepared, harness, shard_validator=reject)
    assert harness.launched == [(0, 1, 2, 3)]


def test_route_change_stops_before_any_submission(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()

    def changed(_prepared):
        raise train.WaveTrainError("serving_route_generation_changed")

    with pytest.raises(train.WaveTrainError, match="serving_route_generation_changed"):
        _drive(prepared, harness, route_verifier=changed)
    assert harness.launched == []


def test_resume_environment_is_always_rejected(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()
    with pytest.raises(train.WaveTrainError, match="resume_forbidden"):
        _drive(prepared, harness, ambient_env={"TMUX_PANE": "%1", "RESUME_DIR": "old"})
    assert not prepared.controller_root.exists()


def test_private_state_mode_is_revalidated_on_restart(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()
    harness.scheduler_state = "RUNNING"
    harness.scheduler_exit_code = None
    _drive(prepared, harness, stop_event=_StopAfterWait())
    (prepared.controller_root / "state.json").chmod(0o644)

    with pytest.raises(train.WaveTrainError, match="controller_state_not_private"):
        _drive(prepared, harness)
    assert harness.launched == [(0, 1, 2, 3)]


def test_intent_recovery_adopts_fully_recorded_wave(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    train._ensure_controller_root(prepared)
    with train._controller_lock(prepared.controller_root):
        _train, state = train._initialize_or_load(prepared)
        state = train._launch_intent(prepared, state)
    root = prepared.controller_root / "wave-000"
    harness.launch(prepared, 0, (0,), root, lambda: False)
    (root / "wave.json").write_text("{}\n")
    (root / "wave.json").chmod(0o600)
    harness.launched.clear()

    final = _drive(prepared, harness)

    assert final["state"] == "complete"
    assert harness.launched == []


def test_intent_recovery_retires_pre_submission_directory(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    train._ensure_controller_root(prepared)
    with train._controller_lock(prepared.controller_root):
        _train, state = train._initialize_or_load(prepared)
        train._launch_intent(prepared, state)
    root = prepared.controller_root / "wave-000"
    root.mkdir(mode=0o700)

    final = _drive(prepared, harness)

    assert final["state"] == "complete"
    assert harness.launched == [(0,)]
    abandoned = list(prepared.controller_root.glob("wave-000-abandoned-*"))
    assert len(abandoned) == 1
    receipt = json.loads((abandoned[0] / "abandoned.json").read_text())
    assert receipt["state"] == "abandoned_before_submission"


def test_query_scheduler_combines_squeue_and_sacct():
    calls = []

    def runner(arguments, **_kwargs):
        calls.append(arguments)
        if arguments[0] == train.SQUEUE:
            return subprocess.CompletedProcess(arguments, 0, "101|RUNNING\n", "")
        return subprocess.CompletedProcess(arguments, 0, "102|COMPLETED|0:0\n", "")

    observed = train.query_scheduler(("101", "102"), runner=runner)

    assert observed == {
        "101": train.SchedulerObservation("RUNNING", None),
        "102": train.SchedulerObservation("COMPLETED", "0:0"),
    }
    assert calls[1][0] == train.SACCT
    assert "--allocations" in calls[1]


@pytest.mark.parametrize(
    ("squeue_output", "sacct_output", "error"),
    [
        ("", "", "scheduler_job_missing"),
        ("999|RUNNING\n", "", "scheduler_response_invalid"),
        ("101|MYSTERY\n", "", "scheduler_response_invalid"),
        ("", "101|COMPLETED|bad\n", "scheduler_response_invalid"),
        ("101|RUNNING\n101|PENDING\n", "", "scheduler_response_invalid"),
    ],
)
def test_query_scheduler_fails_closed(squeue_output: str, sacct_output: str, error: str):
    def runner(arguments, **_kwargs):
        output = squeue_output if arguments[0] == train.SQUEUE else sacct_output
        return subprocess.CompletedProcess(arguments, 0, output, "")

    with pytest.raises(train.WaveTrainError, match=error):
        train.query_scheduler(("101",), runner=runner)


def test_poll_interval_and_wave_size_are_bounded(tmp_path: Path):
    prepared = _prepared(tmp_path)
    for value in (0, 61, float("nan")):
        config = train.WaveTrainConfig(**{**prepared.config.__dict__, "poll_interval_seconds": value})
        with pytest.raises(train.WaveTrainError, match="controller_bounds_invalid"):
            train._validate_config(config)
    config = train.WaveTrainConfig(**{**prepared.config.__dict__, "wave_size": 5})
    with pytest.raises(train.WaveTrainError, match="controller_bounds_invalid"):
        train._validate_config(config)


def test_exact_tmux_target_is_required_before_launch(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()

    def wrong_tmux(arguments, **_kwargs):
        return subprocess.CompletedProcess(arguments, 0, "wrong:Pane.0\n", "")

    with pytest.raises(train.WaveTrainError, match="wave_submission_failed"):
        _drive(prepared, harness, command_runner=wrong_tmux)
    assert harness.launched == []


def _write_exact_wave(
    prepared: train.PreparedTrain,
    *,
    phases: tuple[str, ...] = ("recorded",),
) -> tuple[Path, dict]:
    root = prepared.controller_root / "wave-000"
    root.mkdir(parents=True, mode=0o700)
    indices = prepared.selected_indices[: len(phases)]
    jobs = []
    for index, phase in zip(indices, phases, strict=True):
        shard = prepared.shards[index]
        output_dir = root / f"shard-{index:03d}-attempt-001"
        environment_path = root / f"shard-{index:03d}.env"
        environment_raw = train._expected_job_environment(prepared, shard, output_dir)
        environment_path.write_bytes(environment_raw)
        environment_path.chmod(0o600)
        token = f"{index + 1:016x}" if phase != "unstarted" else None
        jobs.append(
            {
                "shard_index": index,
                "task_count": 1,
                "config_sha256": shard.config_sha256,
                "task_manifest_sha256": shard.task_manifest_sha256,
                "environment": {
                    "path": str(environment_path),
                    "sha256": _digest(environment_raw),
                },
                "output_dir": str(output_dir),
                "submission_started_at": ("2026-09-17T00:00:00Z" if phase != "unstarted" else None),
                "submission_token": token,
                "slurm_job_id": str(12_345 + index) if phase == "recorded" else None,
            }
        )
    body = {
        "schema_version": 1,
        "state": "submitted" if set(phases) == {"recorded"} else "submitting",
        "dry_run": False,
        "plan": {
            "path": str(prepared.plan_artifact.path),
            "sha256": prepared.plan_artifact.sha256,
            "plan_sha256": prepared.plan["plan_sha256"],
        },
        "project": {"path": str(prepared.project), "revisions": prepared.revisions},
        "deployment": {
            "id": prepared.config.deployment_id,
            "spec_sha256": prepared.deployment_spec.sha256,
            "readiness_checkpoint_sha256": prepared.readiness.sha256,
            "proxy_info_sha256": prepared.proxy_info.sha256,
            "smoke_checkpoint_sha256": prepared.smoke.sha256,
            "route_generation_sha256": prepared.generation_sha256,
            "model": "Kimi-K3",
        },
        "dataset": train._dataset_record(prepared),
        "vmvm_environment": train.EXPECTED_VMVM_ENV,
        "wave_size": len(indices),
        "jobs": jobs,
    }
    wave = train._write_once_private_json(root / "wave.json", body, hash_key="wave_sha256")
    return root, wave


def test_wave_metadata_revalidates_exact_environment(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    root, expected = _write_exact_wave(prepared)

    observed = train._load_wave_metadata(prepared, 0, (0,), root, False)
    assert observed == expected

    environment = root / "shard-000.env"
    environment.write_bytes(environment.read_bytes() + b"RESUME_DIR=forbidden\0")
    with pytest.raises(train.WaveTrainError, match="wave_environment_invalid"):
        train._load_wave_metadata(prepared, 0, (0,), root, False)


def test_recovery_rejects_wave_without_durable_job_id(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    root, expected = _write_exact_wave(prepared, phases=("ambiguous",))
    assert train._load_wave_metadata(prepared, 0, (0,), root, True) == expected
    with pytest.raises(train.WaveTrainError, match="wave_metadata_invalid"):
        train._load_wave_metadata(prepared, 0, (0,), root, False)


def test_state_self_hash_tampering_is_rejected(tmp_path: Path):
    prepared = _prepared(tmp_path)
    harness = _Harness()
    harness.scheduler_state = "RUNNING"
    harness.scheduler_exit_code = None
    _drive(prepared, harness, stop_event=_StopAfterWait())
    state_path = prepared.controller_root / "state.json"
    value = json.loads(state_path.read_text())
    value["next_position"] = 1
    state_path.write_text(json.dumps(value) + "\n")
    state_path.chmod(0o600)

    with pytest.raises(train.WaveTrainError, match="controller_state_invalid"):
        _drive(prepared, harness)
    assert harness.launched == [(0, 1, 2, 3)]


def test_restart_recovers_after_completion_receipt_before_state_update(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    train._ensure_controller_root(prepared)
    with train._controller_lock(prepared.controller_root):
        metadata, state = train._initialize_or_load(prepared)
        state = train._launch_intent(prepared, state)
        root = prepared.controller_root / "wave-000"
        wave = harness.launch(prepared, 0, (0,), root, lambda: False)
        current = train._current_from_wave(0, (0,), root, wave)
        body = train._state_body(state)
        body["state"] = "observing"
        body["current_wave"] = current
        train._save_state(prepared, body)
        evidence = harness.validate(prepared, prepared.shards[0], wave["jobs"][0])
        train._write_or_validate_completion(
            prepared,
            metadata["train_sha256"],
            0,
            (0,),
            wave,
            [evidence],
            harness.validate,
        )
    harness.launched.clear()

    def scheduler_must_not_run(_job_ids):
        raise AssertionError("durable completion should avoid an expired scheduler lookup")

    final = _drive(prepared, harness, scheduler_reader=scheduler_must_not_run)
    assert final["state"] == "complete"
    assert harness.launched == []


def test_restart_recovers_initial_state_after_train_write(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    train._ensure_controller_root(prepared)
    train._write_once_private_json(
        prepared.controller_root / "train.json",
        train._train_body(prepared),
        hash_key="train_sha256",
    )

    final = _drive(prepared, harness)

    assert final["state"] == "complete"
    assert harness.launched == [(0,)]


def test_lookup_submission_job_requires_one_exact_name_match():
    name = "tb4-shard-000-0123456789abcdef"

    def unique(arguments, **_kwargs):
        if arguments[0] == train.SQUEUE:
            return subprocess.CompletedProcess(arguments, 0, f"12345|{name}\n", "")
        return subprocess.CompletedProcess(arguments, 0, f"12345|{name}\n", "")

    assert train.lookup_submission_job(name, "2026-09-17T00:00:00Z", runner=unique) == "12345"

    def duplicate(arguments, **_kwargs):
        job_id = "12345" if arguments[0] == train.SQUEUE else "12346"
        return subprocess.CompletedProcess(arguments, 0, f"{job_id}|{name}\n", "")

    with pytest.raises(train.WaveTrainError, match="submission_lookup_not_unique"):
        train.lookup_submission_job(name, "2026-09-17T00:00:00Z", runner=duplicate)


def test_partial_submission_recovers_accepted_job_and_submits_only_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    prepared = _prepared(tmp_path, count=3)
    root, wave = _write_exact_wave(
        prepared,
        phases=("recorded", "ambiguous", "unstarted"),
    )
    submitted_names: list[str] = []

    def runner(arguments, **_kwargs):
        if arguments[0] == "tmux":
            return subprocess.CompletedProcess(arguments, 0, EXPECTED_TMUX_TARGET + "\n", "")
        assert arguments[0] == train.DEFAULT_SBATCH
        submitted_names.append(next(value for value in arguments if value.startswith("--job-name=")))
        return subprocess.CompletedProcess(arguments, 0, "22000\n", "")

    monkeypatch.setattr(train, "_revalidate_submission_inputs", lambda *_args, **_kwargs: None)
    recovered = train._resume_partial_wave_submission(
        prepared,
        (0, 1, 2),
        root,
        wave,
        ambient_env={"TMUX_PANE": "%1"},
        command_runner=runner,
        route_verifier=lambda _prepared: None,
        submission_lookup=lambda _name, _started: "21000",
        stop_requested=lambda: False,
    )

    assert recovered["state"] == "submitted"
    assert [job["slurm_job_id"] for job in recovered["jobs"]] == ["12345", "21000", "22000"]
    assert len(submitted_names) == 1
    assert submitted_names[0].startswith("--job-name=tb4-shard-002-")
    assert train._load_wave_metadata(prepared, 0, (0, 1, 2), root, False) == recovered


def test_completed_receipt_is_preserved_across_route_rollover(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    harness.scheduler_state = "RUNNING"
    harness.scheduler_exit_code = None
    _drive(prepared, harness, stop_event=_StopAfterWait())
    harness.scheduler_state = "COMPLETED"
    harness.scheduler_exit_code = "0:0"
    scheduler_calls = 0

    def delayed_accounting(job_ids):
        nonlocal scheduler_calls
        scheduler_calls += 1
        if scheduler_calls == 1:
            raise train.SchedulerQueryUnavailable("scheduler_job_missing")
        return {job_id: train.SchedulerObservation("COMPLETED", "0:0") for job_id in job_ids}

    def route_must_not_run(_prepared):
        raise AssertionError("completed guarded output must be certified before route liveness")

    final = _drive(
        prepared,
        harness,
        route_verifier=route_must_not_run,
        scheduler_reader=delayed_accounting,
        stop_event=_NeverStop(),
    )
    assert final["state"] == "complete"
    assert scheduler_calls == 2


class _NeverStop:
    def is_set(self) -> bool:
        return False

    def wait(self, _timeout: float) -> bool:
        return False


def test_transient_scheduler_failure_is_retried(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    attempts = 0

    def scheduler(job_ids):
        nonlocal attempts
        attempts += 1
        if attempts < train.MAX_CONSECUTIVE_SCHEDULER_FAILURES:
            raise train.SchedulerQueryUnavailable("scheduler_query_unavailable")
        return {job_id: train.SchedulerObservation("COMPLETED", "0:0") for job_id in job_ids}

    final = _drive(
        prepared,
        harness,
        scheduler_reader=scheduler,
        stop_event=_NeverStop(),
    )
    assert final["state"] == "complete"
    assert attempts == train.MAX_CONSECUTIVE_SCHEDULER_FAILURES


def test_scheduler_failure_budget_is_bounded_and_persisted(tmp_path: Path):
    prepared = _prepared(tmp_path, count=1)
    harness = _Harness()
    attempts = 0

    def unavailable(_job_ids):
        nonlocal attempts
        attempts += 1
        raise train.SchedulerQueryUnavailable("scheduler_query_unavailable")

    with pytest.raises(train.WaveTrainError, match="scheduler_query_unavailable"):
        _drive(
            prepared,
            harness,
            scheduler_reader=unavailable,
            stop_event=_NeverStop(),
        )
    state = json.loads((prepared.controller_root / "state.json").read_text())
    assert attempts == train.MAX_CONSECUTIVE_SCHEDULER_FAILURES
    assert state["state"] == "failed"
    assert state["failure"] == "scheduler_query_unavailable"
