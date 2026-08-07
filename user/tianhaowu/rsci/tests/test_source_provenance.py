import json
import subprocess
import sys
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


def test_verify_source_cli_skips_launch_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    snapshot = run_dir / provenance.SNAPSHOT_NAME
    calls = []

    def fake_verify_snapshot(
        requested_run_dir: Path,
        expected_source: Path | None = None,
        *,
        verify_imports: bool = True,
        require_launch: bool = True,
    ) -> dict[str, str]:
        calls.append((requested_run_dir, expected_source, verify_imports, require_launch))
        return {"snapshot_path": str(snapshot)}

    monkeypatch.setattr(provenance, "verify_snapshot", fake_verify_snapshot)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "source_provenance.py",
            "verify-source",
            str(run_dir),
            "--expected-source",
            str(snapshot),
        ],
    )

    provenance.main()

    assert calls == [(run_dir, snapshot, True, False)]


def test_verify_cli_still_requires_launch_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    snapshot = run_dir / provenance.SNAPSHOT_NAME
    calls = []

    def fake_verify_snapshot(
        requested_run_dir: Path,
        expected_source: Path | None = None,
        *,
        verify_imports: bool = True,
        require_launch: bool = True,
    ) -> dict[str, str]:
        calls.append((requested_run_dir, expected_source, verify_imports, require_launch))
        return {"snapshot_path": str(snapshot)}

    monkeypatch.setattr(provenance, "verify_snapshot", fake_verify_snapshot)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "source_provenance.py",
            "verify",
            str(run_dir),
            "--expected-source",
            str(snapshot),
        ],
    )

    provenance.main()

    assert calls == [(run_dir, snapshot, True, True)]


def test_evaluation_bootstrap_does_not_weaken_training_activation() -> None:
    rsci_root = Path(__file__).resolve().parents[1]
    training_activation = (rsci_root / "scripts" / "activate_source_snapshot.sh").read_text(encoding="utf-8")
    evaluation_activation = (rsci_root / "scripts" / "activate_source_snapshot_eval.sh").read_text(encoding="utf-8")
    frozen_bank = (rsci_root / "scripts" / "run_verifier_frozen_bank.sbatch").read_text(encoding="utf-8")

    assert "source_provenance.py verify \\\n" in training_activation
    assert "verify-source" not in training_activation
    assert "source_provenance.py verify-source \\\n" in evaluation_activation
    assert "activate_source_snapshot_eval.sh" in frozen_bank
    assert "scripts/run_eval.sh" in frozen_bank
    assert frozen_bank.index('source "$SOURCE_BOOTSTRAP" "$RUN_DIR"') < frozen_bank.index(
        'realpath -e -- "$RSCI_SOURCE_SNAPSHOT/$CONFIG_REPO_PATH"'
    )
    assert "#SBATCH --qos=h100_lowest" in frozen_bank
    assert "#SBATCH --nodes=4" in frozen_bank
    assert "#SBATCH --ntasks-per-node=1" in frozen_bank
    assert "#SBATCH --gres=gpu:8" in frozen_bank
    assert "#SBATCH --cpus-per-task=64" in frozen_bank
    assert "#SBATCH --mem=256G" in frozen_bank
    assert "#SBATCH --time=04:00:00" in frozen_bank
    assert "#SBATCH --requeue" in frozen_bank


def _write_frozen_bank_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    snapshot = run_dir / provenance.SNAPSHOT_NAME
    scripts = snapshot / "user" / "tianhaowu" / "rsci" / "scripts"
    scripts.mkdir(parents=True)
    activation = scripts / "activate_source_snapshot_eval.sh"
    activation.write_text(
        'export RSCI_SOURCE_SNAPSHOT=$(realpath "$1/source_snapshot")\ncd "$RSCI_SOURCE_SNAPSHOT"\n',
        encoding="utf-8",
    )
    run_eval = scripts / "run_eval.sh"
    run_eval.write_text('printf "%s\\n" "$1"\n', encoding="utf-8")
    inference = snapshot / "configs" / "inference.toml"
    inference.parent.mkdir(parents=True)
    inference.write_text("[model]\n", encoding="utf-8")
    evaluator = snapshot / "evaluator.py"
    evaluator.write_text("# fixture\n", encoding="utf-8")
    config = snapshot / "user" / "tianhaowu" / "rsci" / "configs" / "eval" / "bank.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'infer_config = "configs/inference.toml"\nevaluator = "evaluator.py"\n\n[eval]\n',
        encoding="utf-8",
    )
    wrapper = Path(__file__).resolve().parents[1] / "scripts" / "run_verifier_frozen_bank.sbatch"
    return wrapper, run_dir, config


def _run_frozen_bank(wrapper: Path, run_dir: Path, config_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(wrapper), config_path, str(run_dir)],
        cwd=run_dir.parent,
        text=True,
        capture_output=True,
        check=False,
    )


def test_frozen_bank_resolves_config_after_source_activation(tmp_path: Path) -> None:
    wrapper, run_dir, config = _write_frozen_bank_fixture(tmp_path)
    relative_config = config.relative_to(run_dir / provenance.SNAPSHOT_NAME).as_posix()
    mutable_decoy = run_dir.parent / relative_config
    mutable_decoy.parent.mkdir(parents=True)
    mutable_decoy.write_text("[mutable]\n", encoding="utf-8")

    result = _run_frozen_bank(wrapper, run_dir, relative_config)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(config.resolve())


@pytest.mark.parametrize(
    "config_path",
    [
        "/tmp/mutable-eval.toml",
        "../mutable-eval.toml",
        "configs/../mutable-eval.toml",
    ],
)
def test_frozen_bank_rejects_absolute_and_traversal_paths(tmp_path: Path, config_path: str) -> None:
    wrapper, run_dir, _ = _write_frozen_bank_fixture(tmp_path)

    result = _run_frozen_bank(wrapper, run_dir, config_path)

    assert result.returncode == 2
    assert "repository-relative path without '..'" in result.stderr


def test_frozen_bank_rejects_symlink_escape(tmp_path: Path) -> None:
    wrapper, run_dir, _ = _write_frozen_bank_fixture(tmp_path)
    snapshot = run_dir / provenance.SNAPSHOT_NAME
    external_config = tmp_path / "mutable-eval.toml"
    external_config.write_text("[eval]\n", encoding="utf-8")
    escape = snapshot / "configs" / "escape.toml"
    escape.parent.mkdir(exist_ok=True)
    escape.symlink_to(external_config)

    result = _run_frozen_bank(wrapper, run_dir, "configs/escape.toml")

    assert result.returncode == 2
    assert "escapes the source snapshot" in result.stderr
