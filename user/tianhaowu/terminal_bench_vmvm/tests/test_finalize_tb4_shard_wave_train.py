from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import finalize_tb4_multigen_chunk_train as multigen_cli
import finalize_tb4_shard_wave_train as finalizer
import pytest
from run_tb4_shard_wave_train import WaveTrainConfig, WaveTrainError


def _controller_config(tmp_path: Path) -> WaveTrainConfig:
    return WaveTrainConfig(
        controller_root=tmp_path / "controller",
        project_dir=tmp_path / "project",
        project_revision="1" * 40,
        plan_path=tmp_path / "plan.json",
        plan_sha256="2" * 64,
        deployment_id="deployment-test",
        deployment_spec_path=tmp_path / "spec.yaml",
        deployment_spec_sha256="3" * 64,
        readiness_path=tmp_path / "readiness.json",
        readiness_sha256="4" * 64,
        proxy_info_path=tmp_path / "proxy.json",
        proxy_info_sha256="5" * 64,
        smoke_checkpoint_path=tmp_path / "smoke.json",
        smoke_checkpoint_sha256="6" * 64,
        dataset_revision="7" * 40,
        first_shard_index=0,
        shard_count=66,
        wave_size=4,
        poll_interval_seconds=15,
    )


def _config(tmp_path: Path, **overrides) -> finalizer.FinalizerConfig:
    values = {
        "controller": _controller_config(tmp_path),
        "expected_train_sha256": "e" * 64,
        "output_dir": tmp_path / "final",
        "wait_for_completion": False,
        "wait_poll_seconds": 1,
        "wait_timeout_seconds": None,
        "lock_poll_seconds": 1,
        "lock_timeout_seconds": 5,
    }
    values.update(overrides)
    return finalizer.FinalizerConfig(**values)


def _clock():
    value = 0.0

    def read() -> float:
        return value

    def advance(seconds: float) -> None:
        nonlocal value
        value += seconds

    return read, advance


def _candidate_config(tmp_path: Path, candidates: tuple[Path, ...]) -> finalizer.CandidateControllerConfig:
    controller = _controller_config(tmp_path)
    return finalizer.CandidateControllerConfig(
        controller_root=controller.controller_root,
        project_dir=controller.project_dir,
        project_revision=controller.project_revision,
        plan_path=controller.plan_path,
        plan_sha256=controller.plan_sha256,
        deployment_id=controller.deployment_id,
        deployment_spec_path=controller.deployment_spec_path,
        deployment_spec_sha256=controller.deployment_spec_sha256,
        readiness_path=controller.readiness_path,
        readiness_sha256=controller.readiness_sha256,
        proxy_info_path=controller.proxy_info_path,
        proxy_info_sha256=controller.proxy_info_sha256,
        smoke_checkpoint_candidates=candidates,
        dataset_revision=controller.dataset_revision,
        wave_size=controller.wave_size,
        controller_poll_interval_seconds=controller.poll_interval_seconds,
    )


def test_candidate_mode_derives_train_hash_from_trusted_winner(tmp_path: Path, monkeypatch):
    candidates = (tmp_path / "smoke-a.json", tmp_path / "smoke-b.json")
    for index, candidate in enumerate(candidates):
        candidate.write_bytes(f"smoke-{index}\n".encode())
        candidate.chmod(0o600)
    config = _candidate_config(tmp_path, candidates)

    def body(prepared):
        return {
            "smoke_path": str(prepared.config.smoke_checkpoint_path),
            "smoke_sha256": prepared.config.smoke_checkpoint_sha256,
        }

    winner_sha = hashlib.sha256(candidates[1].read_bytes()).hexdigest()
    winner_body = {"smoke_path": str(candidates[1]), "smoke_sha256": winner_sha}
    expected_train_sha = hashlib.sha256(finalizer.canonical_json(winner_body)).hexdigest()
    reads = iter((WaveTrainError("train_unavailable"), {**winner_body, "train_sha256": expected_train_sha}))

    def load(*_args, **_kwargs):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value, "0" * 64

    monkeypatch.setattr(finalizer, "_load_private_json", load)
    monkeypatch.setattr(finalizer, "prepare_train", lambda controller, **_kwargs: SimpleNamespace(config=controller))
    monkeypatch.setattr(finalizer, "_train_body", body)
    clock, sleep = _clock()

    controller, train_sha256 = finalizer.resolve_candidate_controller(
        config,
        wait_poll_seconds=1,
        wait_timeout_seconds=10,
        command_runner=lambda *_args, **_kwargs: None,
        sleep=sleep,
        clock=clock,
    )

    assert controller.smoke_checkpoint_path == candidates[1]
    assert controller.smoke_checkpoint_sha256 == winner_sha
    assert train_sha256 == expected_train_sha
    assert clock() == 1


def test_candidate_mode_rejects_self_consistent_untrusted_train(tmp_path: Path, monkeypatch):
    candidate = tmp_path / "smoke.json"
    candidate.write_text("smoke\n")
    candidate.chmod(0o600)
    config = _candidate_config(tmp_path, (candidate,))
    monkeypatch.setattr(
        finalizer,
        "_load_private_json",
        lambda *_args, **_kwargs: ({"substituted": True, "train_sha256": "a" * 64}, "0" * 64),
    )
    monkeypatch.setattr(finalizer, "prepare_train", lambda controller, **_kwargs: SimpleNamespace(config=controller))
    monkeypatch.setattr(
        finalizer,
        "_train_body",
        lambda prepared: {"smoke_path": str(prepared.config.smoke_checkpoint_path)},
    )

    with pytest.raises(finalizer.FinalizationError, match="trusted_train_match_missing"):
        finalizer.resolve_candidate_controller(config, wait_poll_seconds=1)


def test_wait_requires_hash_valid_complete_state(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, wait_for_completion=True, wait_timeout_seconds=10)
    states = iter(({"state": "observing"}, {"state": "complete", "state_sha256": "a" * 64}))
    monkeypatch.setattr(finalizer, "_load_state", lambda _root: next(states))
    clock, sleep = _clock()

    state = finalizer.wait_for_complete_state(config, sleep=sleep, clock=clock)

    assert state["state"] == "complete"
    assert clock() == 1


def test_wait_fails_closed_after_repeated_invalid_existing_state(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, wait_for_completion=True, wait_timeout_seconds=10)
    config.controller.controller_root.mkdir(mode=0o700)
    (config.controller.controller_root / "state.json").write_text("invalid")
    monkeypatch.setattr(
        finalizer,
        "_load_state",
        lambda _root: (_ for _ in ()).throw(finalizer.FinalizationError("controller_state_unavailable")),
    )
    clock, sleep = _clock()

    with pytest.raises(finalizer.FinalizationError, match="controller_state_invalid"):
        finalizer.wait_for_complete_state(config, sleep=sleep, clock=clock)

    assert clock() == 2


