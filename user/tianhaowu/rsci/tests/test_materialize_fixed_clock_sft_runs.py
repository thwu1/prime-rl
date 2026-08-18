from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import materialize_fixed_clock_sft_runs as materializer
import pytest
from materialize_fixed_clock_sft_runs import (
    ACTIVATOR_REPO_PATH,
    BATCH_SIZE,
    CHECKPOINT_INTERVAL,
    COMMON_STEPS,
    CONTROL_TMUX_SESSION,
    CONTROL_TMUX_SOCKET,
    CONTROL_TMUX_WINDOW,
    LAUNCH_MANIFEST_NAME,
    LAUNCH_TRAINING_CONTRACT,
    SCHEMA_VERSION,
    SCRIPT_REPO_PATH,
    STATIC_SFT_CONTRACT,
    STUDY_ID,
    TEMPLATE_REPO_PATH,
    SourceState,
    canonical_json_sha256,
    file_identity,
    frozen_bank_model_identity,
    launch_config,
    max_steps_for_arm,
    readout_steps,
    require_control_tmux,
    schedule_label,
    submission_commands,
    submit,
    two_pass_steps,
    validate_launch_manifest,
    validate_resolved_config,
    validate_sbatch,
    validate_study_inputs,
    write_json_atomic,
    write_toml_once,
)

from prime_rl.configs.sft import SFTConfig
from prime_rl.entrypoints.sft import write_config, write_slurm_script

REPO_ROOT = Path(__file__).resolve().parents[4]
DOSE_BY_LABEL = {"p0025": "1/400", "p0050": "1/200", "p0100": "1/100"}
TREATMENT_OPERATIONS = list(range(21, 41))
ROWS_PER_OPERATION = 128_000
STRICT_DEAD_CONTRACT = {
    "required": True,
    "definition": "every frozen trajectory in every treatment operation has strict perfect=false",
    "operations": TREATMENT_OPERATIONS,
    "rows_per_operation": ROWS_PER_OPERATION,
    "strict_positive_counts_by_op": {str(operation): 0 for operation in TREATMENT_OPERATIONS},
    "candidate_counts_by_op": {str(operation): 1_000 for operation in TREATMENT_OPERATIONS},
    "verified_rows_by_op": {str(operation): ROWS_PER_OPERATION for operation in TREATMENT_OPERATIONS},
}


def _builder_file_identity(path: Path) -> dict:
    identity = file_identity(path)
    return {
        "path": identity["resolved_path"],
        "size_bytes": identity["size_bytes"],
        "sha256": identity["sha256"],
    }


def _metadata(label: str) -> dict:
    if label == "c0_anchor":
        return {
            "clock": "anchor_only",
            "assignment": "clean",
            "dose": "0/1",
            "dose_label": "p0000",
            "selection_seed": 20260807,
            "raw_prefix_trajectories": 0,
            "hard_recipient_rows": 0,
            "hard_recipient_fraction": 0.0,
            "treatment_recipient_rows": 0,
            "treatment_recipient_fraction": 0.0,
            "candidate_overlap": None,
            "global_candidate_overlap": None,
            "global_eligible_rows": None,
            "global_effective_rate": None,
            "global_max_draw_uint64": None,
            "iid_eligible_rows": None,
            "iid_realized_rate": None,
        }
    stem, assignment_code = label.rsplit("_", maxsplit=1)
    prefix, clock_and_dose = stem.split("_fixed_", maxsplit=1)
    seed = int(prefix.removeprefix("seed"))
    clock_suffix, dose_label = clock_and_dose.rsplit("_", maxsplit=1)
    return {
        "clock": f"fixed_{clock_suffix}",
        "assignment": {"b": "behavior", "s": "shuffled", "g": "global", "i": "iid"}[assignment_code],
        "dose": DOSE_BY_LABEL[dose_label],
        "dose_label": dose_label,
        "selection_seed": seed,
        "raw_prefix_trajectories": 100_000,
        "hard_recipient_rows": 512,
        "hard_recipient_fraction": 0.5,
        "treatment_recipient_rows": 512,
        "treatment_recipient_fraction": 0.5,
        "candidate_overlap": (
            512
            if assignment_code == "b" and clock_suffix == "m"
            else {"p0025": 512, "p0050": 1024, "p0100": 2048}[dose_label]
            if assignment_code in {"b", "i"}
            else 0
        ),
        "global_candidate_overlap": 0 if assignment_code == "g" else None,
        "global_eligible_rows": 100_000 if assignment_code == "g" else None,
        "global_effective_rate": 0.005 if assignment_code == "g" else None,
        "global_max_draw_uint64": "1234" if assignment_code == "g" else None,
        "iid_eligible_rows": 100_000 if assignment_code == "i" else None,
        "iid_realized_rate": None,
    }


