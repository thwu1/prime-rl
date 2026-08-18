#!/usr/bin/env python3
"""Freeze and validate the verifier-defect withdrawal evaluation plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import audit_defect_withdrawal_training as withdrawal_audit
import figure3_eval
import materialize_defect_withdrawal_forks as withdrawal_forks
import prepare_rl_checkpoint_eval as legacy_eval
import source_provenance
import tomli_w

SCHEMA_VERSION = 1
AUTHORITY_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_authority"
PLAN_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_plan"
RECEIPT_ARTIFACT_TYPE = "rsci_defect_withdrawal_eval_attempt_receipt"
TRAINING_TERMINAL_ARTIFACT_TYPE = "rsci_defect_withdrawal_training_terminal_provenance"
STUDY_ID = "verifier-defect-withdrawal-v1"
AUTHORITY_NAME = "evaluation_authority.json"
PLAN_NAME = "plan.json"
TRAINING_TERMINAL_NAME = "training_terminal_provenance.json"
SELF_HASH_FIELD = "payload_without_self_hash_sha256"
SOURCE_STEP = 4_000
INTERMEDIATE_STEP = 4_250
FINAL_STEP = 4_375
OPERATIONS = tuple(range(11, 46))
EXAMPLES_PER_OPERATION = 200
REQUEST_SEED = 20_260_807
PROMPT_SEQUENCE_SHA256 = "42954277948a8d6455250d90a36fc4aab322c200717996920ade5995cc170299"
SEED_SEQUENCE_SHA256 = "5d1b58ef75f1160dee4694c7416575e2f20f968963c89c91df73746c38502c6b"
DATASET_BUNDLE_SHA256 = "369435fab4e74241e2112fe1c6fefc41d537febf1d0bbbdff40de1a1429809ce"
EXPECTED_SOURCE_INVENTORIES = {
    "p05": "74b8d8a440a0f7102c726fca20ae7352908bb76e86bcb7bc7812c833a9685d1e",
    "p00": "fdf998ea26ba6b77e99843a3058555054b231112a0484f3a5ea3b73c182ddb2c",
}
DEFAULT_EVAL_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-withdrawal-v1")
REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_TOKENIZER = withdrawal_forks.MODEL_PATH
SOURCE_ROOTS = {
    "p05": withdrawal_forks.ARMS["p05_on"].source_root,
    "p00": withdrawal_forks.ARMS["p00_clean"].source_root,
}
RUN_ROOTS = {name: withdrawal_forks.ARMS[name].output_root for name in ("p05_on", "p05_off", "p00_clean")}
IMPLEMENTATION_PATHS = {
    "planner": Path("user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py"),
    "runner": Path("user/tianhaowu/rsci/run_defect_withdrawal_eval_task.py"),
    "dispatcher": Path("user/tianhaowu/rsci/dispatch_defect_withdrawal.py"),
    "training_auditor": Path("user/tianhaowu/rsci/audit_defect_withdrawal_training.py"),
    "analyzer": Path("user/tianhaowu/rsci/analyze_defect_withdrawal_eval.py"),
    "evaluator": Path("user/tianhaowu/rsci/figure3_eval.py"),
    "scorer": Path("user/tianhaowu/rsci/solution_graph.py"),
    "dataset_router": Path("user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py"),
    "dataset_materializer": Path("user/tianhaowu/rsci/materialize_defect_withdrawal_dataset.py"),
    "fork_materializer": Path("user/tianhaowu/rsci/materialize_defect_withdrawal_forks.py"),
    "source_provenance": Path("user/tianhaowu/rsci/source_provenance.py"),
}
SUCCESS_ARTIFACT_NAMES = (
    "generation_manifest.json",
    "generation_completion.json",
    "generations.jsonl",
    "strict_results.jsonl",
    "metrics.json",
)
TERMINAL_RECEIPT_STATUSES = frozenset({"succeeded", "failed", "cancelled", "preempted"})
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RECEIPT_NAME_RE = re.compile(r"attempt_([0-9]{4})\.json")


@dataclass(frozen=True)
class ConfigArtifact:
    path: Path
    content: bytes

    def identity(self) -> dict[str, Any]:
        return bytes_identity(self.path, self.content)


@dataclass(frozen=True)
class PlanBuild:
    manifest: dict[str, Any]
    manifest_bytes: bytes
    plan_path: Path
    artifacts: tuple[ConfigArtifact, ...]


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_no_symlink_components(
    path: Path,
    label: str,
    *,
    allow_leaf_symlink: bool = False,
) -> Path:
    configured = path.expanduser().absolute()
    components = configured.parents if allow_leaf_symlink else (configured, *configured.parents)
    for component in components:
        if component.is_symlink():
            raise ValueError(f"{label} contains a symlink component: {component}")
    return configured


def file_identity(path: Path, *, allow_symlink: bool = False) -> dict[str, Any]:
    configured = _require_no_symlink_components(
        path,
        "File path",
        allow_leaf_symlink=allow_symlink,
    )
    if configured.is_symlink() and not allow_symlink:
        raise ValueError(f"File path is a symlink: {configured}")
    resolved = configured.resolve()
    if not resolved.is_file():
        raise ValueError(f"Expected a regular non-symlink file: {resolved}")
    identity = {
        "path": str(configured),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }
    if configured.is_symlink():
        identity.update(
            {
                "resolved_path": str(resolved),
                "symlink_target": os.readlink(configured),
            }
        )
    return identity


def bytes_identity(path: Path, content: bytes) -> dict[str, Any]:
    configured = _require_no_symlink_components(path, "Planned artifact path")
    return {
        "path": str(configured),
        "size_bytes": len(content),
        "sha256": bytes_sha256(content),
    }


def directory_identity(
    path: Path,
    *,
    require_stable: bool = True,
    allow_symlinks: bool = False,
) -> dict[str, Any]:
    configured = _require_no_symlink_components(path, "Checkpoint path")
    if not configured.is_absolute():
        raise ValueError(f"Checkpoint path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise ValueError(f"Expected a plain checkpoint directory: {resolved}")
    if require_stable and not (resolved / "STABLE").is_file():
        raise ValueError(f"Checkpoint has no STABLE marker: {resolved}")
    if not (resolved / "config.json").is_file():
        raise ValueError(f"Checkpoint has no config.json: {resolved}")
    paths = sorted(
        (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(resolved).as_posix(),
    )
    if not paths or not any(candidate.suffix == ".safetensors" for candidate in paths):
        raise ValueError(f"Checkpoint has no safetensors weights: {resolved}")
    inventory = []
    for candidate in paths:
        if candidate.is_symlink() and not allow_symlinks:
            raise ValueError(f"Checkpoint contains a symlink: {candidate}")
        record = {
            "path": candidate.relative_to(resolved).as_posix(),
            "size_bytes": candidate.stat().st_size,
            "sha256": file_sha256(candidate),
        }
        if candidate.is_symlink():
            record["symlink_target"] = os.readlink(candidate)
        inventory.append(record)
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(record["size_bytes"] for record in inventory),
        "inventory": inventory,
        "inventory_sha256": canonical_json_sha256(inventory),
    }


def _read_json(path: Path, *, require_read_only: bool = True) -> tuple[bytes, dict[str, Any]]:
    configured = _require_no_symlink_components(path, "JSON path")
    resolved = configured.resolve()
    if not resolved.is_file():
        raise ValueError(f"Expected a plain JSON file: {resolved}")
    if require_read_only and resolved.stat().st_mode & 0o222:
        raise ValueError(f"Immutable JSON artifact must be read-only: {resolved}")
    raw = resolved.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise ValueError(f"JSON artifact is not a canonical object: {resolved}")
    return raw, value


def _write_once(path: Path, content: bytes) -> None:
    configured = _require_no_symlink_components(path, "Immutable output path")
    resolved = configured.resolve()
    if resolved.exists():
        if not resolved.is_file() or resolved.read_bytes() != content:
            raise ValueError(f"Refusing to replace a different immutable artifact: {resolved}")
        if resolved.stat().st_mode & 0o222:
            raise ValueError(f"Immutable artifact must be read-only: {resolved}")
        return
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{resolved.name}.", suffix=".partial", dir=resolved.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)


def _with_self_hash(payload: dict[str, Any]) -> dict[str, Any]:
    if SELF_HASH_FIELD in payload:
        raise ValueError(f"Payload already contains {SELF_HASH_FIELD}")
    return {**payload, SELF_HASH_FIELD: canonical_json_sha256(payload)}


def _verify_self_hash(payload: dict[str, Any]) -> None:
    recorded = payload.get(SELF_HASH_FIELD)
    without = {key: value for key, value in payload.items() if key != SELF_HASH_FIELD}
    if recorded != canonical_json_sha256(without):
        raise ValueError("Artifact self hash differs")


def _implementation_identities(repo_root: Path = REPO_ROOT) -> dict[str, dict[str, Any]]:
    identities = {}
    for name, relative in IMPLEMENTATION_PATHS.items():
        identity = file_identity(repo_root / relative)
        identities[name] = {"repository_path": relative.as_posix(), **identity}
    return identities


def _source_snapshot_identity(source_run_dir: Path) -> dict[str, Any]:
    run_dir = source_run_dir.expanduser().resolve()
    state = source_provenance.verify_snapshot(run_dir, require_launch=False)
    manifest_path = run_dir / source_provenance.MANIFEST_NAME
    freeze_path = run_dir / source_provenance.FREEZE_NAME
    _, manifest = _read_json(manifest_path, require_read_only=False)
    return {
        "run_dir": str(run_dir),
        "snapshot_path": state["snapshot_path"],
        "parent_commit_sha": state["parent_commit_sha"],
        "source_tree_sha256": state["source_tree_sha256"],
        "manifest": file_identity(manifest_path),
        "environment_freeze": file_identity(freeze_path),
        "uv_lock_sha256": manifest["uv_lock_sha256"],
    }


def _evaluation_data_contract() -> dict[str, Any]:
    eval_config = {
        "data_sources": legacy_eval.DATA_SOURCES,
        "operations": list(OPERATIONS),
        "examples_per_operation": EXAMPLES_PER_OPERATION,
    }
    rows, hashes = figure3_eval.load_rows(eval_config)
    prompts = [
        {
            "op": int(row["op"]),
            "__idx": int(row["__idx"]),
            "id": str(row["id"]),
            "prompt_sha256": hashlib.sha256(figure3_eval.compose_prompt(row).encode()).hexdigest(),
        }
        for row in rows
    ]
    seeds = [figure3_eval.derive_request_seed(row, REQUEST_SEED, 0) for row in rows]
    if len(rows) != len(OPERATIONS) * EXAMPLES_PER_OPERATION or len(set(seeds)) != len(seeds):
        raise ValueError("Held-out prompt or request-seed cardinality changed")
    data_dirs = figure3_eval.data_dirs_by_operation(eval_config)
    datasets = [
        {
            "operation": operation,
            **file_identity(
                data_dirs[operation] / f"op{operation}-{EXAMPLES_PER_OPERATION}.jsonl",
                allow_symlink=True,
            ),
        }
        for operation in OPERATIONS
    ]
    dataset_bundle = canonical_json_sha256(
        [{"op": operation, "sha256": hashes[str(operation)]} for operation in OPERATIONS]
    )
    prompt_sequence = canonical_json_sha256(prompts)
    seed_sequence = canonical_json_sha256(seeds)
    expected = {
        "dataset_bundle_sha256": DATASET_BUNDLE_SHA256,
        "prompt_sequence_sha256": PROMPT_SEQUENCE_SHA256,
        "seed_sequence_sha256": SEED_SEQUENCE_SHA256,
    }
    observed = {
        "dataset_bundle_sha256": dataset_bundle,
        "prompt_sequence_sha256": prompt_sequence,
        "seed_sequence_sha256": seed_sequence,
    }
    if observed != expected:
        raise ValueError(f"Held-out evaluation identity changed: {observed}")
    return {
        "data_sources": legacy_eval.DATA_SOURCES,
        "operations": list(OPERATIONS),
        "examples_per_operation": EXAMPLES_PER_OPERATION,
        "prompt_count": len(rows),
        "datasets": datasets,
        **observed,
        "request_seed": REQUEST_SEED,
        "request_seed_derivation": "sha256-v1(base_seed,op,id,row_index,sample_rank)",
        "unique_request_seed_count": len(set(seeds)),
    }


def _readout_contract() -> dict[str, Any]:
    selectors = [
        {
            "readout_id": "p05_source_s4000",
            "source": "p05",
            "arm": None,
            "model_step": SOURCE_STEP,
            "path": str(SOURCE_ROOTS["p05"] / "weights" / f"step_{SOURCE_STEP}"),
        },
        {
            "readout_id": "p00_source_s4000",
            "source": "p00",
            "arm": None,
            "model_step": SOURCE_STEP,
            "path": str(SOURCE_ROOTS["p00"] / "weights" / f"step_{SOURCE_STEP}"),
        },
    ]
    for arm in ("p05_on", "p05_off", "p00_clean"):
        for step in (INTERMEDIATE_STEP, FINAL_STEP):
            selectors.append(
                {
                    "readout_id": f"{arm}_s{step}",
                    "source": "p05" if arm.startswith("p05") else "p00",
                    "arm": arm,
                    "model_step": step,
                    "path": str(RUN_ROOTS[arm] / "weights" / f"step_{step}"),
                }
            )
    source_aliases = [
        {
            "canonical_readout_id": "p05_source_s4000",
            "arm": arm,
            "path": str(RUN_ROOTS[arm] / "weights" / f"step_{SOURCE_STEP}"),
        }
        for arm in ("p05_on", "p05_off")
    ]
    source_aliases.append(
        {
            "canonical_readout_id": "p00_source_s4000",
            "arm": "p00_clean",
            "path": str(RUN_ROOTS["p00_clean"] / "weights" / f"step_{SOURCE_STEP}"),
        }
    )
    transitions = []
    source_by_arm = {
        "p05_on": "p05_source_s4000",
        "p05_off": "p05_source_s4000",
        "p00_clean": "p00_source_s4000",
    }
    for arm in ("p05_on", "p05_off", "p00_clean"):
        for step in (INTERMEDIATE_STEP, FINAL_STEP):
            transitions.append(
                {
                    "transition_id": f"{arm}_to_s{step}",
                    "arm": arm,
                    "analysis_clock": step,
                    "source_readout_id": source_by_arm[arm],
                    "endpoint_readout_id": f"{arm}_s{step}",
                    "trained": True,
                }
            )
    for step in (INTERMEDIATE_STEP, FINAL_STEP):
        transitions.append(
            {
                "transition_id": f"frozen_to_clock_{step}",
                "arm": "frozen",
                "analysis_clock": step,
                "source_readout_id": "p05_source_s4000",
                "endpoint_readout_id": "p05_source_s4000",
                "trained": False,
                "model_step": SOURCE_STEP,
            }
        )
    return {
        "checkpoint_selector_count": 8,
        "selectors": selectors,
        "source_copy_aliases": source_aliases,
        "transitions": transitions,
        "nearest_checkpoint_substitution_allowed": False,
    }


def _evaluation_config_contract() -> dict[str, Any]:
    return {
        "samples_per_prompt": 1,
        "pass_at": [1],
        "max_tokens": 2_048,
        "temperature": 0.7,
        "top_p": 1.0,
        "top_k": -1,
        "stop": ["</answer>"],
        "skip_special_tokens": False,
        "request_timeout_seconds": 3_600.0,
        "max_concurrent_prompts": 128,
        "max_retries": 2,
        "overwrite": False,
        "inference": {
            "gpu_memory_utilization": 0.8,
            "enable_prefix_caching": True,
            "enable_fp32_lm_head": True,
            "seed": 0,
            "max_model_len": 2_048,
            "tp": 1,
            "dp": 1,
            "gpus_per_node": 1,
            "max_num_seqs": 256,
        },
    }


def build_authority(eval_root: Path, source_run_dir: Path) -> dict[str, Any]:
    eval_root = eval_root.expanduser().resolve()
    source_run_dir = source_run_dir.expanduser().resolve()
    if eval_root != source_run_dir:
        raise ValueError("The canonical evaluation root must also own the control-plane source snapshot")
    source_models = {}
    for label, root in SOURCE_ROOTS.items():
        identity = directory_identity(root / "weights" / f"step_{SOURCE_STEP}")
        if identity["inventory_sha256"] != EXPECTED_SOURCE_INVENTORIES[label]:
            raise ValueError(f"{label} source checkpoint differs from the preregistered inventory")
        source_models[label] = identity
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": AUTHORITY_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "eval_root": str(eval_root),
        "source_control": _source_snapshot_identity(source_run_dir),
        "implementations": _implementation_identities(),
        "source_models": source_models,
        "tokenizer": directory_identity(
            BASE_TOKENIZER,
            require_stable=False,
            allow_symlinks=True,
        ),
        "evaluation_data": _evaluation_data_contract(),
        "evaluation_config": _evaluation_config_contract(),
        "readout_contract": _readout_contract(),
        "analysis_contract": {
            "categories": {
                "S": "perfect",
                "A": "answer_correct and not perfect",
                "W": "not answer_correct",
            },
            "assertion": "perfect implies answer_correct",
            "primary_band": [21, 40],
            "secondary_band": [41, 45],
            "other_reported_bands": [[11, 20], [11, 45]],
            "transition_estimand": "paired held-out prompt/request-seed response transition",
        },
    }
    return _with_self_hash(payload)


def materialize_authority(eval_root: Path, source_run_dir: Path) -> Path:
    eval_root = eval_root.expanduser().resolve()
    forbidden = [eval_root / name for name in ("plans", "results", "receipts", "submission")]
    if any(path.exists() for path in forbidden):
        raise ValueError("Evaluation authority must be materialized before any plan or result artifacts")
    authority = build_authority(eval_root, source_run_dir)
    path = eval_root / AUTHORITY_NAME
    _write_once(path, canonical_json_bytes(authority))
    return path


def validate_authority(path: Path) -> dict[str, Any]:
    raw, authority = _read_json(path)
    _verify_self_hash(authority)
    if (
        authority.get("schema_version") != SCHEMA_VERSION
        or authority.get("artifact_type") != AUTHORITY_ARTIFACT_TYPE
        or authority.get("study_id") != STUDY_ID
    ):
        raise ValueError("Evaluation authority schema or study identity differs")
    expected_path = Path(authority["eval_root"]) / AUTHORITY_NAME
    if path.expanduser().resolve() != expected_path.resolve():
        raise ValueError(f"Evaluation authority must be at {expected_path}")
    expected = build_authority(Path(authority["eval_root"]), Path(authority["source_control"]["run_dir"]))
    if raw != canonical_json_bytes(expected):
        raise ValueError("Evaluation authority differs from independently replayed state")
    return authority


def _validate_training_dispatch_chain(
    provenance: dict[str, Any],
    *,
    arm: str,
    scheduler: dict[str, Any],
) -> None:
    import dispatch_defect_withdrawal as withdrawal_dispatch

    authority_path = Path(provenance["dispatch_authority"]["path"])
    authority = withdrawal_dispatch.validate_training_authority(authority_path)
    arm_record = withdrawal_dispatch._arm_by_name(authority, arm)
    if (
        arm_record["run_root"] != provenance["run_root"]
        or arm_record["fork_manifest"] != provenance["fork_manifest"]
        or arm_record["source_provenance"] != provenance["source_provenance"]
        or arm_record["sbatch"] != provenance["rl_sbatch"]
    ):
        raise ValueError("Training terminal authority arm differs")
    intent, receipt = withdrawal_dispatch._validate_training_submission(
        Path(provenance["submission_receipt"]["path"]),
        authority_path=authority_path,
        authority=authority,
        arm=arm_record,
    )
    if (
        file_identity(Path(provenance["dispatch_intent"]["path"]))
        != provenance["dispatch_intent"]
        or intent["comment"] != scheduler["comment"]
        or receipt["job_id"] != scheduler["job_id"]
        or receipt["comment"] != scheduler["comment"]
    ):
        raise ValueError("Training terminal submission chain differs")
    allocation_path = Path(provenance["allocation_log"]["path"])
    allocation_raw = allocation_path.read_bytes()
    if (
        len(allocation_raw) != provenance["allocation_log"]["size_bytes"]
        or hashlib.sha256(allocation_raw).hexdigest() != provenance["allocation_log"]["sha256"]
    ):
        raise ValueError("Training terminal allocation log changed while read")
    allocation = withdrawal_dispatch._parse_terminal_allocation_stdout(
        allocation_raw.decode(),
        job_id=scheduler["job_id"],
    )
    for field in ("job_id", "comment", "job_name", "account", "qos", "state", "exit_code", "restart_count"):
        if allocation[field] != scheduler[field]:
            raise ValueError(f"Training terminal allocation {field} differs")


def _validate_training_terminal_provenance(
    *,
    arm: str,
    root: Path,
    fork_manifest: dict[str, Any],
    source_manifest: dict[str, Any],
    rl_sbatch: dict[str, Any],
    checkpoints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path = root / TRAINING_TERMINAL_NAME
    _, provenance = _read_json(path)
    _verify_self_hash(provenance)
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "arm",
        "run_root",
        "dispatch_authority",
        "dispatch_intent",
        "fork_manifest",
        "source_provenance",
        "rl_sbatch",
        "submission_receipt",
        "allocation_log",
        "training_ledger_audit",
        "scheduler",
        "checkpoints",
        SELF_HASH_FIELD,
    }
    if set(provenance) != expected_fields:
        raise ValueError(f"Training terminal provenance has the wrong schema: {path}")
    expected = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": TRAINING_TERMINAL_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "arm": arm,
        "run_root": str(root),
        "fork_manifest": fork_manifest,
        "source_provenance": source_manifest,
        "rl_sbatch": rl_sbatch,
        "checkpoints": checkpoints,
    }
    for field, value in expected.items():
        if provenance.get(field) != value:
            raise ValueError(f"Training terminal provenance field {field} differs: {path}")
    for field in (
        "dispatch_authority",
        "dispatch_intent",
        "submission_receipt",
        "allocation_log",
        "training_ledger_audit",
    ):
        identity = provenance.get(field)
        if not isinstance(identity, dict) or file_identity(Path(str(identity.get("path", "")))) != identity:
            raise ValueError(f"Training terminal provenance {field} changed: {path}")
    withdrawal_audit.validate_audit(
        Path(provenance["training_ledger_audit"]["path"]),
        arm=arm,
        run_root=root,
    )
    scheduler = provenance.get("scheduler")
    scheduler_fields = {
        "job_id",
        "comment",
        "job_name",
        "account",
        "qos",
        "state",
        "exit_code",
        "restart_count",
        "submitted_batch_script_sha256",
    }
    if not isinstance(scheduler, dict) or set(scheduler) != scheduler_fields:
        raise ValueError(f"Training terminal scheduler schema differs: {path}")
    spec = withdrawal_forks.ARMS[arm]
    if (
        not isinstance(scheduler["job_id"], str)
        or not scheduler["job_id"].isdigit()
        or not isinstance(scheduler["comment"], str)
        or SHA256_RE.fullmatch(scheduler["comment"]) is None
        or scheduler["job_name"] != spec.job_name
        or scheduler["account"] != "ram"
        or scheduler["qos"] != "h100_ram_high"
        or scheduler["state"] != "COMPLETED"
        or scheduler["exit_code"] != "0:0"
        or scheduler["restart_count"] != 0
        or scheduler["submitted_batch_script_sha256"] != rl_sbatch["sha256"]
    ):
        raise ValueError(f"Training terminal scheduler proof differs: {path}")
    _validate_training_dispatch_chain(provenance, arm=arm, scheduler=scheduler)
    return {
        "artifact": file_identity(path),
        "record": provenance,
    }


def _validate_run_evidence(arm: str, authority: dict[str, Any]) -> dict[str, Any]:
    spec = withdrawal_forks.ARMS[arm]
    root = spec.output_root.expanduser().resolve()
    manifest_path = root / withdrawal_forks.MANIFEST_NAME
    fork_state = withdrawal_forks.validate_materialized_fork(
        manifest_path,
        spec=spec,
        repo_root=REPO_ROOT,
        require_resolved_configs=True,
        require_pristine=False,
    )
    source_state = source_provenance.verify_snapshot(root, require_launch=True)
    checkpoint_identities = {
        str(step): directory_identity(root / "weights" / f"step_{step}")
        for step in (SOURCE_STEP, INTERMEDIATE_STEP, FINAL_STEP)
    }
    source_label = "p05" if arm.startswith("p05") else "p00"
    canonical_source = authority["source_models"][source_label]
    if checkpoint_identities[str(SOURCE_STEP)]["inventory"] != canonical_source["inventory"]:
        raise ValueError(f"{arm} staged source weights differ from canonical {source_label}")
    fork_manifest = file_identity(manifest_path)
    source_manifest = file_identity(root / source_provenance.MANIFEST_NAME)
    rl_sbatch = file_identity(root / "rl.sbatch")
    terminal = _validate_training_terminal_provenance(
        arm=arm,
        root=root,
        fork_manifest=fork_manifest,
        source_manifest=source_manifest,
        rl_sbatch=rl_sbatch,
        checkpoints=checkpoint_identities,
    )
    return {
        "arm": arm,
        "run_root": str(root),
        "fork_manifest": fork_manifest,
        "fork_validation": fork_state,
        "source_provenance": source_manifest,
        "source_snapshot": {
            key: source_state[key]
            for key in ("snapshot_path", "parent_commit_sha", "source_tree_sha256", "launch_artifacts_sha256")
        },
        "rl_sbatch": rl_sbatch,
        "checkpoints": checkpoint_identities,
        "training_terminal_provenance": terminal,
    }


def _deduplicate_models(
    selectors: list[dict[str, Any]],
    run_evidence: dict[str, dict[str, Any]],
    authority: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    identities = {}
    for selector in selectors:
        readout_id = selector["readout_id"]
        if selector["arm"] is None:
            identity = authority["source_models"][selector["source"]]
        else:
            identity = run_evidence[selector["arm"]]["checkpoints"][str(selector["model_step"])]
        if Path(identity["resolved_path"]) != Path(selector["path"]).resolve():
            raise ValueError(f"Readout {readout_id} resolved to a different checkpoint path")
        identities[readout_id] = identity

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inventory_by_hash: dict[str, list[dict[str, Any]]] = {}
    for selector in selectors:
        identity = identities[selector["readout_id"]]
        digest = identity["inventory_sha256"]
        previous = inventory_by_hash.setdefault(digest, identity["inventory"])
        if previous != identity["inventory"]:
            raise RuntimeError(f"Checkpoint inventory hash collision: {digest}")
        grouped[digest].append(selector)

    models = []
    readout_to_model = {}
    for selector in selectors:
        readout_id = selector["readout_id"]
        digest = identities[readout_id]["inventory_sha256"]
        if readout_id in readout_to_model:
            continue
        occurrences = grouped[digest]
        model_key = f"model_{digest[:20]}"
        model = {
            "model_key": model_key,
            "checkpoint": identities[readout_id],
            "occurrences": occurrences,
        }
        models.append(model)
        for occurrence in occurrences:
            readout_to_model[occurrence["readout_id"]] = model_key
    if set(readout_to_model) != {selector["readout_id"] for selector in selectors}:
        raise RuntimeError("Readout-to-model mapping is incomplete")
    return models, readout_to_model


def _inference_config(model_path: str, output_dir: Path, port: int, tokenizer_path: str) -> dict[str, Any]:
    return {
        "output_dir": str(output_dir.resolve()),
        "gpu_memory_utilization": 0.8,
        "enable_prefix_caching": True,
        "enable_fp32_lm_head": True,
        "api_server_count": 1,
        "data_parallel_size_local": 1,
        "seed": 0,
        "server": {"host": "0.0.0.0", "port": port, "liveness_timeout_seconds": 30.0},
        "model": {
            "name": model_path,
            "dtype": "auto",
            "max_model_len": 2_048,
            "enforce_eager": False,
            "trust_remote_code": False,
            "tool_call_parser": "None",
            "reasoning_parser": "None",
        },
        "parallel": {"tp": 1, "dp": 1},
        "deployment": {"type": "single_node", "gpus_per_node": 1},
        "vllm_extra": {"max_num_seqs": 256, "tokenizer": tokenizer_path},
        "log": {
            "level": "info",
            "vf_level": "info",
            "json_logging": False,
            "log_data": False,
            "interval": 10.0,
        },
    }


def _eval_config(
    *,
    inference_path: Path,
    evaluator_path: str,
    output_dir: Path,
    model_path: str,
    port: int,
) -> dict[str, Any]:
    return {
        "infer_config": str(inference_path.resolve()),
        "evaluator": evaluator_path,
        "eval": {
            "data_sources": legacy_eval.DATA_SOURCES,
            "operations": list(OPERATIONS),
            "examples_per_operation": EXAMPLES_PER_OPERATION,
            "output_dir": str(output_dir.resolve()),
            "model": model_path,
            "api_base_url": f"http://127.0.0.1:{port}/v1",
            "samples_per_prompt": 1,
            "pass_at": [1],
            "max_tokens": 2_048,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "request_seed": REQUEST_SEED,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_timeout_seconds": 3_600.0,
            "max_concurrent_prompts": 128,
            "max_retries": 2,
            "overwrite": False,
        },
    }


def _task_sbatch(
    *,
    task_id: str,
    job_name: str,
    plan_path: Path,
    source_run_dir: str,
    runner_path: str,
    log_dir: Path,
) -> bytes:
    content = f"""#!/usr/bin/env bash