def test_wait_rejects_unknown_self_hash_valid_phase(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, wait_for_completion=True)
    monkeypatch.setattr(finalizer, "_load_state", lambda _root: {"state": "unknown"})

    with pytest.raises(finalizer.FinalizationError, match="controller_state_invalid"):
        finalizer.wait_for_complete_state(config)


def test_wait_rejects_untrusted_train_hash_before_polling(tmp_path: Path, monkeypatch):
    config = _config(tmp_path, expected_train_sha256="invalid", wait_for_completion=True)
    monkeypatch.setattr(
        finalizer,
        "_load_state",
        lambda _root: (_ for _ in ()).throw(AssertionError("state must not be read")),
    )

    with pytest.raises(finalizer.FinalizationError, match="train_sha256_invalid"):
        finalizer.wait_for_complete_state(config)


def test_finalize_retries_controller_lock_release_race(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    root = config.controller.controller_root
    root.mkdir(mode=0o700)
    attempts = 0

    @contextmanager
    def lock(_root):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise WaveTrainError("controller_already_running")
        yield

    monkeypatch.setattr(finalizer, "wait_for_complete_state", lambda *_args, **_kwargs: {"state": "complete"})
    monkeypatch.setattr(finalizer, "_validate_controller_root", lambda _root: root)
    monkeypatch.setattr(finalizer, "_controller_lock", lock)
    monkeypatch.setattr(finalizer, "_finalize_locked", lambda *_args, **_kwargs: {"state": "passed"})
    clock, sleep = _clock()

    summary = finalizer.finalize_wave_train(
        config,
        command_runner=lambda *_args, **_kwargs: None,
        sleep=sleep,
        clock=clock,
    )

    assert summary == {"state": "passed"}
    assert attempts == 2
    assert clock() == 1


def _controller_route_generation(
    *,
    backend_sha256: str = "a" * 64,
    coordinator_job_id: str = "900",
    proxy_job_id: str = "12345",
) -> dict:
    return {
        "schema_version": 2,
        "coordinator": {
            "slurm_job_id": coordinator_job_id,
            "started_at": "2026-09-17T00:00:00Z",
        },
        "proxy": {
            "slurm_job_id": proxy_job_id,
            "first_ready_at": "2026-09-17T00:30:00Z",
        },
        "routes": [
            {
                "slurm_job_id": "12000",
                "started_at": "2026-09-17T01:00:00Z",
                "backend_sha256": f"backend-sha256:{backend_sha256}",
            }
        ],
    }


def _prepared(
    tmp_path: Path,
    *,
    root_name: str = "controller",
    first_shard_index: int = 0,
    shard_count: int = 66,
    route_generation: dict | None = None,
):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    controller = tmp_path / root_name
    controller.mkdir(mode=0o700, exist_ok=True)
    dataset = tmp_path / "dataset"
    dataset.mkdir(exist_ok=True)
    dataset.chmod(0o700)
    shards = tuple(
        SimpleNamespace(
            task_count=1,
            task_manifest_sha256=f"{index + 1:064x}",
            config_sha256=f"{index + 1000:064x}",
        )
        for index in range(66)
    )
    route_generation = _controller_route_generation() if route_generation is None else route_generation
    proxy_info = SimpleNamespace(path=(tmp_path / f"{root_name}-proxy-info.json").resolve(), sha256="6" * 64)
    return SimpleNamespace(
        config=SimpleNamespace(
            deployment_id="deployment-test",
            wave_size=4,
            project_revision="1" * 40,
            dataset_revision="7" * 40,
            dataset_content_sha256=None,
            poll_interval_seconds=15,
        ),
        controller_root=controller.resolve(),
        project=project.resolve(),
        selected_indices=tuple(range(first_shard_index, first_shard_index + shard_count)),
        shards=shards,
        revisions={"prime-rl": "1" * 40, "verifiers": "2" * 40, "renderers": "3" * 40},
        plan_artifact=SimpleNamespace(path=(tmp_path / "plan.json").resolve(), sha256="1" * 64),
        plan={
            "plan_sha256": "2" * 64,
            "universe": {"sha256": "3" * 64},
            "base_config": {"semantics_sha256": "4" * 64},
        },
        dataset_path=dataset.resolve(),
        deployment_spec=SimpleNamespace(path=(tmp_path / f"{root_name}-spec.yaml").resolve(), sha256="b" * 64),
        readiness=SimpleNamespace(path=(tmp_path / f"{root_name}-readiness.json").resolve(), sha256="5" * 64),
        proxy_info=proxy_info,
        smoke=SimpleNamespace(path=(tmp_path / f"{root_name}-smoke.json").resolve(), sha256="7" * 64),
        generation_sha256=hashlib.sha256(finalizer.canonical_json(route_generation)).hexdigest(),
        proxy_config_snapshot=SimpleNamespace(
            path=(tmp_path / f"{root_name}-proxy-config.yaml").resolve(),
            sha256="9" * 64,
        ),
        route_binding=SimpleNamespace(
            endpoint={
                "schema_version": 1,
                "kind": "deployment_local_proxy_info",
                "proxy_info": {"path": str(proxy_info.path), "sha256": proxy_info.sha256},
                "authority_sha256": "c" * 64,
            },
            proxy_policy={"policy_sha256": "d" * 64},
            route_generation=route_generation,
        ),
    )


def _evidence(tmp_path: Path, prepared) -> finalizer.ControllerEvidence:
    records = []
    receipts = []
    endpoint_sha = hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
    for index in range(66):
        wave = index // 4
        run = prepared.controller_root / f"wave-{wave:03d}" / f"shard-{index:03d}-attempt-001"
        run.mkdir(parents=True, exist_ok=True)
        receipt = run / "route_guard_success.json"
        receipt.write_text("{}\n")
        receipt.chmod(0o600)
        receipts.append(receipt.resolve())
        records.append(
            {
                "index": index,
                "task_count": 1,
                "task_manifest_sha256": prepared.shards[index].task_manifest_sha256,
                "guard_success_receipt_sha256": f"{index + 100:064x}",
                "guard_success_receipt": {
                    "path": str(receipt.resolve()),
                    "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                },
                "eval_run_identity_sha256": f"{index + 200:064x}",
                "results_sha256": f"{index + 300:064x}",
                "route_generation_sha256": prepared.generation_sha256,
                "endpoint_binding_sha256": endpoint_sha,
                "expected_routes": 1,
            }
        )
    return finalizer.ControllerEvidence(
        train={"train_sha256": "e" * 64},
        state={"state_sha256": "f" * 64},
        shard_records=tuple(records),
        receipt_paths=tuple(receipts),
        supported_count=63,
        unsupported_count=3,
        solved_count=8,
    )


def _validated(prepared) -> dict:
    endpoint_sha = hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
    policy_sha = hashlib.sha256(finalizer.canonical_json(prepared.route_binding.proxy_policy)).hexdigest()
    return {
        "shard_count": 66,
        "supported_passes": 8,
        "supported_pass_rate": 8 / 63,
        "all_task_pass_rate": 8 / 66,
        "route_generation_sha256s": [prepared.generation_sha256],
        "endpoint_binding_sha256s": [endpoint_sha],
        "proxy_policy_sha256": policy_sha,
        "deployment_spec_sha256": prepared.deployment_spec.sha256,
        "certificate_sha256": "9" * 64,
    }


def _checkpoint_value(evidence: finalizer.ControllerEvidence, prepared, output: Path) -> dict:
    return {
        "shards": list(evidence.shard_records),
        "plan": {
            "path": str(prepared.plan_artifact.path),
            "sha256": prepared.plan_artifact.sha256,
            "plan_sha256": prepared.plan["plan_sha256"],
        },
        "distinct_route_generations": 1,
        "combined_trace_count": 66,
        "artifacts": {
            "results": {"path": str(output / "results.jsonl"), "sha256": "a" * 64},
            "audit_summary": {"path": str(output / "audit_summary.json"), "sha256": "a" * 64},
            "deployment_spec": {
                "path": str(output / "deployment_spec_policy.json"),
                "sha256": "a" * 64,
            },
            "proxy_policy": {"path": str(output / "proxy_policy.json"), "sha256": "a" * 64},
        },
    }


def _range_evidence(tmp_path: Path, prepared) -> finalizer.ControllerEvidence:
    records = []
    receipts = []
    endpoint_sha = hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
    for offset, index in enumerate(prepared.selected_indices):
        wave = offset // prepared.config.wave_size
        run = prepared.controller_root / f"wave-{wave:03d}" / f"shard-{index:03d}-attempt-001"
        run.mkdir(parents=True, exist_ok=True)
        receipt = run / "route_guard_success.json"
        receipt.write_text("{}\n")
        receipt.chmod(0o600)
        receipts.append(receipt.resolve())
        records.append(
            {
                "index": index,
                "task_count": 1,
                "task_manifest_sha256": prepared.shards[index].task_manifest_sha256,
                "guard_success_receipt_sha256": f"{index + 100:064x}",
                "guard_success_receipt": {
                    "path": str(receipt.resolve()),
                    "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                },
                "eval_run_identity_sha256": f"{index + 200:064x}",
                "results_sha256": f"{index + 300:064x}",
                "route_generation_sha256": prepared.generation_sha256,
                "endpoint_binding_sha256": endpoint_sha,
                "expected_routes": 1,
            }
        )
    supported = sum(index < 63 for index in prepared.selected_indices)
    solved = sum(index < 8 for index in prepared.selected_indices)
    return finalizer.ControllerEvidence(
        train={"train_sha256": f"{prepared.selected_indices[0] + 4000:064x}"},
        state={"state_sha256": f"{prepared.selected_indices[0] + 5000:064x}"},
        shard_records=tuple(records),
        receipt_paths=tuple(receipts),
        supported_count=supported,
        unsupported_count=len(prepared.selected_indices) - supported,
        solved_count=solved,
    )


def _multi_value(evidence: finalizer.ControllerEvidence, prepared, output: Path) -> dict:
    value = _checkpoint_value(evidence, prepared, output)
    value["distinct_route_generations"] = len({record["route_generation_sha256"] for record in evidence.shard_records})
    policy_sha256s = sorted({record["proxy_policy_sha256"] for record in evidence.shard_records})
    policy_artifacts = {
        policy_sha256: {
            "path": str(output / f"proxy_policy_{policy_sha256}.json"),
            "sha256": "a" * 64,
        }
        for policy_sha256 in policy_sha256s
    }
    value["artifacts"] = {
        **{key: item for key, item in value["artifacts"].items() if key != "proxy_policy"},
        "proxy_policies": [
            {"policy_sha256": policy_sha256, **policy_artifacts[policy_sha256]} for policy_sha256 in policy_sha256s
        ],
    }
    value["shards"] = [
        {**record, "proxy_policy_artifact": policy_artifacts[record["proxy_policy_sha256"]]}
        for record in evidence.shard_records
    ]
    return value


def _validated_multi(prepared, evidence: finalizer.ControllerEvidence) -> dict:
    base = _validated(prepared)
    policy = dict(prepared.route_binding.proxy_policy)
    policy.pop("proxy_litellm_config", None)
    base.pop("proxy_policy_sha256")
    base["proxy_policy_semantics_sha256"] = hashlib.sha256(finalizer.canonical_json(policy)).hexdigest()
    base["route_generation_sha256s"] = sorted({record["route_generation_sha256"] for record in evidence.shard_records})
    base["endpoint_binding_sha256s"] = sorted({record["endpoint_binding_sha256"] for record in evidence.shard_records})
    base["supported_passes"] = evidence.solved_count
    base["supported_pass_rate"] = evidence.solved_count / 63
    base["all_task_pass_rate"] = evidence.solved_count / 66
    return base


def test_collect_revalidates_complete_history_and_derives_exact_receipts(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    expected = _evidence(tmp_path, prepared)
    train = {"train_sha256": "e" * 64}
    completed_waves = []
    completions = {}
    position = 0
    for wave_number in range(17):
        stop = min(position + 4, 66)
        indices = tuple(range(position, stop))
        jobs = []
        for index in indices:
            record = expected.shard_records[index]
            jobs.append(
                {
                    "artifacts": {
                        "route_guard_success": record["guard_success_receipt"]["sha256"],
                        "results": record["results_sha256"],
                    },
                    "guard_success_receipt_sha256": record["guard_success_receipt_sha256"],
                    "eval_run_identity_sha256": record["eval_run_identity_sha256"],
                    "route_generation_sha256": record["route_generation_sha256"],
                }
            )
        supported = sum(index < 63 for index in indices)
        solved = sum(index < 8 for index in indices)
        file_sha256 = f"{wave_number + 500:064x}"
        completions[wave_number] = (
            {
                "jobs": jobs,
                "counts": {
                    "jobs": len(indices),
                    "supported": supported,
                    "unsupported": len(indices) - supported,
                    "solved": solved,
                },
            },
            file_sha256,
        )
        completed_waves.append(
            {
                "wave_number": wave_number,
                "shard_indices": list(indices),
                "completion": {
                    "path": str(prepared.controller_root / f"wave-{wave_number:03d}" / "completion.json"),
                    "sha256": file_sha256,
                },
            }
        )
        position = stop
    state = {
        "state": "complete",
        "next_position": 66,
        "current_wave": None,
        "failure": None,
        "completed_waves": completed_waves,
        "state_sha256": "f" * 64,
    }

    def load(path, *, label, hash_key):
        del label, hash_key
        return (train, "1" * 64) if path.name == "train.json" else (state, "2" * 64)

    monkeypatch.setattr(finalizer, "_load_private_json", load)
    monkeypatch.setattr(finalizer, "_train_body", lambda _prepared: {})
    monkeypatch.setattr(finalizer, "_validate_state", lambda *_args: None)
    monkeypatch.setattr(finalizer, "_validate_completed_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(finalizer, "_load_wave_metadata", lambda *_args, **_kwargs: {"jobs": []})
    monkeypatch.setattr(
        finalizer,
        "_load_completion",
        lambda _prepared, _train_sha, wave_number, *_args: completions[wave_number],
    )

    observed = finalizer._collect_controller_evidence(prepared, "e" * 64)

    assert observed.shard_records == expected.shard_records
    assert observed.receipt_paths == expected.receipt_paths
    assert observed.supported_count == 63
    assert observed.unsupported_count == 3
    assert observed.solved_count == 8


def test_multigen_finalizer_allows_disjoint_ranges_with_different_route_generations(tmp_path: Path, monkeypatch):
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=32)
    second = _prepared(
        tmp_path,
        root_name="controller-b",
        first_shard_index=32,
        shard_count=34,
        route_generation=_controller_route_generation(backend_sha256="9" * 64),
    )
    second.proxy_info = first.proxy_info
    second.route_binding.endpoint = first.route_binding.endpoint
    prepared_by_root = {first.controller_root: first, second.controller_root: second}
    evidence_by_root = {
        first.controller_root: _range_evidence(tmp_path, first),
        second.controller_root: _range_evidence(tmp_path, second),
    }
    inputs = tuple(
        finalizer.ControllerFinalizerInput(
            controller=SimpleNamespace(controller_root=prepared.controller_root),
            expected_train_sha256=evidence_by_root[prepared.controller_root].train["train_sha256"],
        )
        for prepared in (first, second)
    )
    output = tmp_path / "final"

    monkeypatch.setattr(
        finalizer, "prepare_train", lambda controller, **_kwargs: prepared_by_root[controller.controller_root]
    )
    monkeypatch.setattr(finalizer, "_validate_controller_root", lambda root: root)
    monkeypatch.setattr(
        finalizer,
        "_collect_selected_controller_evidence",
        lambda prepared, _sha: evidence_by_root[prepared.controller_root],
    )
    monkeypatch.setattr(finalizer, "_resolved_multigen_output", lambda *_args: output)

    def merge(_plan, receipts, *, output_dir, **_kwargs):
        assert len(receipts) == 66
        evidence = finalizer._combined_multigen_evidence(
            (
                (first, evidence_by_root[first.controller_root]),
                (second, evidence_by_root[second.controller_root]),
            )
        )
        value = _multi_value(evidence, first, output_dir)
        _write_output(output_dir, value, multigen=True)
        return value

    observed_evidence = finalizer._combined_multigen_evidence(
        (
            (first, evidence_by_root[first.controller_root]),
            (second, evidence_by_root[second.controller_root]),
        )
    )
    expected_policy_sha256 = hashlib.sha256(finalizer.canonical_json(first.route_binding.proxy_policy)).hexdigest()
    assert observed_evidence.shard_records[0]["proxy_config_snapshot"] == {
        "path": str(first.proxy_config_snapshot.path),
        "sha256": first.proxy_config_snapshot.sha256,
    }
    assert observed_evidence.shard_records[32]["proxy_config_snapshot"] == {
        "path": str(second.proxy_config_snapshot.path),
        "sha256": second.proxy_config_snapshot.sha256,
    }
    assert {record["proxy_policy_sha256"] for record in observed_evidence.shard_records} == {expected_policy_sha256}
    monkeypatch.setattr(finalizer, "merge_multigen_shards", merge)
    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint",
        lambda *_args, **_kwargs: _validated_multi(first, observed_evidence),
    )

    summary = finalizer._finalize_multigen_locked(
        finalizer.MultiGenerationFinalizerConfig(controllers=inputs, output_dir=output),
        command_runner=lambda *_args, **_kwargs: None,
    )

    assert summary["state"] == "passed"
    assert summary["combined_trace_count"] == 66
    assert summary["distinct_route_generations"] == 2


def test_multigen_finalizer_rejects_gap_and_overlap(tmp_path: Path):
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=32)
    gap = _prepared(
        tmp_path,
        root_name="controller-gap",
        first_shard_index=33,
        shard_count=33,
        route_generation=_controller_route_generation(backend_sha256="8" * 64),
    )
    overlap = _prepared(
        tmp_path,
        root_name="controller-overlap",
        first_shard_index=31,
        shard_count=35,
        route_generation=_controller_route_generation(backend_sha256="9" * 64),
    )
    for prepared in (gap, overlap):
        prepared.proxy_info = first.proxy_info
        prepared.route_binding.endpoint = first.route_binding.endpoint
    first_evidence = _range_evidence(tmp_path, first)

    with pytest.raises(finalizer.FinalizationError, match="controller_coverage_gap"):
        finalizer._combined_multigen_evidence(((first, first_evidence), (gap, _range_evidence(tmp_path, gap))))

    with pytest.raises(finalizer.FinalizationError, match="controller_coverage_overlap"):
        finalizer._combined_multigen_evidence(((first, first_evidence), (overlap, _range_evidence(tmp_path, overlap))))


def test_multigen_finalizer_rejects_mixed_policy(tmp_path: Path):
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=32)
    second = _prepared(tmp_path, root_name="controller-b", first_shard_index=32, shard_count=34)
    second.deployment_spec.sha256 = "c" * 64

    with pytest.raises(finalizer.FinalizationError, match="controller_policy_mismatch"):
        finalizer._combined_multigen_evidence(
            ((first, _range_evidence(tmp_path, first)), (second, _range_evidence(tmp_path, second)))
        )

    second.deployment_spec.sha256 = first.deployment_spec.sha256
    second.config.deployment_id = "other-deployment"
    with pytest.raises(finalizer.FinalizationError, match="controller_policy_mismatch"):
        finalizer._combined_multigen_evidence(
            ((first, _range_evidence(tmp_path, first)), (second, _range_evidence(tmp_path, second)))
        )


def test_multigen_fingerprint_permits_generation_artifact_rotation(tmp_path: Path):
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=32)
    second = _prepared(
        tmp_path,
        root_name="controller-b",
        first_shard_index=32,
        shard_count=34,
        route_generation=_controller_route_generation(backend_sha256="9" * 64),
    )
    first.readiness = SimpleNamespace(path=tmp_path / "readiness-a.json", sha256="a" * 64)
    first.smoke = SimpleNamespace(path=tmp_path / "smoke-a.json", sha256="c" * 64)
    second.readiness = SimpleNamespace(path=tmp_path / "readiness-b.json", sha256="d" * 64)
    second.smoke = SimpleNamespace(path=tmp_path / "smoke-b.json", sha256="f" * 64)
    second.proxy_info = first.proxy_info
    second.route_binding.endpoint = first.route_binding.endpoint

    assert finalizer._controller_policy_fingerprint(first) == finalizer._controller_policy_fingerprint(second)


