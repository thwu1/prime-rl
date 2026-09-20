import asyncio
import hashlib
import importlib.util
import json
import signal
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

RUN_ORACLE = Path(__file__).parents[1] / "run_oracle.py"
RUN_ORACLE_SBATCH = Path(__file__).parents[1] / "run_oracle.sbatch"
SPEC = importlib.util.spec_from_file_location("terminal_bench_vmvm_run_oracle", RUN_ORACLE)
assert SPEC is not None and SPEC.loader is not None
run_oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_oracle)


def test_oracle_wrapper_binds_resume_and_python_cache_policy() -> None:
    source = RUN_ORACLE_SBATCH.read_text()

    assert "oracle_resume=${ORACLE_RESUME:-1}" in source
    assert "args+=(--no-resume)" in source
    assert "args+=(--resume)" in source
    assert "export PYTHONPYCACHEPREFIX=/dev/null" in source
    assert "export UV_NO_CONFIG=1" in source
    assert '"$x86_uv" --no-config run --no-project --offline' in source
    assert 'python3 -B "$workflow_dir/run_oracle.py"' in source
    assert "character special file:666:0:0:1:3:1" in source


def _identity_args(tmp_path: Path) -> SimpleNamespace:
    task_file = tmp_path / "tasks.txt"
    task_file.write_text("alpha\nbeta\n")
    image_manifest = tmp_path / "images.json"
    image_manifest.write_text("{}\n")
    return SimpleNamespace(
        dataset_dir=tmp_path / "dataset",
        dataset_revision="a" * 40,
        dataset_archive=None,
        dataset_archive_sha256=None,
        task_file=task_file,
        task_file_sha256=hashlib.sha256(task_file.read_bytes()).hexdigest(),
        image_prefix="registry.example/tasks",
        image_tag="dataset-a",
        image_manifest=image_manifest,
        image_manifest_sha256=hashlib.sha256(image_manifest.read_bytes()).hexdigest(),
        source_wheel_policy=None,
        source_wheel_policy_sha256=None,
        source_wheel_attestation_sha256=None,
        use_declared_images=False,
        enable_compose=True,
        offset=0,
        limit=None,
        prime_rl_commit="b" * 40,
        prime_rl_tree_sha256=run_oracle.CLEAN_TREE_SHA256,
        verifiers_commit="c" * 40,
        vmvm_tb_v2_sha256="d" * 64,
        oracle_solution_network_mode="public",
        max_concurrent=32,
        infra_retries=2,
        setup_timeout=3600.0,
        validate_timeout=10800.0,
        session_timeout=10800.0,
        tenant_id="tenant",
        lease_ttl="60s",
        max_session_buffer_size=67_108_864,
        verifier_runtime_retries=2,
        vacli_lease_retries=20,
        vacli_max_concurrent_leases=4,
        vacli_max_pull_retries=20,
        vacli_image_pull_timeout_seconds=3600,
        vacli_container_privileged=1,
        timeout_multiplier=1.0,
        resource_multiplier=1.0,
        minimum_pass_rate=0.9,
        minimum_valid=2,
        invocation_host="worker.example",
        slurm_job_id="12345",
        resume=True,
        rerun_invalid=False,
    )


def _tasks() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(idx=0, name="alpha", slug="alpha", image="registry.example/tasks:alpha"),
        SimpleNamespace(idx=1, name="beta", slug="beta", image="registry.example/tasks:beta"),
    ]


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
    identity_sha256 = "f" * 64
    summary = run_oracle._summary(
        [{"valid": True, "reason": "valid"}, {"valid": False, "reason": "invalid"}],
        2,
        semantics,
        identity_sha256,
    )

    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["oracle_network_semantics"] == semantics
    assert summary["run_identity_sha256"] == identity_sha256
    assert "source_wheel_attestation_sha256" not in summary

    source_summary = run_oracle._summary(
        [{"valid": True, "reason": "valid"}],
        1,
        semantics,
        identity_sha256,
        "a" * 64,
    )
    assert source_summary["source_wheel_attestation_sha256"] == "a" * 64