def _study_labels() -> tuple[set[str], set[str]]:
    canonical = {"c0_anchor"}
    aliases = set()
    for seed in (20260805, 20260806, 20260807):
        for assignment in ("b", "s", "g"):
            for dose_label in DOSE_BY_LABEL:
                canonical.add(f"seed{seed}_fixed_m_{dose_label}_{assignment}")
            for dose_label in ("p0050", "p0100"):
                canonical.add(f"seed{seed}_fixed_raw_{dose_label}_{assignment}")
            aliases.add(f"seed{seed}_fixed_raw_p0025_{assignment}")
        for dose_label in DOSE_BY_LABEL:
            canonical.add(f"seed{seed}_fixed_raw_{dose_label}_i")
    return canonical, aliases


def _build_arm_index(tmp_path: Path) -> tuple[Path, Path]:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"qwen2"}\n', encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"tiny-model")
    chat_template = model / "chat_template.jinja"
    chat_template.write_text("{% for message in messages %}{{ message.content }}{% endfor %}\n", encoding="utf-8")
    tokenizer = {
        "configured_path": str(model.resolve()),
        "chat_template": _builder_file_identity(chat_template),
    }
    canonical_labels, alias_labels = _study_labels()
    root = tmp_path / "datasets"
    entries: list[dict] = []
    canonical_entries: dict[str, dict] = {}
    bank_contract = {"model": frozen_bank_model_identity(model)}
    bank_sha256 = canonical_json_sha256(bank_contract)
    bank_manifest_path = tmp_path / "bank" / "manifest.json"
    write_json_atomic(
        bank_manifest_path,
        {
            "schema_version": 1,
            "contract_sha256": bank_sha256,
            "contract": bank_contract,
        },
    )
    for label in sorted(canonical_labels):
        arm_dir = root / "arms" / label
        arm_dir.mkdir(parents=True)
        parquet = arm_dir / "train-00000-of-00001.parquet"
        parquet.write_bytes(f"parquet:{label}".encode())
        metadata = _metadata(label)
        rows = 512 if label == "c0_anchor" else 1024
        if label.endswith("_i"):
            rows = {"p0025": 2048, "p0050": 3584, "p0100": 6656}[metadata["dose_label"]]
            metadata["iid_realized_rate"] = (rows - 512) / metadata["iid_eligible_rows"]
        elif "fixed_raw_p0050" in label:
            rows = 1536
        elif "fixed_raw_p0100" in label:
            rows = 2560
        treatment_rows = rows - 512
        metadata["hard_recipient_rows"] = treatment_rows
        metadata["treatment_recipient_rows"] = treatment_rows
        metadata["hard_recipient_fraction"] = treatment_rows / rows
        metadata["treatment_recipient_fraction"] = treatment_rows / rows
        arm = {"label": label, "metadata": metadata, "rows": rows}
        parquet_record = _builder_file_identity(parquet)
        parquet_record["rows"] = rows
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "arm": {"label": label, **metadata},
            "bank_contract_sha256": bank_sha256,
            "strict_dead_contract": STRICT_DEAD_CONTRACT,
            "rows": rows,
            "assistant_weight_mass": float(rows),
            "max_model_input_tokens": 100,
            "parquet": parquet_record,
            "sft_contract": {
                **STATIC_SFT_CONTRACT,
                "max_steps": max_steps_for_arm(arm),
                "ckpt.interval": CHECKPOINT_INTERVAL,
                "readout_steps": readout_steps(arm),
                "two_pass_steps": two_pass_steps(arm),
                "schedule": schedule_label(arm),
            },
            "tokenizer": tokenizer,
        }
        manifest_path = arm_dir / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        entry = {
            "label": label,
            "alias_of": None,
            "dataset_path": str(arm_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "parquet_sha256": file_identity(parquet)["sha256"],
            "rows": rows,
            **metadata,
        }
        entries.append(entry)
        canonical_entries[label] = entry
    for alias_label in sorted(alias_labels):
        canonical_label = alias_label.replace("fixed_raw_p0025", "fixed_m_p0025")
        entries.append(
            {
                **canonical_entries[canonical_label],
                "label": alias_label,
                "alias_of": canonical_label,
                "clock": "fixed_raw",
            }
        )
    index = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "bank_contract_sha256": bank_sha256,
        "protocol": {
            "bank_operations": [10, 11, 12, *range(15, 41)],
            "anchor_operations": [10, 11, 12],
            "treatment_operations": TREATMENT_OPERATIONS,
            "examples_per_operation": 1_000,
            "samples_per_prompt": 128,
            "selection_seeds": [20260805, 20260806, 20260807],
            "doses": ["1/400", "1/200", "1/100"],
            "target_count": 512,
            "anchor_count": 512,
            "selection_hash_domain": "rsci-fixed-clock-sft-v2",
            "strict_dead_contract": STRICT_DEAD_CONTRACT,
            "arm_count_contract": {
                "assignments": ["behavior", "shuffled", "global", "iid"],
                "bsg_canonical_specs_per_seed": 5,
                "iid_canonical_specs_per_seed": 3,
                "distinct_training_arms": 55,
                "minimum_dose_aliases": 9,
                "arm_index_entries": 64,
            },
        },
        "tokenizer": tokenizer,
        "inputs": {"manifest": _builder_file_identity(bank_manifest_path)},
        "distinct_training_arms": sorted(canonical_labels),
        "arms": sorted(entries, key=lambda entry: entry["label"]),
    }
    index_path = root / "arm_index.json"
    write_json_atomic(index_path, index)
    return index_path, model