def test_multigen_accepts_two_disjoint_chunks_from_exact_same_generation(tmp_path: Path) -> None:
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=33)
    second = _prepared(tmp_path, root_name="controller-b", first_shard_index=33, shard_count=33)
    second.proxy_info = first.proxy_info
    second.route_binding.endpoint = first.route_binding.endpoint

    evidence = finalizer._combined_multigen_evidence(
        ((first, _range_evidence(tmp_path, first)), (second, _range_evidence(tmp_path, second)))
    )

    assert len(evidence.shard_records) == 66
    assert {record["route_generation_sha256"] for record in evidence.shard_records} == {first.generation_sha256}


def test_multigen_duplicate_and_rotated_generations_are_order_independent(tmp_path: Path) -> None:
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=22)
    duplicate = _prepared(tmp_path, root_name="controller-b", first_shard_index=22, shard_count=22)
    rotated = _prepared(
        tmp_path,
        root_name="controller-c",
        first_shard_index=44,
        shard_count=22,
        route_generation=_controller_route_generation(backend_sha256="9" * 64),
    )
    for prepared in (duplicate, rotated):
        prepared.proxy_info = first.proxy_info
        prepared.route_binding.endpoint = first.route_binding.endpoint
    evidence_by_root = {
        prepared.controller_root: _range_evidence(tmp_path, prepared) for prepared in (first, duplicate, rotated)
    }

    forward = finalizer._combined_multigen_evidence(
        tuple((prepared, evidence_by_root[prepared.controller_root]) for prepared in (first, duplicate, rotated))
    )
    reordered = finalizer._combined_multigen_evidence(
        tuple((prepared, evidence_by_root[prepared.controller_root]) for prepared in (rotated, duplicate, first))
    )

    assert forward.shard_records == reordered.shard_records
    assert {record["route_generation_sha256"] for record in forward.shard_records} == {
        first.generation_sha256,
        rotated.generation_sha256,
    }


