from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "export_oracle_tasks.py"
SPEC = importlib.util.spec_from_file_location("terminal_bench_vmvm_export_oracle_tasks", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
export_oracle_tasks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_oracle_tasks)
PromotionError = export_oracle_tasks.PromotionError
VERIFIER_COMMIT = "a" * 40
VMVM_TB_V2_SHA256 = "b" * 64
IMAGE_MANIFEST_BYTES = b'{"images":{}}\n'
IMAGE_MANIFEST_SHA256 = hashlib.sha256(IMAGE_MANIFEST_BYTES).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dataset(tmp_path: Path, total: int = 10) -> tuple[Path, list[str], str]:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    tasks = [f"opaque-{index:03d}" for index in range(total)]
    for task in tasks:
        task_dir = dataset / task
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("")
        (task_dir / "instruction.md").write_text("")
    subprocess.run(["git", "init", "-q", str(dataset)], check=True)
    subprocess.run(["git", "-C", str(dataset), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(dataset),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(dataset), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dataset, tasks, revision


def _oracle(
    tmp_path: Path,
    dataset: Path,
    tasks: list[str],
    valid: set[str],
    prime_rl_commit: str,
    revision: str,
    image_manifest: Path,
    minimum_valid: int,
) -> Path:
    oracle = tmp_path / "oracle"
    statuses = oracle / "tasks"
    statuses.mkdir(parents=True)
    (oracle / ".writer.lock").touch()
    semantics = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }
    identity = {
        "schema_version": 1,
        "dataset": {
            "path": str(dataset.resolve()),
            "revision": revision,
            "archive": {"path": None, "sha256": None},
            "content_sha256": None,
        },
        "selection": {
            "count": len(tasks),
            "ordered_task_slugs_sha256": _sha256("".join(f"{task}\n" for task in tasks).encode()),
            "offset": 0,
            "limit": None,
            "task_file": {"path": None, "sha256": None},
        },
        "images": {
            "prefix": "vmvm-registry.invalid/terminal-bench",
            "tag": "mobius-pinned",
            "manifest": {
                "path": str(image_manifest.resolve()),
                "sha256": IMAGE_MANIFEST_SHA256,
            },
            "use_declared_images": False,
            "enable_compose": False,
        },
        "source": {
            "prime_rl_commit": prime_rl_commit,
            "prime_rl_tree_sha256": hashlib.sha256(b"").hexdigest(),
            "verifiers_commit": VERIFIER_COMMIT,
            "vmvm_tb_v2_sha256": VMVM_TB_V2_SHA256,
        },
        "network_semantics": semantics,
        "execution": {
            "max_concurrent": 8,
            "infra_retries": 2,
            "setup_timeout_sec": 3600.0,
            "validate_timeout_sec": 10800.0,
            "session_timeout_sec": 10800.0,
            "tenant_id": "test-tenant",
            "lease_ttl": "60s",
            "max_session_buffer_size": 67_108_864,
            "verifier_runtime_retries": 2,
            "vacli_lease_retries": 20,
            "vacli_max_concurrent_leases": 4,
            "vacli_max_pull_retries": 20,
            "vacli_image_pull_timeout_seconds": 3600,
            "vacli_container_privileged": True,
            "timeout_multiplier": 2.0,
            "resource_multiplier": 2.0,
            "runtime_image": "python:3.12-slim",
            "runtime_workdir": "/app",
        },
        "acceptance": {"minimum_pass_rate": 0.9, "minimum_valid": minimum_valid},
    }
    identity_bytes = json.dumps(
        identity,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    identity_sha256 = _sha256(identity_bytes)
    (oracle / "run_identity.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_identity_sha256": identity_sha256,
                "identity": identity,
            },
            sort_keys=True,
        )
        + "\n"
    )
    results = []
    for index, task in enumerate(tasks):
        passed = task in valid
        result = {
            "index": index,
            "name": task,
            "slug": task,
            "image": f"registry.example/tasks@sha256:{index:064x}",
            "valid": passed,
            "reason": "valid" if passed else "invalid",
            "error": None,
            "error_type": None,
            "elapsed_sec": 1.0,
            "attempts": 1,
            "infrastructure_failures": [],
            "oracle_network_semantics": semantics,
            "run_identity_sha256": identity_sha256,
        }
        results.append(result)
        (statuses / f"{task}.json").write_text(json.dumps(result) + "\n")
    (oracle / "results.jsonl").write_text("".join(json.dumps(result) + "\n" for result in results))
    reasons = Counter(result["reason"] for result in results)
    (oracle / "summary.json").write_text(
        json.dumps(
            {
                "selected": len(tasks),
                "completed": len(tasks),
                "passed": len(valid),
                "pass_rate": len(valid) / len(tasks),
                "reasons": dict(reasons),
                "oracle_network_semantics": semantics,
                "run_identity_sha256": identity_sha256,
                "finished_at": 1.0,
            }
        )
        + "\n"
    )
    (oracle / "run_config.json").write_text(
        json.dumps(
            {
                "dataset_dir": str(dataset.resolve()),
                "selected_tasks": len(tasks),
                "oracle_solution_network_mode": "public",
                "oracle_network_semantics": semantics,
                "run_identity_sha256": identity_sha256,
            }
        )
        + "\n"
    )
    (oracle / "oracle_network_semantics.json").write_text(json.dumps(semantics) + "\n")
    (oracle / "provenance.txt").write_text(
        f"prime_rl={prime_rl_commit}\n"
        f"prime_rl_tree={hashlib.sha256(b'').hexdigest()}\n"
        f"verifiers={VERIFIER_COMMIT}\n"
        f"vmvm_tb_v2={VMVM_TB_V2_SHA256}\n"
        "host=opaque-host\n"
        "slurm_job_id=1\n"
        "oracle_solution_network_mode=public\n"
        f"run_identity_sha256={identity_sha256}\n"
    )
    return oracle