def test_oracle_run_identity_binds_all_canonical_inputs(tmp_path: Path) -> None:
    args = _identity_args(tmp_path)
    tasks = _tasks()
    identity = run_oracle._run_identity(args, tasks, None)

    assert identity["dataset"] == {
        "path": str(args.dataset_dir.resolve()),
        "revision": args.dataset_revision,
        "archive": {"path": None, "sha256": None},
        "content_sha256": None,
    }
    assert identity["selection"] == {
        "count": 2,
        "ordered_task_slugs_sha256": hashlib.sha256(b"alpha\nbeta\n").hexdigest(),
        "offset": 0,
        "limit": None,
        "task_file": {
            "path": str(args.task_file.resolve()),
            "sha256": args.task_file_sha256,
        },
    }
    assert identity["images"]["manifest"]["sha256"] == args.image_manifest_sha256
    assert identity["source"]["prime_rl_tree_sha256"] == run_oracle.CLEAN_TREE_SHA256
    assert identity["network_semantics"]["trusted_reference_solution"] == "public"
    assert identity["execution"]["max_concurrent"] == 32
    assert identity["acceptance"] == {"minimum_pass_rate": 0.9, "minimum_valid": 2}

    digest, created = run_oracle._bind_run_identity(tmp_path, identity)
    saved = json.loads((tmp_path / "run_identity.json").read_text())
    assert created is True
    assert saved["identity"] == identity
    assert digest == hashlib.sha256(run_oracle._canonical_json(identity)).hexdigest()
    assert saved["run_identity_sha256"] == digest
    assert run_oracle._bind_run_identity(tmp_path, identity) == (digest, False)


def test_oracle_run_identity_binds_source_wheel_policy_but_not_resume_approval(tmp_path: Path) -> None:
    args = _identity_args(tmp_path)
    policy = tmp_path / "source-wheel-policy.json"
    policy.write_text('{"schema_version":1}\n')
    args.source_wheel_policy = policy
    args.source_wheel_policy_sha256 = hashlib.sha256(policy.read_bytes()).hexdigest()
    args.source_wheel_attestation_sha256 = "e" * 64

    identity = run_oracle._run_identity(args, _tasks(), None)

    assert identity["source_wheel_recovery"] == {
        "schema_version": run_oracle.SOURCE_WHEEL_RECOVERY_SCHEMA_VERSION,
        "policy": {
            "path": str(policy.resolve()),
            "sha256": args.source_wheel_policy_sha256,
        },
        "attestation": "source_wheel_attestations.json",
        "artifact_download_network": "public-hash-pinned-https",
        "builder_lease_limit": 1,
        "build_dependency_install": "no-system-site-venv-offline-exact-wheel-closure",
        "build_dependency_resolution": "public-binary-only-exact-transitive-policy-closure",
        "build_network": "no-network",
        "build_isolation": True,
        "child_process_path": "venv-bin-only",
        "deterministic_environment_sha256": run_oracle.sha256_bytes(
            run_oracle.canonical_json(run_oracle.source_build_environment_variables())
        ),
        "source_build_python": "venv-python-isolated-no-site-direct-static-setuptools",
        "source_declarations": "static-setup-py-setup-cfg-pyproject-build-requirements",
        "source_build_umask": f"{run_oracle.SOURCE_BUILD_UMASK:04o}",
        "system_site_packages": False,
        "target_install": "offline-no-index-no-deps",
    }
    assert args.source_wheel_attestation_sha256 not in json.dumps(identity)


def test_oracle_run_identity_rejects_legacy_results(tmp_path: Path) -> None:
    status_dir = tmp_path / "tasks"
    status_dir.mkdir()
    (status_dir / "alpha.json").write_text("{}\n")

    with pytest.raises(SystemExit, match="no immutable run identity"):
        run_oracle._bind_run_identity(tmp_path, {"schema_version": 1})