@pytest.mark.parametrize("mismatch", ["endpoint", "proxy_info", "coordinator", "proxy"])
def test_multigen_rejects_cross_controller_proxy_or_coordinator_incarnation(
    tmp_path: Path,
    mismatch: str,
) -> None:
    first = _prepared(tmp_path, root_name="controller-a", first_shard_index=0, shard_count=32)
    second = _prepared(
        tmp_path,
        root_name="controller-b",
        first_shard_index=32,
        shard_count=34,
        route_generation=_controller_route_generation(backend_sha256="9" * 64),
    )
    second.proxy_info = first.proxy_info
    second.route_binding.endpoint = json.loads(json.dumps(first.route_binding.endpoint))
    if mismatch == "endpoint":
        second.route_binding.endpoint["authority_sha256"] = "8" * 64
    elif mismatch == "proxy_info":
        second.proxy_info = SimpleNamespace(path=(tmp_path / "other-proxy-info.json").resolve(), sha256="8" * 64)
        second.route_binding.endpoint["proxy_info"] = {
            "path": str(second.proxy_info.path),
            "sha256": second.proxy_info.sha256,
        }
    elif mismatch == "coordinator":
        second.route_binding.route_generation["coordinator"] = {
            "slurm_job_id": "901",
            "started_at": "2026-09-17T00:00:00Z",
        }
    else:
        second.route_binding.route_generation["proxy"] = {
            "slurm_job_id": "12346",
            "first_ready_at": "2026-09-17T00:30:00Z",
        }
    second.generation_sha256 = hashlib.sha256(
        finalizer.canonical_json(second.route_binding.route_generation)
    ).hexdigest()

    with pytest.raises(finalizer.FinalizationError, match="controller_policy_mismatch"):
        finalizer._combined_multigen_evidence(
            ((first, _range_evidence(tmp_path, first)), (second, _range_evidence(tmp_path, second)))
        )