def _config(
    path: Path,
    task_file: str,
    digest: str,
    count: int,
    dataset: Path,
    revision: str,
    image_manifest: Path,
) -> None:
    path.write_text(
        f"num_tasks = {count}\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f'dataset_dir = "{dataset.resolve()}"\n'
        f'dataset_revision = "{revision}"\n'
        f'task_file = "{task_file}"\n'
        f'task_file_sha256 = "{digest}"\n'
        f'image_manifest = "{image_manifest.resolve()}"\n'
        f'image_manifest_sha256 = "{IMAGE_MANIFEST_SHA256}"\n'
    )


def _fixture(
    tmp_path: Path,
    *,
    valid_indexes: set[int],
    limit: int = 8,
) -> tuple[Path, list[str], str, Path, Path, str, list[Path], str]:
    dataset, tasks, revision = _dataset(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / "approved.txt"
    current_bytes = "".join(f"{task}\n" for task in tasks[:limit]).encode()
    manifest.write_bytes(current_bytes)
    digest = _sha256(current_bytes)
    image_manifest = tmp_path / "image-manifest.json"
    image_manifest.write_bytes(IMAGE_MANIFEST_BYTES)
    configs = [project / "kimi.toml", project / "qwen.toml"]
    for config in configs:
        _config(config, manifest.name, digest, limit, dataset, revision, image_manifest)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{VERIFIER_COMMIT},deps/verifiers",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    prime_rl_commit = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    oracle = _oracle(
        tmp_path,
        dataset,
        tasks,
        {tasks[index] for index in valid_indexes},
        prime_rl_commit,
        revision,
        image_manifest,
        limit,
    )
    return dataset, tasks, revision, oracle, manifest, digest, configs, prime_rl_commit


def _provenance_args(prime_rl_commit: str) -> dict[str, str]:
    return {
        "expected_prime_rl_commit": prime_rl_commit,
        "required_prime_rl_ancestor": prime_rl_commit,
        "minimum_prime_rl_ancestor": prime_rl_commit,
        "expected_verifiers_commit": VERIFIER_COMMIT,
        "expected_vmvm_tb_v2_sha256": VMVM_TB_V2_SHA256,
        "expected_image_manifest_sha256": IMAGE_MANIFEST_SHA256,
    }


def test_dry_run_and_apply_replace_new_invalid_without_reordering_survivors(
    tmp_path: Path,
) -> None:
    dataset, tasks, revision, oracle, manifest, _, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(1, 10)),
    )
    prior_indexes = [3, 0, 7, 1, 6, 2, 5, 4]
    original_manifest = "".join(f"{tasks[index]}\n" for index in prior_indexes).encode()
    manifest.write_bytes(original_manifest)
    digest = _sha256(original_manifest)
    for config in configs:
        _config(
            config,
            manifest.name,
            digest,
            8,
            dataset,
            revision,
            tmp_path / "image-manifest.json",
        )
    original_configs = [path.read_bytes() for path in configs]
    arguments = {
        "dataset_dir": dataset,
        "dataset_revision": revision,
        "expected_current_manifest_sha256": digest,
        "configs": configs,
        "project_root": manifest.parent,
        "expected_total": 10,
        "limit": 8,
        "minimum_pass_rate": 0.9,
        **_provenance_args(prime_rl_commit),
    }

    checked = export_oracle_tasks.promote(oracle, manifest, **arguments)

    assert checked["applied"] is False
    assert checked["completed"] == 10
    assert checked["passed"] == 9
    assert checked["removed_invalid"] == 1
    assert checked["selected"] == 8
    assert checked["selected_subset_valid"] is True
    assert manifest.read_bytes() == original_manifest
    assert [path.read_bytes() for path in configs] == original_configs

    applied = export_oracle_tasks.promote(oracle, manifest, apply=True, **arguments)

    assert applied["applied"] is True
    assert manifest.read_text().splitlines() == [
        *(tasks[index] for index in prior_indexes if index != 0),
        tasks[8],
    ]
    assert _sha256(manifest.read_bytes()) == applied["selected_manifest_sha256"]
    for config in configs:
        parsed = tomllib.loads(config.read_text())
        assert parsed["taskset"]["task_file_sha256"] == applied["selected_manifest_sha256"]