def test_initial_source_wheel_ledger_crash_window_is_narrowly_recoverable(tmp_path: Path) -> None:
    identity = run_oracle._run_identity(_identity_args(tmp_path), _tasks(), None)
    output = tmp_path / "output"
    output.mkdir()
    run_oracle._bind_run_identity(output, identity)
    (output / ".writer.lock").touch()

    assert run_oracle._can_recover_initial_source_wheel_ledger(output) is True

    (output / "run_config.json").write_text("{}\n")
    assert run_oracle._can_recover_initial_source_wheel_ledger(output) is False


def test_oracle_resume_rejects_mismatched_identity_or_unbound_row(tmp_path: Path) -> None:
    identity = run_oracle._run_identity(_identity_args(tmp_path), _tasks(), None)
    digest, _ = run_oracle._bind_run_identity(tmp_path, identity)

    changed = json.loads(json.dumps(identity))
    changed["execution"]["vacli_max_concurrent_leases"] += 1
    with pytest.raises(SystemExit, match="run identity mismatch"):
        run_oracle._bind_run_identity(tmp_path, changed)

    status_dir = tmp_path / "tasks"
    status_dir.mkdir()
    (status_dir / "alpha.json").write_text(
        json.dumps({"index": 0, "name": "alpha", "slug": "alpha", "image": _tasks()[0].image}) + "\n"
    )
    with pytest.raises(SystemExit, match="missing oracle run identity"):
        run_oracle._validate_existing_artifacts(
            tmp_path,
            _tasks(),
            digest,
            identity["network_semantics"],
        )


def test_oracle_resume_rejects_invalid_terminal_status(tmp_path: Path) -> None:
    tasks = _tasks()
    identity = run_oracle._run_identity(_identity_args(tmp_path), tasks, None)
    digest, _ = run_oracle._bind_run_identity(tmp_path, identity)
    status_dir = tmp_path / "tasks"
    status_dir.mkdir()
    (status_dir / "alpha.json").write_text(
        json.dumps(
            {
                "index": 0,
                "name": "alpha",
                "slug": "alpha",
                "image": tasks[0].image,
                "valid": "yes",
                "reason": "valid",
                "run_identity_sha256": digest,
            }
        )
        + "\n"
    )

    with pytest.raises(SystemExit, match="invalid terminal status"):
        run_oracle._validate_existing_artifacts(
            tmp_path,
            tasks,
            digest,
            identity["network_semantics"],
        )


def test_oracle_resume_requires_rows_to_reference_validated_source_wheel_attestations(tmp_path: Path) -> None:
    tasks = _tasks()
    identity = run_oracle._run_identity(_identity_args(tmp_path), tasks, None)
    digest, _ = run_oracle._bind_run_identity(tmp_path, identity)
    status_dir = tmp_path / "tasks"
    status_dir.mkdir()
    status = {
        "index": 0,
        "name": "alpha",
        "slug": "alpha",
        "image": tasks[0].image,
        "valid": True,
        "reason": "valid",
        "error": None,
        "error_type": None,
        "elapsed_sec": 1.0,
        "attempts": 1,
        "infrastructure_failures": [],
        "oracle_network_semantics": identity["network_semantics"],
        "run_identity_sha256": digest,
        "source_wheel_attestation_sha256s": ["a" * 64],
    }
    (status_dir / "alpha.json").write_text(json.dumps(status) + "\n")
    stale_summary = run_oracle._summary(
        [status],
        len(tasks),
        identity["network_semantics"],
        digest,
        "d" * 64,
    )
    (tmp_path / "summary.json").write_text(json.dumps(stale_summary) + "\n")

    assert run_oracle._validate_existing_artifacts(
        tmp_path,
        tasks,
        digest,
        identity["network_semantics"],
        source_wheel_policy_enabled=True,
        source_wheel_attestation_sha256="c" * 64,
        known_source_wheel_attestation_sha256s=frozenset({"a" * 64}),
    ) == {"alpha": status}

    status["source_wheel_attestation_sha256s"] = ["b" * 64]
    (status_dir / "alpha.json").write_text(json.dumps(status) + "\n")
    with pytest.raises(SystemExit, match="invalid terminal status"):
        run_oracle._validate_existing_artifacts(
            tmp_path,
            tasks,
            digest,
            identity["network_semantics"],
            source_wheel_policy_enabled=True,
            source_wheel_attestation_sha256="c" * 64,
            known_source_wheel_attestation_sha256s=frozenset({"a" * 64}),
        )


