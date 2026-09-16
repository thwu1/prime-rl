from __future__ import annotations

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
) -> Path:
    oracle = tmp_path / "oracle"
    statuses = oracle / "tasks"
    statuses.mkdir(parents=True)
    semantics = {
        "schema_version": 1,
        "trusted_reference_solution": "public",
        "verifier": "declared",
    }
    results = []
    for index, task in enumerate(tasks):
        passed = task in valid
        result = {
            "index": index,
            "slug": task,
            "valid": passed,
            "reason": "valid" if passed else "invalid",
            "oracle_network_semantics": semantics,
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
    )
    return oracle


def _config(path: Path, task_file: str, digest: str, count: int) -> None:
    path.write_text(
        f"num_tasks = {count}\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f'task_file = "{task_file}"\n'
        f'task_file_sha256 = "{digest}"\n'
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
    configs = [project / "kimi.toml", project / "qwen.toml"]
    for config in configs:
        _config(config, manifest.name, digest, limit)
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
    )
    return dataset, tasks, revision, oracle, manifest, digest, configs, prime_rl_commit


def _provenance_args(prime_rl_commit: str) -> dict[str, str]:
    return {
        "expected_prime_rl_commit": prime_rl_commit,
        "required_prime_rl_ancestor": prime_rl_commit,
        "minimum_prime_rl_ancestor": prime_rl_commit,
        "expected_verifiers_commit": VERIFIER_COMMIT,
        "expected_vmvm_tb_v2_sha256": VMVM_TB_V2_SHA256,
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
        _config(config, manifest.name, digest, 8)
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

    _config(configs[0], manifest.name, "1" * 64, 8)
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