@pytest.mark.parametrize(
    ("valid_indexes", "limit", "minimum_pass_rate", "error"),
    [
        (set(range(8)), 8, 0.9, "oracle_pass_rate_below_minimum"),
        (set(range(9)), 10, 0.9, "oracle_valid_count_below_minimum"),
    ],
)
def test_rejects_oracle_gate_failures(
    tmp_path: Path,
    valid_indexes: set[int],
    limit: int,
    minimum_pass_rate: float,
    error: str,
) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=valid_indexes,
        limit=limit,
    )

    with pytest.raises(PromotionError, match=f"^{error}$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=limit,
            minimum_pass_rate=minimum_pass_rate,
            **_provenance_args(prime_rl_commit),
        )


def test_rejects_incomplete_or_incoherent_oracle_before_writes(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    original = manifest.read_bytes()
    lines = (oracle / "results.jsonl").read_text().splitlines(keepends=True)
    (oracle / "results.jsonl").write_text("".join(lines[:-1]))

    with pytest.raises(PromotionError, match="^oracle_result_count_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            apply=True,
            **_provenance_args(prime_rl_commit),
        )
    assert manifest.read_bytes() == original


def test_rejects_unapproved_current_hash_and_config_drift(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    with pytest.raises(PromotionError, match="^current_manifest_hash_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256="0" * 64,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **_provenance_args(prime_rl_commit),
        )

    _config(
        configs[0],
        manifest.name,
        "1" * 64,
        8,
        dataset,
        revision,
        tmp_path / "image-manifest.json",
    )
    with pytest.raises(PromotionError, match="^config_current_hash_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            apply=True,
            **_provenance_args(prime_rl_commit),
        )

    _config(
        configs[0],
        manifest.name,
        digest,
        8,
        dataset,
        "f" * 40,
        tmp_path / "image-manifest.json",
    )
    with pytest.raises(PromotionError, match="^config_dataset_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **_provenance_args(prime_rl_commit),
        )

    _config(
        configs[0],
        manifest.name,
        digest,
        8,
        dataset,
        revision,
        tmp_path / "image-manifest.json",
    )
    configs[0].write_text(configs[0].read_text().replace(IMAGE_MANIFEST_SHA256, "0" * 64))
    with pytest.raises(PromotionError, match="^config_image_manifest_hash_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **_provenance_args(prime_rl_commit),
        )


def test_rejects_dirty_or_mismatched_oracle_provenance(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    provenance = oracle / "provenance.txt"
    provenance.write_text(
        provenance.read_text().replace(
            f"prime_rl_tree={hashlib.sha256(b'').hexdigest()}",
            f"prime_rl_tree={'c' * 64}",
        )
    )

    with pytest.raises(PromotionError, match="^oracle_provenance_mismatch$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **_provenance_args(prime_rl_commit),
        )


def test_rejects_missing_or_tampered_run_identity(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    arguments = {
        "dataset_dir": dataset,
        "dataset_revision": revision,
        "expected_current_manifest_sha256": digest,
        "configs": configs,
        "project_root": manifest.parent,
        "expected_total": 10,
        "limit": 8,
        **_provenance_args(prime_rl_commit),
    }
    identity_path = oracle / "run_identity.json"
    original = identity_path.read_bytes()
    identity_path.unlink()
    with pytest.raises(PromotionError, match="^oracle_run_identity_invalid$"):
        export_oracle_tasks.promote(oracle, manifest, **arguments)

    identity_path.write_bytes(original)
    wrapper = json.loads(identity_path.read_text())
    wrapper["identity"]["dataset"]["revision"] = "f" * 40
    identity_path.write_text(json.dumps(wrapper) + "\n")
    with pytest.raises(PromotionError, match="^oracle_run_identity_hash_mismatch$"):
        export_oracle_tasks.promote(oracle, manifest, **arguments)


def test_rejects_result_without_bound_run_identity(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    rows = (oracle / "results.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    del first["run_identity_sha256"]
    rows[0] = json.dumps(first)
    (oracle / "results.jsonl").write_text("\n".join(rows) + "\n")

    with pytest.raises(PromotionError, match="^oracle_result_schema_invalid$"):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **_provenance_args(prime_rl_commit),
        )


def test_rejects_malformed_or_divergent_terminal_rows(tmp_path: Path) -> None:
    dataset, tasks, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    arguments = {
        "dataset_dir": dataset,
        "dataset_revision": revision,
        "expected_current_manifest_sha256": digest,
        "configs": configs,
        "project_root": manifest.parent,
        "expected_total": 10,
        "limit": 8,
        **_provenance_args(prime_rl_commit),
    }
    results_path = oracle / "results.jsonl"
    original_results = results_path.read_bytes()
    rows = results_path.read_text().splitlines()
    first = json.loads(rows[0])
    first["index"] = False
    rows[0] = json.dumps(first)
    results_path.write_text("\n".join(rows) + "\n")
    with pytest.raises(PromotionError, match="^oracle_result_schema_invalid$"):
        export_oracle_tasks.promote(oracle, manifest, **arguments)

    results_path.write_bytes(original_results)
    status_path = oracle / "tasks" / f"{tasks[0]}.json"
    status = json.loads(status_path.read_text())
    status["attempts"] = 2
    status_path.write_text(json.dumps(status) + "\n")
    with pytest.raises(PromotionError, match="^oracle_status_mismatch$"):
        export_oracle_tasks.promote(oracle, manifest, **arguments)


def test_rejects_promotion_while_oracle_writer_is_active(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    with (oracle / ".writer.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PromotionError, match="^oracle_writer_active$"):
            export_oracle_tasks.promote(
                oracle,
                manifest,
                dataset_dir=dataset,
                dataset_revision=revision,
                expected_current_manifest_sha256=digest,
                configs=configs,
                project_root=manifest.parent,
                expected_total=10,
                limit=8,
                **_provenance_args(prime_rl_commit),
            )


def test_rejects_required_ancestor_before_lifecycle_baseline(tmp_path: Path) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    marker = manifest.parent / "lifecycle-marker"
    marker.write_text("final\n")
    subprocess.run(["git", "-C", str(manifest.parent), "add", marker.name], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(manifest.parent),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "lifecycle baseline",
        ],
        check=True,
    )
    lifecycle_commit = subprocess.run(
        ["git", "-C", str(manifest.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    provenance = _provenance_args(prime_rl_commit)
    provenance["minimum_prime_rl_ancestor"] = lifecycle_commit

    with pytest.raises(
        PromotionError,
        match="^required_oracle_ancestor_before_lifecycle_baseline$",
    ):
        export_oracle_tasks.promote(
            oracle,
            manifest,
            dataset_dir=dataset,
            dataset_revision=revision,
            expected_current_manifest_sha256=digest,
            configs=configs,
            project_root=manifest.parent,
            expected_total=10,
            limit=8,
            **provenance,
        )


def test_cli_emits_metadata_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _, revision, oracle, manifest, digest, configs, prime_rl_commit = _fixture(
        tmp_path,
        valid_indexes=set(range(10)),
    )
    monkeypatch.setattr(
        export_oracle_tasks,
        "MINIMUM_ORACLE_PRIME_RL_ANCESTOR",
        prime_rl_commit,
    )
    status = export_oracle_tasks.main(
        [
            str(oracle),
            str(manifest),
            "--dataset-dir",
            str(dataset),
            "--dataset-revision",
            revision,
            "--expected-current-manifest-sha256",
            digest,
            "--expected-prime-rl-commit",
            prime_rl_commit,
            "--required-prime-rl-ancestor",
            prime_rl_commit,
            "--expected-verifiers-commit",
            VERIFIER_COMMIT,
            "--expected-vmvm-tb-v2-sha256",
            VMVM_TB_V2_SHA256,
            "--expected-image-manifest-sha256",
            IMAGE_MANIFEST_SHA256,
            "--config",
            str(configs[0]),
            "--config",
            str(configs[1]),
            "--project-root",
            str(manifest.parent),
            "--expected-total",
            "10",
            "--limit",
            "8",
        ]
    )

    assert status == 0
    output = capsys.readouterr()
    assert "opaque-" not in output.out
    assert output.err == ""
    assert json.loads(output.out)["selected_subset_valid"] is True