def _write_manifest(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    path.chmod(0o600)


def _valid_multigen_manifest(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "project_dir": str(tmp_path / "project"),
        "project_revision": "1" * 40,
        "plan": str(tmp_path / "plan.json"),
        "plan_sha256": "2" * 64,
        "deployment_id": "deployment-test",
        "deployment_spec": str(tmp_path / "spec.yaml"),
        "deployment_spec_sha256": "3" * 64,
        "dataset_revision": "4" * 40,
        "controllers": [
            {
                "controller_root": str(tmp_path / "controller-a"),
                "train_sha256": "5" * 64,
                "readiness_checkpoint": str(tmp_path / "readiness-a.json"),
                "readiness_checkpoint_sha256": "6" * 64,
                "proxy_info": str(tmp_path / "proxy-a.json"),
                "proxy_info_sha256": "7" * 64,
                "proxy_config_snapshot": str(tmp_path / "proxy-config-a.yaml"),
                "proxy_config_snapshot_sha256": "9" * 64,
                "smoke_checkpoint": str(tmp_path / "smoke-a.json"),
                "smoke_checkpoint_sha256": "8" * 64,
                "first_shard_index": 0,
                "shard_count": 66,
            }
        ],
    }


def test_multigen_manifest_rejects_unknown_keys_and_dataset_aliases(tmp_path: Path):
    manifest = _valid_multigen_manifest(tmp_path)
    manifest["unexpected"] = True
    path = tmp_path / "manifest.json"
    _write_manifest(path, manifest)
    with pytest.raises(finalizer.FinalizationError, match="manifest_unknown_key"):
        multigen_cli.config_from_manifest(path, tmp_path / "final")

    manifest = _valid_multigen_manifest(tmp_path)
    manifest["controllers"][0]["unexpected"] = True
    _write_manifest(path, manifest)
    with pytest.raises(finalizer.FinalizationError, match="manifest_unknown_key"):
        multigen_cli.config_from_manifest(path, tmp_path / "final")

    manifest = _valid_multigen_manifest(tmp_path)
    manifest["dataset_archive"] = str(tmp_path / "dataset.tar.gz")
    manifest["dataset_archive_sha256"] = "9" * 64
    manifest["dataset_content_sha256"] = "a" * 64
    _write_manifest(path, manifest)
    with pytest.raises(finalizer.FinalizationError, match="manifest_invalid"):
        multigen_cli.config_from_manifest(path, tmp_path / "final")


def test_multigen_manifest_rejects_duplicate_keys(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version":1,"schema_version":1}\n')
    path.chmod(0o600)

    with pytest.raises(finalizer.FinalizationError, match="manifest_invalid"):
        multigen_cli.config_from_manifest(path, tmp_path / "final")


def test_multigen_timing_validation_matches_single_finalizer(tmp_path: Path):
    config = finalizer.MultiGenerationFinalizerConfig(
        controllers=(
            finalizer.ControllerFinalizerInput(
                controller=SimpleNamespace(controller_root=tmp_path / "controller"),
                expected_train_sha256="e" * 64,
            ),
        ),
        output_dir=tmp_path / "final",
        lock_poll_seconds=True,
    )

    with pytest.raises(finalizer.FinalizationError, match="finalizer_timing_invalid"):
        finalizer.finalize_multigen_wave_train(config, command_runner=lambda *_args, **_kwargs: None)


def test_multigen_checkpoint_rejects_tampered_route_generation_summary(tmp_path: Path, monkeypatch):
    first = _prepared(tmp_path)
    evidence = finalizer._combined_multigen_evidence(((first, _evidence(tmp_path, first)),))
    value = _multi_value(evidence, first, tmp_path / "final")
    output = tmp_path / "final"
    _write_output(output, value, multigen=True)
    bad = _validated_multi(first, evidence)
    bad["route_generation_sha256s"] = ["0" * 64]
    monkeypatch.setattr(finalizer, "validate_multigen_sharded_checkpoint", lambda *_args, **_kwargs: bad)

    with pytest.raises(finalizer.FinalizationError, match="sharded_checkpoint_controller_mismatch"):
        finalizer._load_and_validate_multigen_checkpoint(
            output,
            first,
            evidence,
            expected_value=value,
            expected_route_generation_sha256s=[first.generation_sha256],
            expected_endpoint_binding_sha256s=[
                hashlib.sha256(finalizer.canonical_json(first.route_binding.endpoint)).hexdigest()
            ],
        )


@pytest.mark.parametrize("binding", ["snapshot_path", "snapshot_sha256", "proxy_policy_sha256"])
def test_reused_multigen_checkpoint_is_cross_bound_to_controller_snapshot_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding: str,
) -> None:
    prepared = _prepared(tmp_path)
    evidence = finalizer._combined_multigen_evidence(((prepared, _evidence(tmp_path, prepared)),))
    output = tmp_path / "final"
    value = json.loads(json.dumps(_multi_value(evidence, prepared, output)))
    if binding == "snapshot_path":
        value["shards"][0]["proxy_config_snapshot"]["path"] = str(tmp_path / "other-snapshot.yaml")
    elif binding == "snapshot_sha256":
        value["shards"][0]["proxy_config_snapshot"]["sha256"] = "0" * 64
    else:
        value["shards"][0]["proxy_policy_sha256"] = "0" * 64
    _write_output(output, value, multigen=True)
    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint",
        lambda *_args, **_kwargs: _validated_multi(prepared, evidence),
    )

    with pytest.raises(finalizer.FinalizationError, match="sharded_checkpoint_controller_mismatch"):
        finalizer._load_and_validate_multigen_checkpoint(
            output,
            prepared,
            evidence,
            expected_value=None,
            expected_route_generation_sha256s=[prepared.generation_sha256],
            expected_endpoint_binding_sha256s=[
                hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
            ],
        )


