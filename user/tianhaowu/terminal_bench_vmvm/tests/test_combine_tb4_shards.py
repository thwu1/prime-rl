from __future__ import annotations

import hashlib
import json
from pathlib import Path

import combine_tb4_shards as combine_module
import pytest
from audit_tb4_results import EXPECTED_TASK_COUNT, EXPECTED_UNSUPPORTED_TASKS
from combine_tb4_shards import (
    SHARD_SPECS,
    CombineError,
    _read_tasks,
    _read_toml,
    _validate_config,
    combine_shards,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    for spec in SHARD_SPECS:
        for slug in _read_tasks(spec.task_file):
            task = root / slug
            task.mkdir(parents=True)
            (task / "task.toml").write_text("")
            (task / "instruction.md").write_text(f"Complete {slug}.\n")
    return root


def _write_shard(
    tmp_path: Path,
    spec,
    dataset_dir: Path,
    *,
    endpoint: str | None = None,
    tasks: list[str] | None = None,
    revisions: tuple[str, str, str] = ("1" * 40, "2" * 40, "3" * 40),
) -> Path:
    shard_dir = tmp_path / f"shard-{spec.name}"
    inputs = shard_dir / "inputs"
    inputs.mkdir(parents=True)
    (shard_dir / ".writer.lock").write_text("")

    source_text = spec.config.read_text().replace(
        "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks",
        str(dataset_dir),
    )
    source_config = inputs / "source_config.toml"
    source_config.write_text(source_text)
    task_snapshot = inputs / "task_file.txt"
    task_snapshot.write_bytes(spec.task_file.read_bytes())
    input_manifest = {
        "config": {
            "source": str(spec.config),
            "snapshot": str(source_config.resolve()),
            "sha256": _sha256(source_config),
        },
        "task_file": {
            "source": str(spec.task_file),
            "snapshot": str(task_snapshot.resolve()),
            "sha256": _sha256(task_snapshot),
        },
    }
    (inputs / "manifest.json").write_text(json.dumps(input_manifest, indent=2, sort_keys=True) + "\n")

    saved_text = source_text.replace(
        f'task_file = "{spec.task_file.relative_to(combine_module.WORKFLOW_DIR.parents[2])}"',
        f'task_file = "{task_snapshot.resolve()}"',
    )
    (shard_dir / "config.toml").write_text(saved_text)
    selected_endpoint = endpoint or spec.endpoint
    (shard_dir / "provenance.txt").write_text(
        "\n".join(
            [
                f"prime_rl={revisions[0]}",
                f"verifiers={revisions[1]}",
                f"renderers={revisions[2]}",
                f"inference_base_url={selected_endpoint}",
                "inference_deployment_id=",
                f"slurm_job_id={100 + ord(spec.name)}",
                "",
            ]
        )
    )
    rows = tasks if tasks is not None else _read_tasks(spec.task_file)
    with (shard_dir / "results.jsonl").open("w", encoding="utf-8") as output:
        for index, slug in enumerate(rows):
            output.write(
                json.dumps(
                    {
                        "id": f"{spec.name}-{index}",
                        "task": {"slug": slug, "name": f"terminal-bench/{slug}"},
                    }
                )
                + "\n"
            )
    return shard_dir


def _accept_audit(results: Path, **_kwargs):
    assert sum(1 for line in results.read_text().splitlines() if line.strip()) == EXPECTED_TASK_COUNT
    return {"ok": True, "trace_failures": 0, "global_problems": []}, False


def test_committed_direct_shards_are_exact_and_pinned():
    task_sets = []
    for spec in SHARD_SPECS:
        assert _sha256(spec.task_file) == spec.task_file_sha256
        tasks = set(_read_tasks(spec.task_file))
        assert len(tasks) == EXPECTED_TASK_COUNT // 2
        task_sets.append(tasks)
        config = _read_toml(spec.config)
        _validate_config(
            config,
            spec,
            task_file=None,
            dataset_dir=Path(config["taskset"]["dataset_dir"]).resolve(),
        )

    assert task_sets[0].isdisjoint(task_sets[1])
    assert len(task_sets[0] | task_sets[1]) == EXPECTED_TASK_COUNT
    assert EXPECTED_UNSUPPORTED_TASKS.issubset(task_sets[0] | task_sets[1])


def test_combine_validates_and_atomically_publishes(tmp_path: Path, monkeypatch):
    dataset_dir = _dataset(tmp_path)
    shards = tuple(_write_shard(tmp_path, spec, dataset_dir) for spec in SHARD_SPECS)
    output_dir = tmp_path / "combined"
    monkeypatch.setattr(combine_module, "audit_results", _accept_audit)

    manifest = combine_shards(
        shards,
        output_dir=output_dir,
        dataset_dir=dataset_dir,
    )

    assert output_dir.is_dir()
    assert (output_dir / "checkpoint.json").is_file()
    assert (output_dir / "merge_manifest.json").is_file()
    assert len((output_dir / "results.jsonl").read_text().splitlines()) == 66
    assert manifest["combined_trace_count"] == 66
    assert [record["trace_count"] for record in manifest["shards"]] == [33, 33]
    assert manifest["combined_results_sha256"] == _sha256(output_dir / "results.jsonl")


def test_combine_rejects_wrong_shard_membership_without_output(tmp_path: Path):
    dataset_dir = _dataset(tmp_path)
    first_tasks = _read_tasks(SHARD_SPECS[0].task_file)
    bad_tasks = [first_tasks[1], *first_tasks[1:]]
    shards = (
        _write_shard(tmp_path, SHARD_SPECS[0], dataset_dir, tasks=bad_tasks),
        _write_shard(tmp_path, SHARD_SPECS[1], dataset_dir),
    )
    output_dir = tmp_path / "combined"

    with pytest.raises(CombineError, match="task mismatch"):
        combine_shards(shards, output_dir=output_dir, dataset_dir=dataset_dir)

    assert not output_dir.exists()


def test_combine_rejects_endpoint_mismatch(tmp_path: Path):
    dataset_dir = _dataset(tmp_path)
    shards = (
        _write_shard(tmp_path, SHARD_SPECS[0], dataset_dir),
        _write_shard(
            tmp_path,
            SHARD_SPECS[1],
            dataset_dir,
            endpoint="http://wrong.invalid/v1",
        ),
    )
    output_dir = tmp_path / "combined"

    with pytest.raises(CombineError, match="inference_base_url"):
        combine_shards(shards, output_dir=output_dir, dataset_dir=dataset_dir)

    assert not output_dir.exists()


def test_combine_rejects_revision_mismatch(tmp_path: Path):
    dataset_dir = _dataset(tmp_path)
    shards = (
        _write_shard(tmp_path, SHARD_SPECS[0], dataset_dir),
        _write_shard(
            tmp_path,
            SHARD_SPECS[1],
            dataset_dir,
            revisions=("4" * 40, "2" * 40, "3" * 40),
        ),
    )
    output_dir = tmp_path / "combined"

    with pytest.raises(CombineError, match="different code revisions"):
        combine_shards(shards, output_dir=output_dir, dataset_dir=dataset_dir)

    assert not output_dir.exists()


def test_combine_rejects_snapshot_hash_mismatch(tmp_path: Path):
    dataset_dir = _dataset(tmp_path)
    shards = tuple(_write_shard(tmp_path, spec, dataset_dir) for spec in SHARD_SPECS)
    manifest_path = shards[0] / "inputs" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["task_file"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n")
    output_dir = tmp_path / "combined"

    with pytest.raises(CombineError, match="SHA-256 mismatch"):
        combine_shards(shards, output_dir=output_dir, dataset_dir=dataset_dir)

    assert not output_dir.exists()


def test_combine_does_not_publish_failed_strict_audit(tmp_path: Path, monkeypatch):
    dataset_dir = _dataset(tmp_path)
    shards = tuple(_write_shard(tmp_path, spec, dataset_dir) for spec in SHARD_SPECS)
    output_dir = tmp_path / "combined"
    monkeypatch.setattr(
        combine_module,
        "audit_results",
        lambda *_args, **_kwargs: (
            {"ok": False, "trace_failures": 1, "global_problems": []},
            True,
        ),
    )

    with pytest.raises(CombineError, match="strict TB4 audit failed"):
        combine_shards(shards, output_dir=output_dir, dataset_dir=dataset_dir)

    assert not output_dir.exists()
