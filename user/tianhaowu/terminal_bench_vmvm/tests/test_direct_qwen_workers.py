from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import direct_qwen_workers as direct
import pytest


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
                line.split('"')[1]
                for line in config.read_text().splitlines()
                if line.startswith("task_file_sha256 = ")
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
    assert len(urls.read_text().splitlines()) == 2
    serialized = manifest_path.read_text().casefold()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert oct(manifest_path.stat().st_mode & 0o777) == "0o600"


def test_validate_saved_manifest_rejects_router_retry(tmp_path: Path, monkeypatch) -> None:
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
    manifest["router"]["retries"] = 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(direct.DirectWorkerError, match="router_invalid"):
        direct.validate_saved_manifest(path)


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
    manifest = direct._manifest(tmp_path, workers, spec_sha256, bundle_sha256, task_hash, 20_001, 40_001)
    (run_dir / "direct_workers.json").write_text(json.dumps(manifest) + "\n")

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
    )

    summary = direct.audit_run_directory(run_dir)

    assert summary["ok"] is True
    assert summary["endpoints"] == 2


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
    manifest = direct._manifest(tmp_path, workers, spec_sha256, bundle_sha256, task_hash, 20_001, 40_001)
    (run_dir / "direct_workers.json").write_text(json.dumps(manifest) + "\n")
    (run_dir / "config.toml").write_text(_approved_config(tmp_path).read_text().replace("127.0.0.1:8000", "127.0.0.1:20001"))
    (run_dir / "provenance.txt").write_text("api_key=forbidden\n")

    with pytest.raises(direct.DirectWorkerError, match="contains_credential"):
        direct.audit_run_directory(run_dir)