def test_multigen_checkpoint_rejects_unreferenced_policy_artifact(tmp_path: Path, monkeypatch) -> None:
    prepared = _prepared(tmp_path)
    evidence = finalizer._combined_multigen_evidence(((prepared, _evidence(tmp_path, prepared)),))
    output = tmp_path / "final"
    value = _multi_value(evidence, prepared, output)
    _write_output(output, value, multigen=True)
    extra = output / f"proxy_policy_{'b' * 64}.json"
    extra.write_text("{}\n")
    extra.chmod(0o600)
    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint",
        lambda *_args, **_kwargs: _validated_multi(prepared, evidence),
    )

    with pytest.raises(finalizer.FinalizationError, match="merge_output_invalid"):
        finalizer._load_and_validate_multigen_checkpoint(
            output,
            prepared,
            evidence,
            expected_value=None,
            expected_route_generation_sha256s=[prepared.generation_sha256],
            expected_endpoint_binding_sha256s=[
                hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
            ],
        )


def test_collect_rejects_self_consistent_but_unexpected_train(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    train = {"unexpected": True, "train_sha256": "e" * 64}
    monkeypatch.setattr(finalizer, "_load_private_json", lambda *_args, **_kwargs: (train, "1" * 64))
    monkeypatch.setattr(finalizer, "_train_body", lambda _prepared: {"expected": True})

    with pytest.raises(finalizer.FinalizationError, match="train_spec_mismatch"):
        finalizer._collect_controller_evidence(prepared, "e" * 64)


def test_collect_accepts_legacy_train_without_proxy_config_snapshot(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    current_body = finalizer._train_body(prepared)
    assert "proxy_config_snapshot" in current_body["deployment"]
    legacy_body = {
        **current_body,
        "deployment": {
            key: value for key, value in current_body["deployment"].items() if key != "proxy_config_snapshot"
        },
    }
    reads = iter(
        (
            ({**legacy_body, "train_sha256": "e" * 64}, "1" * 64),
            ({"state": "complete"}, "2" * 64),
        )
    )
    monkeypatch.setattr(finalizer, "_load_private_json", lambda *_args, **_kwargs: next(reads))
    monkeypatch.setattr(
        finalizer,
        "_validate_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(finalizer.FinalizationError("after_train")),
    )

    with pytest.raises(finalizer.FinalizationError, match="after_train"):
        finalizer._collect_selected_controller_evidence(prepared, "e" * 64)


def test_collect_rejects_untrusted_train_hash(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    train = {"train_sha256": "e" * 64}
    monkeypatch.setattr(finalizer, "_load_private_json", lambda *_args, **_kwargs: (train, "1" * 64))
    monkeypatch.setattr(finalizer, "_train_body", lambda _prepared: {})

    with pytest.raises(finalizer.FinalizationError, match="train_spec_mismatch"):
        finalizer._collect_controller_evidence(prepared, "d" * 64)


def _write_output(output: Path, value: dict, *, multigen: bool = False) -> bytes:
    output.mkdir(mode=0o700)
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    artifacts = (
        [(Path(item["path"]).name, b"{}\n") for item in value.get("artifacts", {}).get("proxy_policies", [])]
        if multigen
        else [("proxy_policy.json", b"{}\n")]
    )
    for name, payload in [
        ("results.jsonl", b"results\n"),
        ("audit_summary.json", b"{}\n"),
        ("deployment_spec_policy.json", b"{}\n"),
        ("checkpoint.json", raw),
        *artifacts,
    ]:
        path = output / name
        path.write_bytes(payload)
        path.chmod(0o600)
    return raw


def _load_reused_checkpoint(
    output: Path,
    prepared,
    evidence: finalizer.ControllerEvidence,
    *,
    multigen: bool,
):
    if not multigen:
        return finalizer._load_and_validate_checkpoint(
            output,
            prepared,
            evidence,
            expected_value=None,
        )
    return finalizer._load_and_validate_multigen_checkpoint(
        output,
        prepared,
        evidence,
        expected_value=None,
        expected_route_generation_sha256s=[prepared.generation_sha256],
        expected_endpoint_binding_sha256s=[
            hashlib.sha256(finalizer.canonical_json(prepared.route_binding.endpoint)).hexdigest()
        ],
    )


@pytest.mark.parametrize("multigen", [False, True], ids=["schema2", "schema3"])
def test_reuse_accepts_exact_local_checkpoint_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    multigen: bool,
) -> None:
    prepared = _prepared(tmp_path)
    evidence = _evidence(tmp_path, prepared)
    if multigen:
        evidence = finalizer._combined_multigen_evidence(((prepared, evidence),))
    output = tmp_path / "final"
    value = _multi_value(evidence, prepared, output) if multigen else _checkpoint_value(evidence, prepared, output)
    raw = _write_output(output, value, multigen=multigen)
    validated = _validated_multi(prepared, evidence) if multigen else _validated(prepared)

    def validate(
        checkpoint: dict,
        *,
        deployment_id: str,
        artifact_root: Path,
    ) -> dict:
        assert checkpoint == value
        assert deployment_id == prepared.config.deployment_id
        assert artifact_root == output
        return validated

    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint" if multigen else "validate_sharded_checkpoint",
        validate,
    )

    observed, observed_raw = _load_reused_checkpoint(
        output,
        prepared,
        evidence,
        multigen=multigen,
    )

    assert observed == validated
    assert observed_raw == raw


@pytest.mark.parametrize("multigen", [False, True], ids=["schema2", "schema3"])
@pytest.mark.parametrize("layout", ["external_parent", "external_policy", "symlink", "path_alias"])
def test_reuse_rejects_checkpoint_artifacts_outside_exact_output_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    multigen: bool,
    layout: str,
) -> None:
    prepared = _prepared(tmp_path)
    evidence = _evidence(tmp_path, prepared)
    if multigen:
        evidence = finalizer._combined_multigen_evidence(((prepared, evidence),))
    output = tmp_path / "final"
    value = _multi_value(evidence, prepared, output) if multigen else _checkpoint_value(evidence, prepared, output)
    artifacts = value["artifacts"]
    external = tmp_path / "external"
    if layout in {"external_parent", "external_policy"}:
        external.mkdir(mode=0o700)
        payloads = (
            {
                "results": ("results.jsonl", b"results\n"),
                "audit_summary": ("audit_summary.json", b"{}\n"),
                "deployment_spec": ("deployment_spec_policy.json", b"{}\n"),
            }
            if layout == "external_parent"
            else {}
        )
        if not multigen and layout in {"external_parent", "external_policy"}:
            payloads["proxy_policy"] = ("proxy_policy.json", b"{}\n")
        for key, (name, payload) in payloads.items():
            path = external / name
            path.write_bytes(payload)
            path.chmod(0o600)
            artifacts[key] = {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}
        if multigen:
            policy_artifacts: dict[str, dict[str, str]] = {}
            for item in artifacts["proxy_policies"]:
                payload = b"{}\n"
                path = external / Path(item["path"]).name
                path.write_bytes(payload)
                path.chmod(0o600)
                item["path"] = str(path)
                item["sha256"] = hashlib.sha256(payload).hexdigest()
                policy_artifacts[item["policy_sha256"]] = {
                    "path": item["path"],
                    "sha256": item["sha256"],
                }
            for shard in value["shards"]:
                shard["proxy_policy_artifact"] = policy_artifacts[shard["proxy_policy_sha256"]]
    elif layout == "path_alias":
        artifacts["results"]["path"] = str(output / ".." / output.name / "results.jsonl")
    _write_output(output, value, multigen=multigen)
    if layout == "symlink":
        external.mkdir(mode=0o700)
        external_result = external / "results.jsonl"
        external_result.write_text("results\n")
        external_result.chmod(0o600)
        local_result = output / "results.jsonl"
        local_result.unlink()
        local_result.symlink_to(external_result)
    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint" if multigen else "validate_sharded_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("validator must not read relocated artifacts")),
    )

    with pytest.raises(
        finalizer.FinalizationError,
        match="^(merge_output_invalid|sharded_checkpoint_output_artifact_mismatch)$",
    ):
        _load_reused_checkpoint(
            output,
            prepared,
            evidence,
            multigen=multigen,
        )


