import json
from pathlib import Path

import pytest
import source_provenance as provenance
from source_provenance import (
    _launch_artifact_hashes,
    _launch_input_identities,
    _verify_launch_materialization,
    materialize_launch,
    source_tree_sha256,
)


def _write_launch(run_dir: Path, snapshot: Path, *, prefix: str = "") -> None:
    config_dir = run_dir / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("inference.toml", "orchestrator.toml", "trainer.toml"):
        (config_dir / name).write_text(f'name = "{name}"\n', encoding="utf-8")
    (run_dir / "rl.sbatch").write_text(
        prefix
        + f"export PROJECT_DIR={snapshot}\n"
        + f"export OUTPUT_DIR={run_dir}\n"
        + 'source user/tianhaowu/rsci/scripts/activate_source_snapshot.sh "$OUTPUT_DIR"\n'
        + "uv run rl @ configs/rl.toml\n",
        encoding="utf-8",
    )


def test_source_tree_digest_ignores_shared_venv_link_and_detects_source_changes(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    source = snapshot / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (snapshot / ".venv").symlink_to(tmp_path / "environment", target_is_directory=True)

    first = source_tree_sha256(snapshot)
    (snapshot / ".venv").unlink()
    (snapshot / ".venv").symlink_to(tmp_path / "other-environment", target_is_directory=True)
    assert source_tree_sha256(snapshot) == first

    source.write_text("value = 2\n", encoding="utf-8")
    assert source_tree_sha256(snapshot) != first


def test_scoped_source_digest_binds_only_declared_runtime_closure(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    runtime = snapshot / "runtime"
    runtime.mkdir(parents=True)
    source = runtime / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    unrelated = snapshot / "docs.txt"
    unrelated.write_text("first\n", encoding="utf-8")

    first = source_tree_sha256(snapshot, ("runtime",))
    unrelated.write_text("second\n", encoding="utf-8")
    assert source_tree_sha256(snapshot, ("runtime",)) == first

    source.write_text("value = 2\n", encoding="utf-8")
    assert source_tree_sha256(snapshot, ("runtime",)) != first


def test_launch_hashes_bind_all_resolved_configs_and_activation_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    snapshot = run_dir / "source_snapshot"
    snapshot.mkdir(parents=True)
    _write_launch(run_dir, snapshot)

    hashes = _launch_artifact_hashes(run_dir, snapshot)
    assert set(hashes) == {
        "rl.sbatch",
        "configs/inference.toml",
        "configs/orchestrator.toml",
        "configs/trainer.toml",
    }

    _write_launch(run_dir, snapshot, prefix="uv run python -c 'import prime_rl'\n")
    with pytest.raises(ValueError, match="before the snapshot activation guard"):
        _launch_artifact_hashes(run_dir, snapshot)


def test_materialize_launch_runs_pinned_configs_from_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    snapshot = run_dir / "source_snapshot"
    config_paths = [Path("configs/base.toml"), Path("configs/overlay.toml")]
    for config_path in config_paths:
        path = snapshot / config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("max_steps = 1\n", encoding="utf-8")
    manifest_path = run_dir / provenance.MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": provenance.SCHEMA_VERSION,
                "source_repo": str(provenance.LIVE_REPO_ROOT),
                "parent_commit_sha": "a" * 40,
                "source_tree_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        provenance,
        "verify_snapshot",
        lambda requested_run_dir, require_launch: {
            "snapshot_path": str(snapshot),
        },
    )
    invocation = {}

    def fake_run(command, *, cwd, env, text=True):
        invocation.update(command=command, cwd=cwd, env=env, text=text)
        _write_launch(run_dir, snapshot)

    monkeypatch.setattr(provenance, "_run", fake_run)

    result = materialize_launch(run_dir, config_paths)

    assert invocation["cwd"] == snapshot
    assert invocation["env"]["RSCI_SOURCE_SNAPSHOT"] == str(snapshot)
    assert invocation["env"]["UV_PROJECT_ENVIRONMENT"] == str(snapshot / ".venv")
    assert invocation["env"]["NEVER_CLEAN_OUTPUT_DIR"] == "1"
    assert invocation["command"] == [
        "uv",
        "run",
        "--no-sync",
        "rl",
        "@",
        "configs/base.toml",
        "@",
        "configs/overlay.toml",
        "--dry-run",
    ]
    materialization = result["launch_materialization"]
    assert materialization["config_paths"] == ["configs/base.toml", "configs/overlay.toml"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _verify_launch_materialization(run_dir, snapshot, manifest, required=True) == materialization

    (run_dir / "configs" / "trainer.toml").write_text("changed = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after pinned materialization"):
        _verify_launch_materialization(run_dir, snapshot, manifest, required=True)


def test_launch_inputs_hash_datasets_and_follow_model_symlinks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    config_dir = run_dir / "configs"
    config_dir.mkdir(parents=True)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    blob = tmp_path / "weight-blob"
    blob.write_bytes(b"weights-v1")
    (model_dir / "model.safetensors").symlink_to(blob)
    chat_template = model_dir / "chat_template.jinja"
    chat_template.write_text("{{ messages }}\n", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}\n", encoding="utf-8")
    train_data = tmp_path / "train.jsonl"
    eval_data = tmp_path / "eval.jsonl"
    train_data.write_text('{"id": "train"}\n', encoding="utf-8")
    eval_data.write_text('{"id": "eval"}\n', encoding="utf-8")
    (tmp_path / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "train": {
                        "path": str(train_data),
                        "sha256": provenance.sha256_file(train_data),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    (config_dir / "trainer.toml").write_text(
        f'[model]\nname = "{model_dir}"\n[tokenizer]\nname = "{model_dir}"\nchat_template = "{chat_template}"\n',
        encoding="utf-8",
    )
    (config_dir / "inference.toml").write_text(
        f'[model]\nname = "{model_dir}"\nchat_template = "{chat_template}"\n',
        encoding="utf-8",
    )
    (config_dir / "orchestrator.toml").write_text(
        f'[student.model]\nname = "{model_dir}"\n[tokenizer]\nname = "{model_dir}"\n'
        f'chat_template = "{chat_template}"\n'
        f'[[train.env]]\nid = "env"\nname = "train"\nargs = {{ dataset_path = "{train_data}" }}\n'
        f'[[eval.env]]\nid = "env"\nname = "eval"\nargs = {{ dataset_path = "{eval_data}" }}\n',
        encoding="utf-8",
    )

    first = _launch_input_identities(run_dir)
    assert {entry["path"] for entry in first["datasets"]} == {str(train_data), str(eval_data)}
    assert next(entry for entry in first["datasets"] if entry["path"] == str(train_data))["dataset_manifest"][
        "declared_dataset_sha256"
    ] == provenance.sha256_file(train_data)
    assert first["base_model"]["file_count"] == 3
    assert first["base_model"]["sha256"] == first["tokenizer"]["sha256"]

    train_data.write_text('{"id": "changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Dataset bytes do not match"):
        _launch_input_identities(run_dir)
    train_data.write_text('{"id": "train"}\n', encoding="utf-8")
    eval_data.write_text('{"id": "changed"}\n', encoding="utf-8")
    assert _launch_input_identities(run_dir) != first
    eval_data.write_text('{"id": "eval"}\n', encoding="utf-8")
    blob.write_bytes(b"weights-v2")
    assert _launch_input_identities(run_dir)["base_model"]["sha256"] != first["base_model"]["sha256"]