#SBATCH --job-name={job_name}
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output={log_dir.resolve()}/{task_id}_attempt_%j.log

set -euo pipefail
ATTEMPT=${{1:?usage: task.sbatch ATTEMPT DISPATCH_INTENT}}
DISPATCH_INTENT=${{2:?usage: task.sbatch ATTEMPT DISPATCH_INTENT}}
SOURCE_RUN_DIR={source_run_dir!r}
source "$SOURCE_RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$SOURCE_RUN_DIR"
cd "$RSCI_SOURCE_SNAPSHOT"
exec uv run --no-sync {runner_path!r} {str(plan_path.resolve())!r} {task_id!r} \
  --attempt "$ATTEMPT" --dispatch-intent "$DISPATCH_INTENT"
"""
    return content.encode()


def build_task_bundle(
    *,
    model: dict[str, Any],
    task_index: int,
    plan_root: Path,
    authority: dict[str, Any],
) -> tuple[dict[str, Any], tuple[ConfigArtifact, ...]]:
    task_id = model["model_key"]
    config_root = plan_root / "configs" / task_id
    result_root = plan_root / "results" / task_id
    inference_path = config_root / "inference.toml"
    eval_path = config_root / "eval.toml"
    port = 22_000 + task_index
    model_path = model["checkpoint"]["resolved_path"]
    inference_content = tomli_w.dumps(
        _inference_config(
            model_path,
            result_root / "deployment",
            port,
            authority["tokenizer"]["resolved_path"],
        )
    ).encode()
    eval_content = tomli_w.dumps(
        _eval_config(
            inference_path=inference_path,
            evaluator_path=authority["implementations"]["evaluator"]["path"],
            output_dir=result_root,
            model_path=model_path,
            port=port,
        )
    ).encode()
    artifacts = (
        ConfigArtifact(inference_path, inference_content),
        ConfigArtifact(eval_path, eval_content),
    )
    config_identities = [artifact.identity() for artifact in artifacts]
    job_name = f"rsci-vdw-eval-{task_index:02d}-{model['checkpoint']['inventory_sha256'][:8]}"
    sbatch_path = config_root / "task.sbatch"
    sbatch_content = _task_sbatch(
        task_id=task_id,
        job_name=job_name,
        plan_path=plan_root / PLAN_NAME,
        source_run_dir=authority["source_control"]["run_dir"],
        runner_path=authority["implementations"]["runner"]["path"],
        log_dir=plan_root / "logs",
    )
    sbatch_artifact = ConfigArtifact(sbatch_path, sbatch_content)
    task = {
        "task_id": task_id,
        "task_index": task_index,
        "job_name": job_name,
        "model_path": model_path,
        "evaluator_path": authority["implementations"]["evaluator"]["path"],
        "checkpoint_inventory_sha256": model["checkpoint"]["inventory_sha256"],
        "transport_port": port,
        "result_root": str(result_root.resolve()),
        "receipt_dir": str((plan_root / "receipts" / task_id).resolve()),
        "inference_config": config_identities[0],
        "eval_config": config_identities[1],
        "config_bundle_sha256": canonical_json_sha256(config_identities),
        "sbatch": sbatch_artifact.identity(),
    }
    return task, (*artifacts, sbatch_artifact)


def _receipt_contract() -> dict[str, Any]:
    return {
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "path_template": "receipts/<task_id>/attempt_<four-digit-attempt>.json",
        "attempt_numbering": "contiguous from one",
        "terminal_statuses": sorted(TERMINAL_RECEIPT_STATUSES),
        "retry_rule": "each retry binds the exact preceding terminal receipt; nothing follows success",
        "dispatch_rule": "every receipt binds a protected task intent and the authority-pinned runner",
        "success_artifacts": list(SUCCESS_ARTIFACT_NAMES),
        "scheduler_terminal_requirement": (
            "runner success is necessary but not sufficient; durable protected scheduler-terminal provenance "
            "must be materialized before scientific analysis"
        ),
    }


def build_plan(authority_path: Path) -> PlanBuild:
    authority = validate_authority(authority_path)
    run_evidence = {arm: _validate_run_evidence(arm, authority) for arm in ("p05_on", "p05_off", "p00_clean")}
    selectors = authority["readout_contract"]["selectors"]
    models, readout_to_model = _deduplicate_models(selectors, run_evidence, authority)
    source_aliases = []
    for alias in authority["readout_contract"]["source_copy_aliases"]:
        canonical = next(
            model for model in models if model["model_key"] == readout_to_model[alias["canonical_readout_id"]]
        )
        observed = directory_identity(Path(alias["path"]))
        if observed["inventory"] != canonical["checkpoint"]["inventory"]:
            raise ValueError(f"Source-copy alias differs: {alias['path']}")
        source_aliases.append({**alias, "checkpoint": observed})
    semantic_core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": PLAN_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "authority": file_identity(authority_path),
        "source_control": authority["source_control"],
        "implementations": authority["implementations"],
        "evaluation_data": authority["evaluation_data"],
        "evaluation_config": authority["evaluation_config"],
        "analysis_contract": authority["analysis_contract"],
        "readout_contract": authority["readout_contract"],
        "run_evidence": run_evidence,
        "models": models,
        "readout_to_model": readout_to_model,
        "validated_source_copy_aliases": source_aliases,
        "receipt_contract": _receipt_contract(),
        "dispatch_gate": {
            "protected_submission_required": True,
            "durable_scheduler_terminal_provenance_required": True,
            "manual_sbatch_authorized": False,
        },
    }
    plan_id = canonical_json_sha256(semantic_core)
    plan_root = Path(authority["eval_root"]) / "plans" / plan_id
    tasks = []
    artifacts = []
    for index, model in enumerate(models):
        task, task_artifacts = build_task_bundle(
            model=model,
            task_index=index,
            plan_root=plan_root,
            authority=authority,
        )
        tasks.append(task)
        artifacts.extend(task_artifacts)
    task_by_model = {task["task_id"]: task["task_id"] for task in tasks}
    readouts = [
        {
            **selector,
            "model_key": readout_to_model[selector["readout_id"]],
            "task_id": task_by_model[readout_to_model[selector["readout_id"]]],
        }
        for selector in selectors
    ]
    manifest = {
        **semantic_core,
        "plan_id": plan_id,
        "plan_root": str(plan_root.resolve()),
        "plan_path": str((plan_root / PLAN_NAME).resolve()),
        "checkpoint_selector_count": len(readouts),
        "physical_task_count": len(tasks),
        "readouts": readouts,
        "tasks": tasks,
    }
    return PlanBuild(
        manifest=manifest,
        manifest_bytes=canonical_json_bytes(manifest),
        plan_path=plan_root / PLAN_NAME,
        artifacts=tuple(artifacts),
    )


def materialize_plan(authority_path: Path) -> Path:
    build = build_plan(authority_path)
    (build.plan_path.parent / "logs").mkdir(parents=True, exist_ok=True)
    for artifact in build.artifacts:
        _write_once(artifact.path, artifact.content)
    _write_once(build.plan_path, build.manifest_bytes)
    validate_plan(build.plan_path)
    return build.plan_path


def _validate_task_contract(plan: dict[str, Any], task: dict[str, Any]) -> None:
    model = next((model for model in plan["models"] if model["model_key"] == task["task_id"]), None)
    if model is None:
        raise ValueError(f"Task has no matching model: {task['task_id']}")
    observed_checkpoint = directory_identity(Path(task["model_path"]))
    if observed_checkpoint != model["checkpoint"]:
        raise ValueError(f"Task checkpoint changed: {task['task_id']}")
    for field in ("inference_config", "eval_config", "sbatch"):
        if file_identity(Path(task[field]["path"])) != task[field]:
            raise ValueError(f"Task {field} changed: {task['task_id']}")
        if Path(task[field]["path"]).stat().st_mode & 0o222:
            raise ValueError(f"Task {field} is not read-only: {task['task_id']}")
    config_identities = [task["inference_config"], task["eval_config"]]
    if canonical_json_sha256(config_identities) != task["config_bundle_sha256"]:
        raise ValueError(f"Task config bundle differs: {task['task_id']}")
    config = figure3_eval.load_config(Path(task["eval_config"]["path"]))
    eval_config = config["eval"]
    if config.get("evaluator") != task["evaluator_path"]:
        raise ValueError(f"Task evaluator path differs: {task['task_id']}")
    expected = {
        "model": task["model_path"],
        "output_dir": task["result_root"],
        "operations": list(OPERATIONS),
        "examples_per_operation": EXAMPLES_PER_OPERATION,
        "samples_per_prompt": 1,
        "pass_at": [1],
        "request_seed": REQUEST_SEED,
    }
    for field, value in expected.items():
        if eval_config.get(field) != value:
            raise ValueError(f"Task eval field {field} differs: {task['task_id']}")


def validate_completed_task(plan: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_task_contract(plan, task)
    config = figure3_eval.load_config(Path(task["eval_config"]["path"]))
    eval_config = config["eval"]
    output_dir = Path(task["result_root"])
    rows, hashes = figure3_eval.load_rows(eval_config)
    manifest = figure3_eval.build_generation_manifest(config, rows, hashes)
    figure3_eval.verify_generation_manifest(output_dir / figure3_eval.GENERATION_MANIFEST_NAME, manifest)
    generation_digest, generations = figure3_eval.canonical_generation_content(
        output_dir / "generations.jsonl", rows, 1
    )
    completion = figure3_eval.verify_generation_completion(output_dir, manifest, generation_digest, len(generations))
    strict_records = figure3_eval.verify_strict_results(output_dir / "strict_results.jsonl", rows, generations)
    if len(strict_records) != len(OPERATIONS) * EXAMPLES_PER_OPERATION:
        raise ValueError(f"Strict result count differs: {task['task_id']}")
    metrics = figure3_eval.load_json_object(output_dir / "metrics.json")
    expected_fields = {
        "model": task["model_path"],
        "dataset_sha256_by_op": hashes,
        "operations": list(OPERATIONS),
        "num_prompts": len(rows),
        "samples_per_prompt": 1,
        "num_generations": len(rows),
        "generation_provenance": {
            **completion,
            "generation_manifest": figure3_eval.GENERATION_MANIFEST_NAME,
            "generation_completion": figure3_eval.GENERATION_COMPLETION_NAME,
        },
    }
    for field, expected in expected_fields.items():
        if metrics.get(field) != expected:
            raise ValueError(f"Completed task metric {field} differs: {task['task_id']}")
    outcomes: dict[str, dict[tuple[str, int], dict[int, bool]]] = {
        "strict_graph": defaultdict(dict),
        "answer_only": defaultdict(dict),
    }
    for record in strict_records:
        key = (str(record["op"]), int(record["__idx"]))
        rank = int(record["sample_rank"])
        outcomes["strict_graph"][key][rank] = bool(record["perfect"])
        outcomes["answer_only"][key][rank] = bool(record["answer_correct"])
    for field, values in outcomes.items():
        expected = figure3_eval.aggregate_pass_at_k(values, [1])
        if metrics.get(field) != expected:
            raise ValueError(f"Completed task aggregate {field} differs: {task['task_id']}")
    implementation = figure3_eval.implementation_identity()
    scoring = {
        "implementation_sha256": implementation,
        "strict_results_sha256": file_sha256(output_dir / "strict_results.jsonl"),
        "num_results": len(strict_records),
    }
    if metrics.get("implementation_sha256") != implementation:
        raise ValueError(f"Completed task evaluator identity differs: {task['task_id']}")
    if metrics.get("strict_scoring_provenance") != scoring:
        raise ValueError(f"Completed task scorer provenance differs: {task['task_id']}")
    return strict_records


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo != UTC:
        raise ValueError(f"{label} must use UTC")
    return parsed


def validate_receipt_chain(plan: dict[str, Any], plan_sha256: str) -> dict[str, Any]:
    task_statuses = {}
    receipt_count = 0
    for task in plan["tasks"]:
        receipt_dir = Path(task["receipt_dir"])
        if not receipt_dir.exists():
            continue
        paths = sorted(receipt_dir.iterdir())
        attempts = []
        for path in paths:
            match = RECEIPT_NAME_RE.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unexpected receipt artifact: {path}")
            attempts.append((int(match.group(1)), path))
        if [attempt for attempt, _ in attempts] != list(range(1, len(attempts) + 1)):
            raise ValueError(f"Receipt attempts are not contiguous: {task['task_id']}")
        predecessor_sha256 = None
        predecessor_status = None
        for attempt, path in attempts:
            raw, receipt = _read_json(path)
            if predecessor_status == "succeeded":
                raise ValueError(f"Receipt follows a succeeded attempt: {path}")
            expected = {
                "schema_version": SCHEMA_VERSION,
                "artifact_type": RECEIPT_ARTIFACT_TYPE,
                "plan_id": plan["plan_id"],
                "plan_sha256": plan_sha256,
                "task_id": task["task_id"],
                "attempt": attempt,
                "predecessor_receipt_sha256": predecessor_sha256,
                "config_bundle_sha256": task["config_bundle_sha256"],
                "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
                "result_root": task["result_root"],
            }
            for field, value in expected.items():
                if receipt.get(field) != value:
                    raise ValueError(f"Receipt field {field} differs: {path}")
            status = receipt.get("status")
            if status not in TERMINAL_RECEIPT_STATUSES:
                raise ValueError(f"Receipt status is not terminal: {path}")
            if _parse_timestamp(receipt.get("finished_at"), f"{path} finished_at") < _parse_timestamp(
                receipt.get("started_at"), f"{path} started_at"
            ):
                raise ValueError(f"Receipt finishes before it starts: {path}")
            scheduler = receipt.get("scheduler")
            if not isinstance(scheduler, dict) or not str(scheduler.get("job_id", "")).isdigit():
                raise ValueError(f"Receipt scheduler identity is invalid: {path}")
            expected_scheduler = {
                "job_id",
                "array_task_id",
                "comment",
                "job_name",
                "account",
                "qos",
                "submitted_batch_script_sha256",
            }
            if (
                set(scheduler) != expected_scheduler
                or scheduler["array_task_id"] is not None
                or scheduler["job_name"] != task.get("job_name")
                or scheduler["account"] != "ram"
                or scheduler["qos"] != "h100_ram_high"
                or SHA256_RE.fullmatch(str(scheduler["comment"])) is None
                or scheduler["submitted_batch_script_sha256"] != task["sbatch"]["sha256"]
            ):
                raise ValueError(f"Receipt scheduler allocation differs: {path}")
            for field in ("dispatch_intent", "runner"):
                identity = receipt.get(field)
                if not isinstance(identity, dict) or file_identity(Path(str(identity.get("path", "")))) != identity:
                    raise ValueError(f"Receipt {field} identity changed: {path}")
            if receipt["runner"] != {
                key: plan["implementations"]["runner"][key] for key in ("path", "size_bytes", "sha256")
            }:
                raise ValueError(f"Receipt runner differs from the authority: {path}")
            import dispatch_defect_withdrawal as dispatch

            dispatch_intent = Path(receipt["dispatch_intent"]["path"])
            intent = dispatch.validate_eval_task_intent(
                dispatch_intent,
                plan=plan,
                task=task,
                attempt=attempt,
            )
            if (
                receipt["dispatch_intent"] != file_identity(dispatch_intent)
                or scheduler["comment"] != intent["comment"]
            ):
                raise ValueError(f"Receipt dispatch intent differs: {path}")
            expected_fields = {
                *expected,
                "dispatch_intent",
                "runner",
                "status",
                "started_at",
                "finished_at",
                "scheduler",
                "exit_code",
                "artifacts" if status == "succeeded" else "failure",
            }
            if set(receipt) != expected_fields:
                raise ValueError(f"Receipt schema differs: {path}")
            if status == "succeeded":
                if receipt.get("exit_code") != 0 or "failure" in receipt:
                    raise ValueError(f"Succeeded receipt has invalid exit state: {path}")
                artifacts = receipt.get("artifacts")
                if not isinstance(artifacts, dict) or set(artifacts) != set(SUCCESS_ARTIFACT_NAMES):
                    raise ValueError(f"Succeeded receipt artifact inventory differs: {path}")
                for name in SUCCESS_ARTIFACT_NAMES:
                    if artifacts[name] != file_identity(Path(task["result_root"]) / name):
                        raise ValueError(f"Succeeded receipt artifact changed: {path}/{name}")
                validate_completed_task(plan, task)
            elif (
                not isinstance(receipt.get("exit_code"), int)
                or receipt["exit_code"] == 0
                or not isinstance(receipt.get("failure"), str)
                or not receipt["failure"]
            ):
                raise ValueError(f"Unsuccessful receipt lacks failure evidence: {path}")
            predecessor_sha256 = bytes_sha256(raw)
            predecessor_status = status
            receipt_count += 1
        if predecessor_status is not None:
            task_statuses[task["task_id"]] = predecessor_status
    return {"receipt_count": receipt_count, "task_statuses": task_statuses}


def validate_plan(path: Path, *, require_complete: bool = False) -> dict[str, Any]:
    raw, plan = _read_json(path)
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("artifact_type") != PLAN_ARTIFACT_TYPE
        or plan.get("study_id") != STUDY_ID
    ):
        raise ValueError("Evaluation plan schema or study identity differs")
    if path.expanduser().resolve() != Path(plan["plan_path"]).resolve():
        raise ValueError("Evaluation plan path differs")
    authority_path = Path(plan["authority"]["path"])
    if file_identity(authority_path) != plan["authority"]:
        raise ValueError("Evaluation authority changed after plan materialization")
    expected = build_plan(authority_path)
    if raw != expected.manifest_bytes:
        raise ValueError("Evaluation plan differs from independently replayed state")
    for artifact in expected.artifacts:
        if file_identity(artifact.path) != artifact.identity():
            raise ValueError(f"Materialized task artifact changed: {artifact.path}")
        if artifact.path.stat().st_mode & 0o222:
            raise ValueError(f"Materialized task artifact is not read-only: {artifact.path}")
    for task in plan["tasks"]:
        _validate_task_contract(plan, task)
    receipts = validate_receipt_chain(plan, bytes_sha256(raw))
    if require_complete:
        expected_tasks = {task["task_id"] for task in plan["tasks"]}
        succeeded = {task_id for task_id, status in receipts["task_statuses"].items() if status == "succeeded"}
        if succeeded != expected_tasks:
            raise ValueError(f"Evaluation tasks are incomplete: {sorted(expected_tasks - succeeded)}")
    return {
        "plan": str(path.expanduser().resolve()),
        "plan_id": plan["plan_id"],
        "checkpoint_selector_count": plan["checkpoint_selector_count"],
        "physical_task_count": plan["physical_task_count"],
        **receipts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    authority = subparsers.add_parser("materialize-authority")
    authority.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    authority.add_argument("--source-run-dir", type=Path)
    validate_authority_parser = subparsers.add_parser("validate-authority")
    validate_authority_parser.add_argument("--authority", type=Path, required=True)
    plan = subparsers.add_parser("materialize-plan")
    plan.add_argument("--authority", type=Path, required=True)
    validate_plan_parser = subparsers.add_parser("validate-plan")
    validate_plan_parser.add_argument("--plan", type=Path, required=True)
    validate_plan_parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-authority":
        source_run_dir = args.source_run_dir or args.eval_root
        path = materialize_authority(args.eval_root, source_run_dir)
        result = {"authority": str(path)}
    elif args.command == "validate-authority":
        authority = validate_authority(args.authority)
        result = {
            "authority": str(args.authority.expanduser().resolve()),
            "payload_without_self_hash_sha256": authority[SELF_HASH_FIELD],
        }
    elif args.command == "materialize-plan":
        path = materialize_plan(args.authority)
        result = validate_plan(path)
    else:
        result = validate_plan(args.plan, require_complete=args.require_complete)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
