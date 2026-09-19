from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import direct_qwen_workers as direct
import pytest


def test_production_worker_generation_is_exactly_the_certified_24_routes() -> None:
    assert direct.EXPECTED_ENDPOINTS == 24
    assert direct.EXPECTED_SPEC_SHA256 == ("e5ddc652b1e3dbb99ed65b44b276cf9d9b8ae866b5a4471db42cf0c732a64007")
    assert direct.EXPECTED_ENDPOINT_BUNDLE_SHA256 == (
        "db0095649feda5d1c8ea66a434c6486a6c91d6b4519664701a26dab44c7a83a0"
    )


def _write_deployment(tmp_path: Path, count: int = 2) -> tuple[Path, str, str, list[direct.Worker]]:
    root = tmp_path / "deployment"
    endpoints = root / "endpoints"
    endpoints.mkdir(parents=True)
    spec = root / "spec.yaml"
    spec.write_text("model: qwen\n", encoding="utf-8")
    for index in range(count):
        (endpoints / f"{100 + index}.json").write_text(
            json.dumps(
                {
                    "host": f"worker-{index}",
                    "port": 20_000 + index,
                    "started_at": "2026-09-16T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
    paths = sorted(endpoints.iterdir())
    spec_sha256 = hashlib.sha256(spec.read_bytes()).hexdigest()
    bundle_sha256 = direct.endpoint_bundle_sha256(paths)
    workers, _, _ = direct.load_workers(
        root,
        expected_spec_sha256=spec_sha256,
        expected_bundle_sha256=bundle_sha256,
        expected_count=count,
    )
    return root, spec_sha256, bundle_sha256, workers


def _approved_config(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "configs" / "eval" / "tb4_qwen_token_smoke.toml"
    task_file = tmp_path / "approved_tasks.txt"
    task_file.write_text("approved-fixture-a\napproved-fixture-b\n")
    task_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()
    source_config = tomllib.loads(source.read_text())
    source_task_file = source_config["taskset"]["task_file"]
    source_task_hash = source_config["taskset"]["task_file_sha256"]
    text = source.read_text()
    text = text.replace(
        f'task_file = "{source_task_file}"',
        f'task_file = "{task_file}"',
    ).replace(
        f'task_file_sha256 = "{source_task_hash}"',
        f'task_file_sha256 = "{task_hash}"',
    )
    config = tmp_path / "approved.toml"
    config.write_text(text)
    return config


def test_load_workers_validates_exact_metadata_and_hashes(tmp_path: Path) -> None:
    root, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)

    assert len(workers) == 2
    assert workers[0].metadata_file == "100.json"
    assert workers[0].url == "http://worker-0:20000"
    assert spec_sha256 == hashlib.sha256((root / "spec.yaml").read_bytes()).hexdigest()
    assert bundle_sha256 == direct.endpoint_bundle_sha256(sorted((root / "endpoints").iterdir()))


def test_post_eval_generation_rejects_dead_reduced_or_drifted_service(tmp_path: Path, monkeypatch) -> None:
    root, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(direct._manifest(root, workers, spec_sha256, bundle_sha256, "a" * 64, 20001, 40001, 2)) + "\n"
    )

    with pytest.raises(direct.DirectWorkerError, match="not_live"):
        direct.validate_post_eval_generation(manifest_path, root, router_alive=False, active_workers=2)
    with pytest.raises(direct.DirectWorkerError, match="worker_count_drift"):
        direct.validate_post_eval_generation(manifest_path, root, router_alive=True, active_workers=1)

    (root / "spec.yaml").write_text("model: drifted\n")
    with pytest.raises(direct.DirectWorkerError, match="serving_generation_drift"):
        direct.validate_post_eval_generation(manifest_path, root, router_alive=True, active_workers=2)


def test_load_workers_rejects_metadata_change(tmp_path: Path) -> None:
    root, spec_sha256, bundle_sha256, _ = _write_deployment(tmp_path)
    endpoint = root / "endpoints" / "100.json"
    value = json.loads(endpoint.read_text())
    value["port"] += 1
    endpoint.write_text(json.dumps(value) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="endpoint_bundle_sha256_mismatch"):
        direct.load_workers(
            root,
            expected_spec_sha256=spec_sha256,
            expected_bundle_sha256=bundle_sha256,
            expected_count=2,
        )


@pytest.mark.parametrize(
    "filename",
    [
        "tb4_qwen_token_smoke.toml",
        "tb4_qwen_a95b_miniswe.toml",
        "mobius_qwen_a95b_2500.toml",
    ],
)
def test_approved_qwen_configs_can_use_direct_fallback(filename: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = Path(__file__).parents[1] / "configs" / "eval"
    repository_root = config_dir.parents[4]
    config_path = config_dir / filename
    config = tomllib.loads(config_path.read_text())
    task_file = repository_root / config["taskset"]["task_file"]
    task_hash = config["taskset"]["task_file_sha256"]
    monkeypatch.chdir(repository_root)

    assert (
        direct.validate_eval_config(
            config_path,
            approved_task_file=task_file,
            approved_task_file_sha256=task_hash,
        )
        == task_hash
    )


def test_full_sandoq_config_fails_closed_on_aggregate_compose_count(monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = Path(__file__).parents[1] / "configs" / "eval"
    repository_root = config_dir.parents[4]
    config_path = config_dir / "mobius_qwen_a95b_2500_sandoq.toml"
    config = tomllib.loads(config_path.read_text())
    task_file = repository_root / config["taskset"]["task_file"]
    monkeypatch.chdir(repository_root)

    with pytest.raises(direct.DirectWorkerError, match=r"eval_sandoq_compose_tasks_unsupported:1$"):
        direct.validate_eval_config(
            config_path,
            approved_task_file=task_file,
            approved_task_file_sha256=config["taskset"]["task_file_sha256"],
        )


def test_sandoq_ramp_prefixes_have_no_compose_tasks(tmp_path: Path) -> None:
    config_dir = Path(__file__).parents[1] / "configs" / "eval"
    repository_root = config_dir.parents[4]
    config = tomllib.loads((config_dir / "mobius_qwen_a95b_2500_sandoq.toml").read_text())
    source = repository_root / config["taskset"]["task_file"]
    dataset_dir = Path(config["taskset"]["dataset_dir"])
    lines = source.read_bytes().splitlines(keepends=True)

    for count in (2, 8, 24):
        selected = tmp_path / f"prefix-{count}.txt"
        selected.write_bytes(b"".join(lines[:count]))
        assert direct.sandoq_compose_task_count(dataset_dir, selected) == 0


def test_empty_inline_task_selection_is_still_forbidden(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace("[taskset]\n", "[taskset]\ntasks = []\n"))

    with pytest.raises(direct.DirectWorkerError, match="inline_tasks_forbidden"):
        direct.validate_eval_config(config)


def test_approved_qwen_config_preserves_direct_fallback_contract(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    task_file = tmp_path / "approved_tasks.txt"
    task_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()

    assert (
        direct.validate_eval_config(
            config,
            approved_task_file=task_file,
            approved_task_file_sha256=task_hash,
        )
        == task_hash
    )


def test_approved_qwen_config_requires_interception_retry(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace(', "InterceptionError"', ""))

    with pytest.raises(direct.DirectWorkerError, match="eval_rollout_retry_policy_mismatch"):
        direct.validate_eval_config(config)


def test_approved_qwen_config_rejects_harness_error_retry(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace('"InterceptionError"', '"InterceptionError", "HarnessError"'))

    with pytest.raises(direct.DirectWorkerError, match="eval_rollout_retry_policy_mismatch"):
        direct.validate_eval_config(config)


def test_historical_qwen_retry_policy_requires_explicit_validation_mode(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace(', "InterceptionError"', ""))

    with pytest.raises(direct.DirectWorkerError, match="eval_rollout_retry_policy_mismatch"):
        direct.validate_eval_config(config)

    assert direct.validate_eval_config(config, allow_historical_retry_policy=True)


def test_qwen_retry_policy_rejects_duplicate_entries(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace('"InterceptionError"', '"InterceptionError", "InterceptionError"'))

    with pytest.raises(direct.DirectWorkerError, match="eval_rollout_retry_policy_mismatch"):
        direct.validate_eval_config(config, allow_historical_retry_policy=True)


def test_qwen_retry_policy_rejects_exclusions(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text() + '\nexclude = ["InterceptionError"]\n')

    with pytest.raises(direct.DirectWorkerError, match="eval_rollout_retry_policy_mismatch"):
        direct.validate_eval_config(config)


@pytest.mark.parametrize("field", ["max_connections", "max_keepalive_connections"])
def test_approved_qwen_config_requires_exact_worker_bounded_http_pool(tmp_path: Path, field: str) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace(f"{field} = 2", f"{field} = 3"))

    with pytest.raises(direct.DirectWorkerError, match=f"eval_client_{field}_invalid"):
        direct.validate_eval_config(config)


def test_production_qwen_config_queues_64_rollouts_behind_32_http_connections() -> None:
    config_path = Path(__file__).parents[1] / "configs" / "eval" / "mobius_qwen_a95b_2500.toml"
    config = tomllib.loads(config_path.read_text())

    assert config["max_concurrent"] == 64
    assert config["multiplex"] == 64
    assert config["client"]["max_connections"] == direct.PRODUCTION_PROVIDER_CONCURRENCY == 32
    assert config["client"]["max_keepalive_connections"] == direct.PRODUCTION_PROVIDER_CONCURRENCY
    assert [
        value for value in config["harness"]["config_overrides"] if value.startswith("model.model_kwargs.timeout=")
    ] == [f"model.model_kwargs.timeout={direct.PRODUCTION_MODEL_TIMEOUT_SECONDS}"]


def test_qwen_config_rejects_boolean_num_rollouts(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    config.write_text(config.read_text().replace("num_rollouts = 1", "num_rollouts = true"))

    with pytest.raises(direct.DirectWorkerError, match="eval_num_rollouts_mismatch"):
        direct.validate_eval_config(config)


def test_production_qwen_config_requires_end_to_end_model_timeout(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    text = config.read_text()
    text = text.replace("max_concurrent = 2", "max_concurrent = 64")
    text = text.replace("multiplex = 2", "multiplex = 64")
    text = text.replace("max_connections = 2", "max_connections = 32")
    text = text.replace("max_keepalive_connections = 2", "max_keepalive_connections = 32")
    config.write_text(text)

    with pytest.raises(direct.DirectWorkerError, match="eval_model_timeout_mismatch"):
        direct.validate_eval_config(config)

    config.write_text(
        config.read_text().replace(
            '    "model.model_kwargs.parallel_tool_calls=true",',
            '    "model.model_kwargs.parallel_tool_calls=true",\n'
            f'    "model.model_kwargs.timeout={direct.PRODUCTION_MODEL_TIMEOUT_SECONDS}",',
        )
    )
    assert direct.validate_eval_config(config)


def test_approved_qwen_config_rejects_independent_approval_mismatch(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    different_allowlist = tmp_path / "external_approval.txt"
    different_allowlist.write_text("different-approved-fixture\n")
    different_hash = hashlib.sha256(different_allowlist.read_bytes()).hexdigest()

    with pytest.raises(direct.DirectWorkerError, match="not_externally_approved"):
        direct.validate_eval_config(
            config,
            approved_task_file=different_allowlist,
            approved_task_file_sha256=different_hash,
        )


def test_approved_qwen_config_rejects_wrong_allowlist_count(tmp_path: Path) -> None:
    config = _approved_config(tmp_path)
    task_file = tmp_path / "approved_tasks.txt"
    task_file.write_text("approved-fixture\n")
    task_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()
    config.write_text(
        config.read_text().replace(
            next(
                line.split('"')[1] for line in config.read_text().splitlines() if line.startswith("task_file_sha256 = ")
            ),
            task_hash,
        )
    )

    with pytest.raises(direct.DirectWorkerError, match="task_file_count_mismatch"):
        direct.validate_eval_config(
            config,
            approved_task_file=task_file,
            approved_task_file_sha256=task_hash,
        )


def test_prepare_snapshots_only_non_secret_worker_metadata(tmp_path: Path, monkeypatch) -> None:
    _, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "load_workers",
        lambda _root: (workers, spec_sha256, bundle_sha256),
    )
    monkeypatch.setattr(direct, "probe_workers", lambda *_args, **_kwargs: None)
    config = _approved_config(tmp_path)
    run_dir = tmp_path / "run"
    manifest_path = run_dir / "direct_workers.json"
    urls = tmp_path / "urls.txt"
    ports = tmp_path / "ports.txt"

    manifest = direct.prepare(
        tmp_path,
        config,
        manifest_path,
        urls,
        ports,
        tmp_path / "approved_tasks.txt",
        hashlib.sha256((tmp_path / "approved_tasks.txt").read_bytes()).hexdigest(),
        resume=False,
        probe_timeout=1,
    )

    assert manifest["spec_sha256"] == spec_sha256
    assert manifest["endpoint_bundle_sha256"] == bundle_sha256
    assert manifest["schema_version"] == direct.ROUTER_MANIFEST_SCHEMA_VERSION
    assert manifest["router"]["policy"] == direct.ROUTER_POLICY
    assert manifest["router"]["request_id_headers"] == list(direct.ROUTER_REQUEST_ID_HEADERS)
    assert len(urls.read_text().splitlines()) == 2
    assert ports.read_text().splitlines() == [
        str(manifest["router"]["port"]),
        str(manifest["router"]["metrics_port"]),
        "2",
        "0",
        "7200",
        "consistent_hash",
        "x-session-id",
    ]
    serialized = manifest_path.read_text().casefold()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert oct(manifest_path.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("retry_value", [1, False])
def test_validate_saved_manifest_rejects_router_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retry_value: object,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    manifest["router"]["retries"] = retry_value
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="router_invalid"):
        direct.validate_saved_manifest(path)


@pytest.mark.parametrize(
    "field",
    [
        "rollout_concurrency",
        "client_max_connections",
        "client_max_keepalive_connections",
        "router_max_concurrent_requests",
        "router_queue_size",
    ],
)
def test_validate_saved_manifest_rejects_admission_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
        2,
        2,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    manifest["admission"][field] += 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="manifest_admission_invalid"):
        direct.validate_saved_manifest(path)


def test_validate_saved_manifest_rejects_schema3_production_cap16(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
        direct.MAX_DIRECT_CONCURRENCY,
        direct.LEGACY_PRODUCTION_PROVIDER_CONCURRENCY,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="manifest_production_admission_invalid"):
        direct.validate_saved_manifest(path)


def test_validate_saved_manifest_rejects_admission_above_rollout_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
        direct.MAX_DIRECT_CONCURRENCY,
        direct.MAX_DIRECT_CONCURRENCY,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    manifest["router"]["queue_size"] = 63
    manifest["admission"]["rollout_concurrency"] = 127
    manifest["admission"]["router_queue_size"] = 63
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="admission_exceeds_rollout_limit"):
        direct.validate_saved_manifest(path)


def test_validate_saved_manifest_rejects_boolean_admission_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
        2,
        2,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    manifest["admission"]["schema_version"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="manifest_admission_invalid"):
        direct.validate_saved_manifest(path)


def test_epoch2_lineage_rejects_boolean_routing_epoch(tmp_path: Path) -> None:
    path = tmp_path / "lineage.jsonl"
    path.write_text(json.dumps({"row_sha256": "a" * 64, "routing_epoch": True}) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="epoch2_lineage_invalid"):
        direct._read_epoch2_lineage(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("policy", "round_robin"),
        ("request_id_headers", []),
        ("request_id_headers", ["x-request-id"]),
        ("request_id_headers", ["x-session-id", "x-request-id"]),
    ],
)
def test_validate_saved_manifest_rejects_affinity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    _, _, _, workers = _write_deployment(tmp_path)
    manifest = direct._manifest(
        tmp_path,
        workers,
        direct.EXPECTED_SPEC_SHA256,
        direct.EXPECTED_ENDPOINT_BUNDLE_SHA256,
        "a" * 64,
        20_001,
        40_001,
    )
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "EXPECTED_ENDPOINT_BUNDLE_SHA256",
        direct.endpoint_bundle_sha256(
            [tmp_path / "deployment" / "endpoints" / worker.metadata_file for worker in workers]
        ),
    )
    manifest["endpoint_bundle_sha256"] = direct.EXPECTED_ENDPOINT_BUNDLE_SHA256
    manifest["router"][field] = value
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="router_invalid"):
        direct.validate_saved_manifest(path)


def test_resume_accepts_only_the_saved_affinity_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_root, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "load_workers",
        lambda _root: (workers, spec_sha256, bundle_sha256),
    )
    monkeypatch.setattr(direct, "probe_workers", lambda *_args, **_kwargs: None)
    config = _approved_config(tmp_path)
    approved_task_file = tmp_path / "approved_tasks.txt"
    approved_task_sha256 = hashlib.sha256(approved_task_file.read_bytes()).hexdigest()
    run_dir = tmp_path / "run"
    manifest_path = run_dir / "direct_workers.json"

    fresh = direct.prepare(
        deployment_root,
        config,
        manifest_path,
        tmp_path / "fresh-urls.txt",
        tmp_path / "fresh-runtime.txt",
        approved_task_file,
        approved_task_sha256,
        resume=False,
        probe_timeout=1,
    )
    config.write_text(
        config.read_text().replace(
            "http://127.0.0.1:8000/v1",
            f"http://127.0.0.1:{fresh['router']['port']}/v1",
        )
    )
    saved_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(saved_bytes).hexdigest()
    (run_dir / "provenance.txt").write_text(
        f"direct_qwen_manifest_sha256={manifest_sha256}\n"
        "direct_qwen_router_policy=consistent_hash\n"
        "direct_qwen_request_id_headers=x-session-id\n"
        "direct_qwen_provider_concurrency=2\n"
    )

    resumed = direct.prepare(
        deployment_root,
        config,
        manifest_path,
        tmp_path / "resume-urls.txt",
        tmp_path / "resume-runtime.txt",
        approved_task_file,
        approved_task_sha256,
        resume=True,
        probe_timeout=1,
    )

    assert resumed == fresh
    assert manifest_path.read_bytes() == saved_bytes
    assert resumed["router"]["policy"] == "consistent_hash"
    assert resumed["router"]["request_id_headers"] == ["x-session-id"]