@pytest.mark.parametrize("attack", ["external", "path_alias", "symlink"])
def test_schema3_reuse_rejects_one_unbound_shard_policy_before_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    prepared = _prepared(tmp_path)
    evidence = finalizer._combined_multigen_evidence(((prepared, _evidence(tmp_path, prepared)),))
    output = tmp_path / "final"
    value = _multi_value(evidence, prepared, output)
    policy = value["artifacts"]["proxy_policies"][0]
    policy_sha256 = hashlib.sha256(b"{}\n").hexdigest()
    policy["sha256"] = policy_sha256
    for shard in value["shards"]:
        shard["proxy_policy_artifact"]["sha256"] = policy_sha256
    expected_policy = Path(policy["path"])
    if attack == "external":
        external_policy = tmp_path / "external-policy.json"
    elif attack == "path_alias":
        external_policy = output / ".." / output.name / expected_policy.name
    else:
        external_policy = tmp_path / "policy-symlink.json"
    value["shards"][0]["proxy_policy_artifact"] = {
        "path": str(external_policy),
        "sha256": policy_sha256,
    }
    _write_output(output, value, multigen=True)
    if attack == "external":
        external_policy.write_bytes(b"{}\n")
        external_policy.chmod(0o600)
    elif attack == "symlink":
        external_policy.symlink_to(expected_policy)
    monkeypatch.setattr(
        finalizer,
        "validate_multigen_sharded_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("validator must not read an unbound shard policy")
        ),
    )

    with pytest.raises(finalizer.FinalizationError, match="^sharded_checkpoint_controller_mismatch$"):
        _load_reused_checkpoint(
            output,
            prepared,
            evidence,
            multigen=True,
        )