def test_oracle_matching_resume_preserves_provenance_and_reuses_status(tmp_path: Path) -> None:
    args = _identity_args(tmp_path)
    tasks = _tasks()
    identity = run_oracle._run_identity(args, tasks, None)
    digest, created = run_oracle._bind_run_identity(tmp_path, identity)
    run_oracle._bind_initial_provenance(
        tmp_path,
        identity,
        digest,
        identity_created=created,
        invocation_host=args.invocation_host,
        slurm_job_id=args.slurm_job_id,
    )
    initial_provenance = (tmp_path / "provenance.txt").read_bytes()
    run_oracle._bind_initial_provenance(
        tmp_path,
        identity,
        digest,
        identity_created=False,
        invocation_host="different-worker.example",
        slurm_job_id="67890",
    )
    assert (tmp_path / "provenance.txt").read_bytes() == initial_provenance

    status_dir = tmp_path / "tasks"
    status_dir.mkdir()
    status = {
        "index": 0,
        "name": "alpha",
        "slug": "alpha",
        "image": tasks[0].image,
        "valid": True,
        "reason": "valid",
        "elapsed_sec": 1.0,
        "attempts": 1,
        "infrastructure_failures": [],
        "oracle_network_semantics": identity["network_semantics"],
        "run_identity_sha256": digest,
    }
    (status_dir / "alpha.json").write_text(json.dumps(status) + "\n")
    summary = run_oracle._summary([status], len(tasks), identity["network_semantics"], digest)
    (tmp_path / "summary.json").write_text(json.dumps(summary) + "\n")
    (tmp_path / "results.jsonl").write_text(json.dumps(status) + "\n")

    assert run_oracle._validate_existing_artifacts(
        tmp_path,
        tasks,
        digest,
        identity["network_semantics"],
    ) == {"alpha": status}


def test_oracle_archive_authority_matches_and_revalidates_live_tree(tmp_path: Path) -> None:
    args = _identity_args(tmp_path)
    args.dataset_revision = None
    args.use_declared_images = True
    args.dataset_dir.mkdir()
    task_dir = args.dataset_dir / "alpha"
    task_dir.mkdir()
    payload = task_dir / "instruction.md"
    payload.write_text("solve this\n")
    archive_path = tmp_path / "dataset.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(args.dataset_dir, arcname="tasks")
    args.dataset_archive = archive_path
    args.dataset_archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    content_sha256 = run_oracle._validated_dataset_content_sha256(args)
    assert content_sha256 is not None
    identity = run_oracle._run_identity(args, _tasks(), content_sha256)
    assert identity["dataset"] == {
        "path": str(args.dataset_dir.resolve()),
        "revision": None,
        "archive": {
            "path": str(archive_path.resolve()),
            "sha256": args.dataset_archive_sha256,
        },
        "content_sha256": content_sha256,
    }

    payload.write_text("mutated\n")
    with pytest.raises(SystemExit, match="does not match the pinned archive"):
        run_oracle._validated_dataset_content_sha256(args)


def test_oracle_dataset_authority_is_mutually_exclusive(tmp_path: Path) -> None:
    args = _identity_args(tmp_path)
    args.dataset_archive = tmp_path / "dataset.tar.gz"
    args.dataset_archive_sha256 = "e" * 64

    with pytest.raises(SystemExit, match="exactly one dataset revision or archive"):
        run_oracle._validate_identity_inputs(args)


def test_oracle_acceptance_requires_rate_and_minimum_valid_count() -> None:
    summary = {"passed": 2499, "pass_rate": 0.99}
    assert run_oracle._meets_acceptance(summary, 0.9, 2500) is False

    summary["passed"] = 2500
    assert run_oracle._meets_acceptance(summary, 0.9, 2500) is True
    assert run_oracle._meets_acceptance(summary, 1.0, 2500) is False