def test_resume_rejects_legacy_round_robin_manifest_without_rewriting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment_root, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    monkeypatch.setattr(
        direct,
        "load_workers",
        lambda _root: (workers, spec_sha256, bundle_sha256),
    )
    monkeypatch.setattr(direct, "probe_workers", lambda *_args, **_kwargs: None)
    config = _approved_config(tmp_path)
    approved_task_file = tmp_path / "approved_tasks.txt"
    approved_task_sha256 = hashlib.sha256(approved_task_file.read_bytes()).hexdigest()
    manifest_path = tmp_path / "run" / "direct_workers.json"
    fresh = direct.prepare(
        deployment_root,
        config,
        manifest_path,
        tmp_path / "fresh-urls.txt",
        tmp_path / "fresh-runtime.txt",
        approved_task_file,
        approved_task_sha256,
        resume=False,
        probe_timeout=1,
    )
    config.write_text(
        config.read_text().replace(
            "http://127.0.0.1:8000/v1",
            f"http://127.0.0.1:{fresh['router']['port']}/v1",
        )
    )
    legacy = json.loads(manifest_path.read_text())
    legacy["schema_version"] = 1
    legacy["router"]["policy"] = "round_robin"
    legacy["router"].pop("request_id_headers")
    manifest_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")
    legacy_bytes = manifest_path.read_bytes()

    with pytest.raises(direct.DirectWorkerError, match="manifest_schema_mismatch"):
        direct.prepare(
            deployment_root,
            config,
            manifest_path,
            tmp_path / "resume-urls.txt",
            tmp_path / "resume-runtime.txt",
            approved_task_file,
            approved_task_sha256,
            resume=True,
            probe_timeout=1,
        )

    assert manifest_path.read_bytes() == legacy_bytes