def _materialized_launch(tmp_path: Path) -> tuple[Path, dict]:
    index_path, model = _build_arm_index(tmp_path)
    inputs = validate_study_inputs(index_path, model)
    launch_root = tmp_path / "launch"
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    provenance_path = source_run / "source_provenance.json"
    write_json_atomic(provenance_path, {"schema_version": 2})
    source = SourceState(
        run_dir=source_run,
        root=REPO_ROOT,
        provenance={"parent_commit_sha": "b" * 40, "source_tree_sha256": "c" * 64},
    )
    records = []
    for arm in inputs["arms"]:
        config_dict = launch_config(
            arm,
            launch_root=launch_root,
            source=source,
            base_model=model.resolve(),
            chat_template=(model / "chat_template.jinja").resolve(),
        )
        config = SFTConfig.model_validate(config_dict)
        launch_config_path = launch_root / "launch_configs" / f"{arm['label']}.toml"
        write_toml_once(launch_config_path, config_dict)
        output_dir = Path(config.output_dir)
        resolved_config = output_dir / "configs" / "sft.toml"
        write_config(config, resolved_config, exclude={"slurm", "dry_run", "clean_output_dir"})
        sbatch = output_dir / "sft.sbatch"
        write_slurm_script(config, resolved_config, sbatch)
        records.append(
            {
                **arm,
                "output_dir": str(output_dir),
                "launch_config": file_identity(launch_config_path),
                "resolved_config": file_identity(resolved_config),
                "sbatch": file_identity(sbatch),
                "wandb": config_dict["wandb"],
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "launch_root": str(launch_root),
        "source_run_dir": str(source_run),
        "source": {
            "snapshot_path": str(REPO_ROOT),
            "parent_commit_sha": "b" * 40,
            "source_tree_sha256": "c" * 64,
            "provenance_manifest": file_identity(provenance_path),
        },
        "inputs": {
            key: inputs[key]
            for key in (
                "arm_index",
                "bank_contract_sha256",
                "base_model",
                "frozen_bank_manifest",
                "frozen_bank_model",
                "chat_template",
            )
        },
        "implementation": file_identity(REPO_ROOT / SCRIPT_REPO_PATH),
        "template": file_identity(REPO_ROOT / TEMPLATE_REPO_PATH),
        "activator": file_identity(REPO_ROOT / ACTIVATOR_REPO_PATH),
        "training_contract": LAUNCH_TRAINING_CONTRACT,
        "arm_count": len(records),
        "arms": records,
    }
    manifest_path = launch_root / LAUNCH_MANIFEST_NAME
    write_json_atomic(manifest_path, manifest)
    return manifest_path, manifest


def test_study_input_validation_excludes_aliases_and_rejects_parquet_tamper(tmp_path: Path) -> None:
    index_path, model = _build_arm_index(tmp_path)
    inputs = validate_study_inputs(index_path, model)

    distinct = json.loads(index_path.read_text())["distinct_training_arms"]
    assert len(inputs["arms"]) == len(distinct) == 55
    assert len(json.loads(index_path.read_text())["arms"]) == 64
    assert all(
        "fixed_raw_p0025" not in arm["label"] or arm["metadata"]["assignment"] == "iid" for arm in inputs["arms"]
    )

    parquet = Path(inputs["arms"][0]["parquet"]["path"])
    parquet_bytes = parquet.read_bytes()
    parquet.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="parquet bytes differ"):
        validate_study_inputs(index_path, model)
    parquet.write_bytes(parquet_bytes)

    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    index["protocol"]["strict_dead_contract"]["strict_positive_counts_by_op"]["21"] = 1
    write_json_atomic(index_path, index)
    with pytest.raises(ValueError, match="strict-dead"):
        validate_study_inputs(index_path, model)
    index_path.write_bytes(index_bytes)

    (model / "model.safetensors").write_bytes(b"changed-model")
    with pytest.raises(ValueError, match="model frozen into the rollout bank"):
        validate_study_inputs(index_path, model)