def test_oracle_attempt_cleans_taskset_before_runtime_stop_on_cancellation(monkeypatch) -> None:
    events: list[str] = []
    setup_started = asyncio.Event()

    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            events.append("runtime-start")

        async def stop(self) -> None:
            events.append("runtime-stop")

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            events.append("taskset-setup")
            setup_started.set()
            await asyncio.Event().wait()

        async def validate(self, task, runtime) -> bool:
            raise AssertionError("cancelled setup must not reach validation")

        async def cleanup(self, task, trace, runtime) -> None:
            assert trace is None
            events.append("taskset-cleanup")

    runtime = Runtime()
    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: runtime)

    async def exercise() -> None:
        attempt = asyncio.create_task(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            )
        )
        await setup_started.wait()
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt

    asyncio.run(exercise())

    assert events[-2:] == ["taskset-cleanup", "runtime-stop"]


def test_oracle_attempt_drains_teardown_after_repeated_cancellation(monkeypatch) -> None:
    events: list[str] = []
    setup_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            events.append("runtime-start")

        async def stop(self) -> None:
            events.append("runtime-stop")

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            events.append("taskset-setup")
            setup_started.set()
            await asyncio.Event().wait()

        async def validate(self, task, runtime) -> bool:
            raise AssertionError("cancelled setup must not reach validation")

        async def cleanup(self, task, trace, runtime) -> None:
            assert trace is None
            events.append("taskset-cleanup-start")
            cleanup_started.set()
            await release_cleanup.wait()
            events.append("taskset-cleanup-done")

    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: Runtime())

    async def exercise() -> None:
        attempt = asyncio.create_task(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            )
        )
        await setup_started.wait()
        attempt.cancel()
        await cleanup_started.wait()
        attempt.cancel()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await attempt

    asyncio.run(exercise())

    assert events[-2:] == ["taskset-cleanup-done", "runtime-stop"]


def test_oracle_teardown_preserves_cancellation_when_operation_finishes_same_turn() -> None:
    async def exercise() -> None:
        current = asyncio.current_task()
        assert current is not None
        asyncio.get_running_loop().call_soon(current.cancel)
        operation_errors, interruptions = await run_oracle._drain_teardown(asyncio.sleep(0))
        assert operation_errors == []
        assert len(interruptions) == 1
        assert isinstance(interruptions[0], asyncio.CancelledError)

    asyncio.run(exercise())


def test_oracle_teardown_failure_chains_same_turn_cancellation(monkeypatch) -> None:
    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            return None

        async def validate(self, task, runtime) -> bool:
            return True

        async def cleanup(self, task, trace, runtime) -> None:
            current = asyncio.current_task()
            assert current is not None
            caller = next(
                candidate
                for candidate in asyncio.all_tasks()
                if candidate is not current and candidate.get_name() == "oracle-attempt"
            )
            asyncio.get_running_loop().call_soon(caller.cancel)
            raise RuntimeError("cleanup boom")

    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: Runtime())

    async def exercise() -> None:
        attempt = asyncio.create_task(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            ),
            name="oracle-attempt",
        )
        with pytest.raises(run_oracle.SandboxError) as error:
            await attempt
        assert isinstance(error.value.__cause__, asyncio.CancelledError)
        assert "taskset cleanup RuntimeError: cleanup boom" in str(error.value)

    asyncio.run(exercise())


def test_oracle_attempt_rejects_success_after_both_teardown_failures(monkeypatch) -> None:
    events: list[str] = []

    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            events.append("runtime-start")

        async def stop(self) -> None:
            events.append("runtime-stop")
            raise RuntimeError("stop boom")

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            events.append("taskset-setup")

        async def validate(self, task, runtime) -> bool:
            events.append("validate")
            return True

        async def cleanup(self, task, trace, runtime) -> None:
            assert trace is None
            events.append("taskset-cleanup")
            raise RuntimeError("cleanup boom")

    runtime = Runtime()
    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: runtime)

    with pytest.raises(run_oracle.SandboxError) as error:
        asyncio.run(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            )
        )

    assert "taskset cleanup RuntimeError: cleanup boom" in str(error.value)
    assert "runtime stop RuntimeError: stop boom" in str(error.value)
    assert events[-2:] == ["taskset-cleanup", "runtime-stop"]