def test_checkpoint_is_exactly_cross_bound_to_controller(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    evidence = _evidence(tmp_path, prepared)
    output = tmp_path / "final"
    value = _checkpoint_value(evidence, prepared, output)
    raw = _write_output(output, value)
    monkeypatch.setattr(finalizer, "validate_sharded_checkpoint", lambda *_args, **_kwargs: _validated(prepared))

    validated, observed_raw = finalizer._load_and_validate_checkpoint(
        output,
        prepared,
        evidence,
        expected_value=value,
    )

    assert validated["supported_pass_rate"] == pytest.approx(8 / 63)
    assert observed_raw == raw


def test_checkpoint_rejects_generation_or_output_member_mismatch(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    evidence = _evidence(tmp_path, prepared)
    output = tmp_path / "final"
    value = _checkpoint_value(evidence, prepared, output)
    _write_output(output, value)
    bad = _validated(prepared)
    bad["route_generation_sha256s"] = ["0" * 64]
    monkeypatch.setattr(finalizer, "validate_sharded_checkpoint", lambda *_args, **_kwargs: bad)

    with pytest.raises(finalizer.FinalizationError, match="sharded_checkpoint_controller_mismatch"):
        finalizer._load_and_validate_checkpoint(output, prepared, evidence, expected_value=value)

    (output / "unexpected").write_text("no")
    with pytest.raises(finalizer.FinalizationError, match="merge_output_invalid"):
        finalizer._load_and_validate_checkpoint(output, prepared, evidence, expected_value=value)


def test_finalize_is_idempotent_after_atomic_publish(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    evidence = _evidence(tmp_path, prepared)
    output = tmp_path / "final"
    output.mkdir(mode=0o700)
    config = _config(tmp_path, output_dir=output)
    monkeypatch.setattr(finalizer, "prepare_train", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(finalizer, "_collect_controller_evidence", lambda *_args: evidence)
    monkeypatch.setattr(finalizer, "_resolved_output", lambda *_args: output)
    monkeypatch.setattr(
        finalizer,
        "merge_shards",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("merge must not run")),
    )
    monkeypatch.setattr(
        finalizer,
        "_load_and_validate_checkpoint",
        lambda *_args, **_kwargs: (_validated(prepared), b"checkpoint\n"),
    )

    summary = finalizer._finalize_locked(config, command_runner=lambda *_args, **_kwargs: None)

    assert summary["state"] == "passed"
    assert summary["reused_existing"] is True
    assert summary["supported_passes"] == 8


def test_finalize_requires_exact_four_wide_controller(tmp_path: Path, monkeypatch):
    prepared = _prepared(tmp_path)
    prepared.config.wave_size = 2
    config = _config(tmp_path)
    monkeypatch.setattr(finalizer, "prepare_train", lambda *_args, **_kwargs: prepared)

    with pytest.raises(finalizer.FinalizationError, match="full_singleton_plan_required"):
        finalizer._finalize_locked(config, command_runner=lambda *_args, **_kwargs: None)


def test_dangling_output_symlink_is_never_reused(tmp_path: Path):
    prepared = _prepared(tmp_path)
    output = tmp_path / "final"
    output.symlink_to(tmp_path / "missing", target_is_directory=True)

    with pytest.raises(finalizer.FinalizationError, match="merge_output_invalid"):
        finalizer._resolved_output(output, prepared)


@pytest.mark.parametrize("protected_name", ["dataset_path", "plan_root"])
def test_output_cannot_mutate_pinned_input_trees(tmp_path: Path, protected_name: str):
    prepared = _prepared(tmp_path)
    protected = prepared.dataset_path if protected_name == "dataset_path" else prepared.plan_artifact.path.parent

    with pytest.raises(finalizer.FinalizationError, match="merge_output_invalid"):
        finalizer._resolved_output(protected / "final", prepared)


def test_output_parent_must_preexist_and_be_private(tmp_path: Path):
    prepared = _prepared(tmp_path)
    missing_parent = tmp_path / "missing"
    with pytest.raises(finalizer.FinalizationError, match="merge_output_parent_invalid"):
        finalizer._resolved_output(missing_parent / "final", prepared)

    public_parent = tmp_path / "public"
    public_parent.mkdir(mode=0o755)
    public_parent.chmod(0o755)
    with pytest.raises(finalizer.FinalizationError, match="merge_output_parent_invalid"):
        finalizer._resolved_output(public_parent / "final", prepared)


def test_cli_failure_is_aggregate_only(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setattr(
        finalizer,
        "finalize_wave_train",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sensitive detail")),
    )
    args = [
        "--controller-root",
        str(tmp_path / "controller"),
        "--train-sha256",
        "e" * 64,
        "--project-dir",
        str(tmp_path / "project"),
        "--project-revision",
        "1" * 40,
        "--plan",
        str(tmp_path / "plan"),
        "--plan-sha256",
        "2" * 64,
        "--deployment-id",
        "deployment-test",
        "--deployment-spec",
        str(tmp_path / "spec"),
        "--deployment-spec-sha256",
        "3" * 64,
        "--readiness-checkpoint",
        str(tmp_path / "readiness"),
        "--readiness-checkpoint-sha256",
        "4" * 64,
        "--proxy-info",
        str(tmp_path / "proxy"),
        "--proxy-info-sha256",
        "5" * 64,
        "--smoke-checkpoint",
        str(tmp_path / "smoke"),
        "--smoke-checkpoint-sha256",
        "6" * 64,
        "--dataset-revision",
        "7" * 40,
        "--output-dir",
        str(tmp_path / "final"),
    ]

    assert finalizer.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "tb4_wave_train_finalize_error:finalization_failed\n"
    assert "sensitive" not in captured.err