def test_config_and_template_pin_the_scientific_training_contract(tmp_path: Path) -> None:
    index_path, model = _build_arm_index(tmp_path)
    arms = validate_study_inputs(index_path, model)["arms"]
    arm = next(arm for arm in arms if arm["label"] == "seed20260805_fixed_raw_p0100_g")
    source = SourceState(tmp_path, REPO_ROOT, {})
    launch_root = tmp_path / "launch"
    config_dict = launch_config(
        arm,
        launch_root=launch_root,
        source=source,
        base_model=model.resolve(),
        chat_template=(model / "chat_template.jinja").resolve(),
    )

    assert "optimization_dtype" not in config_dict["model"]
    assert "reduce_dtype" not in config_dict["model"]
    assert config_dict["scheduler"] == {"type": "constant"}
    assert config_dict["data"]["weight_column"] == "sft_weight"
    assert config_dict["deployment"] == {"type": "single_node", "num_gpus": 1, "gpus_per_node": 1}
    assert config_dict["max_steps"] == 2 * arm["rows"] // BATCH_SIZE == 160
    assert arm["readout_steps"] == [COMMON_STEPS, 160]
    assert config_dict["ckpt"]["keep_last"] == 20
    assert config_dict["ckpt"]["weights_only"] is True
    assert LAUNCH_TRAINING_CONTRACT["checkpoint_resumable"] is False
    assert "restart from step 0" in LAUNCH_TRAINING_CONTRACT["failure_policy"]
    assert "schedule:at_least_two_dataset_passes" in config_dict["wandb"]["tags"]

    config = SFTConfig.model_validate(config_dict)
    resolved = Path(config.output_dir) / "configs" / "sft.toml"
    write_config(config, resolved, exclude={"slurm", "dry_run", "clean_output_dir"})
    sbatch = Path(config.output_dir) / "sft.sbatch"
    write_slurm_script(config, resolved, sbatch)
    validate_resolved_config(
        resolved,
        arm=arm,
        output_dir=Path(config.output_dir),
        base_model=model.resolve(),
        chat_template=(model / "chat_template.jinja").resolve(),
    )
    validate_sbatch(sbatch, resolved_config=resolved, arm_label=arm["label"])
    assert "--exclusive" not in sbatch.read_text(encoding="utf-8")


def test_launch_manifest_covers_55_single_gpu_jobs_and_detects_config_tamper(tmp_path: Path) -> None:
    manifest_path, manifest = _materialized_launch(tmp_path)
    validated = validate_launch_manifest(manifest_path)
    commands = submission_commands(validated["manifest"])
    dry_run = submit(Namespace(launch_root=manifest_path.parent, dry_run=True, confirm_study_id=None))

    assert len(commands) == len(manifest["arms"]) == 55
    assert len(dry_run["commands"]) == 55
    assert all(command[-2] == "--parsable" for command in commands)
    assert all(
        "fixed_raw_p0025" not in arm["label"] or arm["metadata"]["assignment"] == "iid" for arm in manifest["arms"]
    )
    resolved = Path(manifest["arms"][0]["resolved_config"]["path"])
    resolved.write_text(resolved.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="resolved_config identity differs"):
        validate_launch_manifest(manifest_path)


def test_actual_submission_requires_exact_control_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", f"{CONTROL_TMUX_SOCKET},123,0")
    monkeypatch.setenv("TMUX_PANE", "%7")

    def display_message(command, **kwargs):
        assert command == [
            "tmux",
            "-S",
            CONTROL_TMUX_SOCKET,
            "display-message",
            "-p",
            "-t",
            "%7",
            "#{session_name}\t#{window_name}",
        ]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return type(
            "Result",
            (),
            {"stdout": f"{CONTROL_TMUX_SESSION}\t{CONTROL_TMUX_WINDOW}\n"},
        )()

    monkeypatch.setattr(materializer.subprocess, "run", display_message)
    assert require_control_tmux() == {
        "socket": CONTROL_TMUX_SOCKET,
        "session": CONTROL_TMUX_SESSION,
        "window": CONTROL_TMUX_WINDOW,
    }

    monkeypatch.setenv("TMUX", "/tmp/wrong.sock,123,0")
    with pytest.raises(ValueError, match="socket differs"):
        require_control_tmux()