@pytest.mark.parametrize(
    "primary_factory",
    [
        pytest.param(lambda: run_oracle.SandboxError("primary sandbox"), id="sandbox"),
        pytest.param(lambda: run_oracle.OracleFailure("primary oracle"), id="oracle"),
        pytest.param(lambda: asyncio.TimeoutError("primary timeout"), id="timeout"),
        pytest.param(lambda: RuntimeError("primary runtime"), id="generic"),
        pytest.param(lambda: BaseException("primary base"), id="base-exception"),
        pytest.param(lambda: asyncio.CancelledError("primary cancellation"), id="cancellation"),
    ],
)
@pytest.mark.parametrize("failing_teardown", ["taskset", "runtime"])
def test_oracle_teardown_failure_overrides_and_chains_every_primary_error(
    monkeypatch, primary_factory, failing_teardown: str
) -> None:
    events: list[str] = []
    primary = primary_factory()

    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            events.append("runtime-start")

        async def stop(self) -> None:
            events.append("runtime-stop")
            if failing_teardown == "runtime":
                raise RuntimeError("stop boom")

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            events.append("taskset-setup")

        async def validate(self, task, runtime) -> bool:
            events.append("validate")
            raise primary

        async def cleanup(self, task, trace, runtime) -> None:
            assert trace is None
            events.append("taskset-cleanup")
            if failing_teardown == "taskset":
                raise RuntimeError("cleanup boom")

    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: Runtime())

    with pytest.raises(run_oracle.SandboxError) as error:
        asyncio.run(
            run_oracle._attempt(
                Taskset(),
                SimpleNamespace(idx=0, name="test"),
                SimpleNamespace(),
                setup_timeout=30,
                validate_timeout=30,
                attempt=1,
            )
        )

    assert error.value.__cause__ is primary
    expected_label = "taskset cleanup" if failing_teardown == "taskset" else "runtime stop"
    assert expected_label in str(error.value)
    assert events[-2:] == ["taskset-cleanup", "runtime-stop"]


def test_oracle_cleanup_failure_is_classified_as_infrastructure_error(monkeypatch) -> None:
    class Runtime:
        descriptor = "runtime"

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class Taskset:
        async def setup_oracle(self, task, runtime) -> None:
            return None

        async def validate(self, task, runtime) -> bool:
            return True

        async def cleanup(self, task, trace, runtime) -> None:
            raise RuntimeError("cleanup boom")

    monkeypatch.setattr(run_oracle, "resolve_runtime_config", lambda config, task: config)
    monkeypatch.setattr(run_oracle, "make_runtime", lambda config, name: Runtime())
    task = SimpleNamespace(idx=0, name="test", slug="test", image="image")
    args = SimpleNamespace(infra_retries=0, setup_timeout=30, validate_timeout=30)

    result = asyncio.run(run_oracle._validate_one(Taskset(), task, SimpleNamespace(), args))

    assert result["valid"] is False
    assert result["reason"] == "infrastructure_error"
    assert result["error_type"] == "SandboxError"
    assert "taskset cleanup RuntimeError: cleanup boom" in result["error"]
    assert result["infrastructure_failures"] == [
        {
            "attempt": 1,
            "error_type": "SandboxError",
            "error": result["error"],
        }
    ]


def test_oracle_main_translates_sigterm_to_graceful_interrupt(monkeypatch) -> None:
    installed: dict[int, object] = {}

    def install_signal(number: int, handler: object) -> None:
        installed[number] = handler

    def run(coroutine) -> int:
        coroutine.close()
        return 0

    monkeypatch.setattr(run_oracle, "_parse_args", lambda: SimpleNamespace(log_level="INFO"))
    monkeypatch.setattr(run_oracle.signal, "signal", install_signal)
    monkeypatch.setattr(run_oracle.asyncio, "run", run)

    with pytest.raises(SystemExit) as exit_info:
        run_oracle.main()

    assert exit_info.value.code == 0
    assert signal.SIGTERM in installed