def test_audit_run_directory_validates_provenance_without_results(tmp_path: Path, monkeypatch) -> None:
    _, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    task_file = tmp_path / "approved_tasks.txt"
    task_file.write_text("approved-fixture-a\napproved-fixture-b\n")
    task_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()
    manifest = direct._manifest(
        tmp_path,
        workers,
        spec_sha256,
        bundle_sha256,
        task_hash,
        20_001,
        40_001,
        2,
    )
    manifest_path = run_dir / "direct_workers.json"
    manifest_path.write_text(json.dumps(manifest) + "\n")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    source = _approved_config(tmp_path)
    source_config = inputs / "source_config.toml"
    source_config.write_bytes(source.read_bytes())
    task_file_snapshot = inputs / "task_file.txt"
    task_file_snapshot.write_bytes(task_file.read_bytes())
    saved_config = source.read_text().replace(
        'base_url = "http://127.0.0.1:8000/v1"',
        'base_url = "http://127.0.0.1:20001/v1"',
    )
    (run_dir / "config.toml").write_text(saved_config)
    (inputs / "manifest.json").write_text(
        json.dumps(
            {
                "config": {
                    "source": str(source),
                    "snapshot": str(source_config.resolve()),
                    "sha256": hashlib.sha256(source_config.read_bytes()).hexdigest(),
                },
                "task_file": {
                    "source": str(task_file),
                    "snapshot": str(task_file_snapshot.resolve()),
                    "sha256": task_hash,
                },
            }
        )
        + "\n"
    )
    (run_dir / "provenance.txt").write_text(
        "prime_rl=" + "1" * 40 + "\n"
        "verifiers=" + "2" * 40 + "\n"
        "renderers=" + "3" * 40 + "\n"
        "inference_base_url=http://127.0.0.1:20001/v1\n"
        "inference_deployment_id=\n"
        "slurm_job_id=123\n"
        f"direct_qwen_manifest_sha256={manifest_sha256}\n"
        "direct_qwen_router_policy=consistent_hash\n"
        "direct_qwen_request_id_headers=x-session-id\n"
        "direct_qwen_provider_concurrency=2\n"
    )

    summary = direct.audit_run_directory(run_dir)

    assert summary["ok"] is True
    assert summary["endpoints"] == 2
    assert summary["manifest_sha256"] == manifest_sha256
    assert summary["router_policy"] == "consistent_hash"
    assert summary["request_id_headers"] == ["x-session-id"]

    provenance_path = run_dir / "provenance.txt"
    fresh_provenance = provenance_path.read_text()
    provenance_path.write_text(
        fresh_provenance.replace(
            "direct_qwen_router_policy=consistent_hash",
            "direct_qwen_router_policy=round_robin",
        )
    )
    with pytest.raises(direct.DirectWorkerError, match="provenance_router_mismatch"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(fresh_provenance + "resume_slurm_job_id=124\n")
    with pytest.raises(
        direct.DirectWorkerError,
        match="resume_provenance_router_mismatch",
    ):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + f"resume_direct_qwen_manifest_sha256={manifest_sha256}\n"
        + "resume_direct_qwen_router_policy=consistent_hash\n"
        + "resume_direct_qwen_request_id_headers=x-session-id\n"
        + "resume_direct_qwen_provider_concurrency=2\n"
    )
    assert direct.audit_run_directory(run_dir)["ok"] is True

    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + f"resume_direct_qwen_manifest_sha256={manifest_sha256}\n"
        + "resume_direct_qwen_router_policy=consistent_hash\n"
        + "resume_direct_qwen_request_id_headers=x-session-id\n"
        + "resume_direct_qwen_provider_concurrency=16\n"
        + "resume_direct_qwen_provider_concurrency=2\n"
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_duplicate_key"):
        direct.audit_run_directory(run_dir)

    valid_resume_router = (
        f"resume_direct_qwen_manifest_sha256={manifest_sha256}\n"
        "resume_direct_qwen_router_policy=consistent_hash\n"
        "resume_direct_qwen_request_id_headers=x-session-id\n"
        "resume_direct_qwen_provider_concurrency=2\n"
    )
    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + valid_resume_router
        + "resume_slurm_job_id=125\n"
        + valid_resume_router
    )
    assert direct.audit_run_directory(run_dir)["ok"] is True

    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + valid_resume_router
        + "resume_slurm_job_id=124\n"
        + valid_resume_router
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_boundary_invalid"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + "resume_prime_rl="
        + "4" * 40
        + "\nresume_prime_rl="
        + "5" * 40
        + "\n"
        + valid_resume_router
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_duplicate_key"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(fresh_provenance + valid_resume_router)
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_boundary_invalid"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(
        fresh_provenance
        + "resume_slurm_job_id=124\n"
        + valid_resume_router
        + "ambiguous_boundary=value\n"
        + "resume_prime_rl="
        + "4" * 40
        + "\n"
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_boundary_invalid"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(fresh_provenance + "resume_slurm_job_id=0\n" + valid_resume_router)
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_boundary_invalid"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(
        fresh_provenance + "resume_slurm_job_id=124\n" + valid_resume_router + "resume_direct_qwen_unknown=value\n"
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_router_mismatch"):
        direct.audit_run_directory(run_dir)

    provenance_path.write_text(
        fresh_provenance
        + "qwen_router_admission_transition_sha256="
        + "a" * 64
        + "\nqwen_router_transition_sha256="
        + "b" * 64
        + "\n"
    )
    with pytest.raises(direct.DirectWorkerError, match="resume_provenance_boundary_invalid"):
        direct.audit_run_directory(run_dir)


def test_audit_run_directory_rejects_credential_provenance(tmp_path: Path, monkeypatch) -> None:
    _, spec_sha256, bundle_sha256, workers = _write_deployment(tmp_path)
    monkeypatch.setattr(direct, "EXPECTED_SPEC_SHA256", spec_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINT_BUNDLE_SHA256", bundle_sha256)
    monkeypatch.setattr(direct, "EXPECTED_ENDPOINTS", len(workers))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    task_file = tmp_path / "approved_tasks.txt"
    task_file.write_text("approved-fixture-a\napproved-fixture-b\n")
    task_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()
    manifest = direct._manifest(
        tmp_path,
        workers,
        spec_sha256,
        bundle_sha256,
        task_hash,
        20_001,
        40_001,
        2,
    )
    (run_dir / "direct_workers.json").write_text(json.dumps(manifest) + "\n")
    (run_dir / "config.toml").write_text(
        _approved_config(tmp_path).read_text().replace("127.0.0.1:8000", "127.0.0.1:20001")
    )
    (run_dir / "provenance.txt").write_text("api_key=forbidden\n")

    with pytest.raises(direct.DirectWorkerError, match="contains_credential"):
        direct.audit_run_directory(run_dir)
