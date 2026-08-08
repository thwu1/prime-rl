#!/usr/bin/env python3
"""Measure fixed-pair tag-gradient geometry at a completed RL checkpoint."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import materialize_known_cost_training_completion as completion
import numpy as np
import probe_known_cost_tag_kernel as initial_probe

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_checkpoint_tag_kernel"
ALLOWED_CHECKPOINT_STEPS = (0, 375, 750, 1500)
PRODUCTION_RUN_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1"
)
ALLOWED_RUN_ARMS = {
    "g-p0125": "b20260808_g_p0125.toml",
    "t-p0125": "b20260808_t_p0125.toml",
    "g-p0375": "b20260808_g_p0375.toml",
    "t-p0375": "b20260808_t_p0375.toml",
}
SELECTED_TAG_BLOCKS = ((0, 1), (2, 3), (4, 5))
ARCHITECTURE_FIELDS = (
    "architectures",
    "model_type",
    "vocab_size",
    "hidden_size",
    "intermediate_size",
    "num_hidden_layers",
    "num_attention_heads",
    "num_key_value_heads",
    "max_position_embeddings",
    "tie_word_embeddings",
)
CONFIG_RELOCATION_FIELDS = ("_name_or_path",)
CONFIG_DISABLED_EQUIVALENCE_FIELDS = ("fp8",)
CONFIG_UNUSED_DENSE_PROBE_FIELDS = ("pad_token_id", "use_grouped_mm")
SYMMETRY_ATOL = 1e-10


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(value):
        raise ValueError(f"JSON is not canonical: {resolved}")
    return raw, value


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def source_identity(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    ).resolve()
    relative = resolved.relative_to(root)
    commit = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", relative.as_posix()],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not commit:
        raise ValueError(f"Implementation is not committed: {relative}")
    committed = subprocess.run(
        ["git", "show", f"{commit}:{relative.as_posix()}"],
        capture_output=True,
        check=True,
    ).stdout
    if committed != resolved.read_bytes():
        raise ValueError(f"Implementation differs from its last source commit: {relative}")
    return {
        "repository_path": relative.as_posix(),
        "last_source_commit": commit,
        **file_identity(resolved),
    }


def implementation_identity() -> dict[str, Any]:
    repository_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    ).resolve()
    return {
        "checkpoint_probe": source_identity(Path(__file__)),
        "initial_probe_dependency": source_identity(Path(initial_probe.__file__)),
        "completion_envelope_dependency": source_identity(Path(completion.__file__)),
        "pyproject": file_identity(repository_root / "pyproject.toml"),
        "uv_lock": file_identity(repository_root / "uv.lock"),
    }


def architecture_signature(path: Path) -> dict[str, Any]:
    config = read_json_object(path.expanduser().resolve() / "config.json")
    missing = [field for field in ARCHITECTURE_FIELDS if field not in config]
    if missing:
        raise ValueError(f"Model config lacks architecture fields {missing}: {path}")
    return {field: config[field] for field in ARCHITECTURE_FIELDS}


def normalized_config_signature(path: Path) -> dict[str, Any]:
    from transformers import AutoConfig

    resolved = path.expanduser().resolve()
    config = AutoConfig.from_pretrained(resolved, trust_remote_code=False).to_dict()
    if config.get("auto_map") not in (None, {}):
        raise ValueError(f"Remote model code is not permitted: {resolved}")
    ignored = {}
    for field in CONFIG_RELOCATION_FIELDS:
        ignored[field] = config.pop(field, None)
    for field in CONFIG_DISABLED_EQUIVALENCE_FIELDS:
        value = config.pop(field, None)
        if value not in (None, False):
            raise ValueError(f"Model config enables unsupported {field}={value!r}: {resolved}")
        ignored[field] = value
    model_type = config.get("model_type")
    if model_type != "qwen2" or config.get("num_experts") not in (None, 0):
        raise ValueError(f"Dense Qwen2 compatibility assumptions do not apply: {resolved}")
    for field in CONFIG_UNUSED_DENSE_PROBE_FIELDS:
        ignored[field] = config.pop(field, None)
    return {
        "normalized_config": config,
        "normalized_config_sha256": canonical_json_sha256(config),
        "ignored_fields": ignored,
        "ignored_field_rationale": {
            "_name_or_path": "filesystem provenance only",
            "fp8": "None and false both disable FP8",
            "pad_token_id": "probe supplies explicit attention masks and never reads padded labels",
            "use_grouped_mm": "unused by the asserted dense Qwen2 architecture",
        },
    }


def tokenizer_semantic_signature(path: Path) -> dict[str, Any]:
    from transformers import AutoTokenizer

    resolved = path.expanduser().resolve()
    tokenizer = AutoTokenizer.from_pretrained(resolved, trust_remote_code=False)
    vocabulary = sorted(tokenizer.get_vocab().items())
    used_specials = {
        name: {"token": getattr(tokenizer, name), "token_id": getattr(tokenizer, f"{name}_id")}
        for name in ("bos_token", "eos_token", "unk_token")
    }
    return {
        "vocabulary_size": len(vocabulary),
        "vocabulary_sha256": canonical_json_sha256(vocabulary),
        "chat_template_sha256": hashlib.sha256((tokenizer.chat_template or "").encode()).hexdigest(),
        "used_special_tokens": used_specials,
        "added_tokens_sha256": canonical_json_sha256(
            sorted((int(index), str(token)) for index, token in tokenizer.added_tokens_decoder.items())
        ),
        "pad_token_observed_not_used": {
            "token": tokenizer.pad_token,
            "token_id": tokenizer.pad_token_id,
        },
    }


def model_storage_dtypes(path: Path) -> list[str]:
    from safetensors import safe_open

    model_path = path.expanduser().resolve() / "model.safetensors"
    with safe_open(model_path, framework="pt", device="cpu") as handle:
        dtypes = sorted({handle.get_slice(key).get_dtype() for key in handle.keys()})
    if not dtypes:
        raise ValueError(f"Model safetensors has no tensors: {model_path}")
    return dtypes


def _same_identity_except_path(left: object, right: object, label: str) -> None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError(f"{label} identity is not an object")
    left_without_path = {key: value for key, value in left.items() if key != "path"}
    right_without_path = {key: value for key, value in right.items() if key != "path"}
    if left_without_path != right_without_path:
        raise ValueError(f"{label} bytes differ from the frozen source-probe identity")
    frozen_path = Path(str(left.get("path"))).expanduser().resolve()
    if file_identity(frozen_path) != {
        "path": str(frozen_path),
        "size_bytes": left.get("bytes", left.get("size_bytes")),
        "sha256": left.get("sha256"),
    }:
        raise ValueError(f"{label} frozen implementation identity is stale")


def validate_source_probe(source_probe_dir: Path) -> dict[str, Any]:
    source_probe_dir = source_probe_dir.expanduser().resolve()
    manifest_path = source_probe_dir / initial_probe.MANIFEST_NAME
    dataset_path = source_probe_dir / initial_probe.DATASET_NAME
    manifest = read_json_object(manifest_path)
    selection = manifest.get("selection")
    inputs = manifest.get("inputs")
    if not isinstance(selection, dict) or not isinstance(inputs, dict):
        raise ValueError("Source probe manifest lacks selection or input records")
    bank = inputs.get("bank")
    gold = inputs.get("gold_source")
    model = inputs.get("model")
    if not all(isinstance(value, dict) for value in (bank, gold, model)):
        raise ValueError("Source probe manifest input records are invalid")
    expected = initial_probe.build_probe_plan(
        bank_root=Path(str(bank["root"])),
        gold_source=Path(str(gold["path"])),
        model_path=Path(str(model["configured_name"])),
        output_dir=source_probe_dir,
        selection_seed=int(selection["seed"]),
        pairs_per_stratum=int(selection["pairs_per_operation_template_stratum"]),
    )
    if dataset_path.read_bytes() != expected.dataset_bytes:
        raise ValueError("Source probe dataset differs from full independent replay")

    normalized_expected = copy.deepcopy(expected.manifest)
    frozen_implementation = manifest.get("implementation")
    current_implementation = normalized_expected.get("implementation")
    _same_identity_except_path(frozen_implementation, current_implementation, "source probe")
    normalized_expected["implementation"]["path"] = frozen_implementation["path"]
    frozen_renderer = manifest.get("rendering", {}).get("renderer_implementation")
    current_renderer = normalized_expected.get("rendering", {}).get("renderer_implementation")
    _same_identity_except_path(frozen_renderer, current_renderer, "source probe renderer")
    normalized_expected["rendering"]["renderer_implementation"]["path"] = frozen_renderer["path"]
    expected_manifest_bytes = initial_probe.canonical_json_bytes(normalized_expected, indent=2)
    actual_manifest_bytes = manifest_path.read_bytes()
    if actual_manifest_bytes != expected_manifest_bytes:
        raise ValueError("Source probe manifest differs beyond its frozen snapshot paths")
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(actual_manifest_bytes).hexdigest(),
        "dataset_sha256": hashlib.sha256(expected.dataset_bytes).hexdigest(),
        "validation": "full replay with exact frozen implementation bytes and path-only relocation normalization",
    }


def load_source_sequences(source_probe_dir: Path, manifest: dict[str, Any]) -> dict[int, list[Any]]:
    model_path = Path(str(manifest["inputs"]["model"]["configured_name"]))
    _, _, current_rendering = initial_probe.renderer_state(model_path)
    _same_identity_except_path(
        manifest["rendering"]["renderer_implementation"],
        current_rendering["renderer_implementation"],
        "source probe renderer",
    )
    normalized_manifest = copy.deepcopy(manifest)
    normalized_manifest["rendering"] = current_rendering
    return initial_probe.load_probe_sequences(source_probe_dir, normalized_manifest)


def checkpoint_context(
    source_probe_dir: Path,
    checkpoint_path: Path,
    completion_receipt_path: Path | None,
    checkpoint_step: int,
) -> dict[str, Any]:
    if checkpoint_step not in ALLOWED_CHECKPOINT_STEPS:
        raise ValueError(f"checkpoint_step must be one of {ALLOWED_CHECKPOINT_STEPS}")
    source_probe_dir = source_probe_dir.expanduser().resolve()
    checkpoint_path = checkpoint_path.expanduser().resolve()

    source = validate_source_probe(source_probe_dir)
    source_manifest = source["manifest"]
    source_model_path = Path(source_manifest["inputs"]["model"]["configured_name"])
    source_signature = architecture_signature(source_model_path)
    checkpoint_signature = architecture_signature(checkpoint_path)
    if checkpoint_signature != source_signature:
        raise ValueError("Checkpoint architecture differs from the sealed source-probe model")
    source_config = normalized_config_signature(source_model_path)
    checkpoint_config = normalized_config_signature(checkpoint_path)
    if checkpoint_config["normalized_config"] != source_config["normalized_config"]:
        raise ValueError("Checkpoint forward-relevant config differs from the sealed source model")
    source_tokenizer = tokenizer_semantic_signature(source_model_path)
    checkpoint_tokenizer = tokenizer_semantic_signature(checkpoint_path)
    source_tokenizer_comparable = {
        key: value for key, value in source_tokenizer.items() if key != "pad_token_observed_not_used"
    }
    checkpoint_tokenizer_comparable = {
        key: value for key, value in checkpoint_tokenizer.items() if key != "pad_token_observed_not_used"
    }
    if checkpoint_tokenizer_comparable != source_tokenizer_comparable:
        raise ValueError("Checkpoint token-ID semantics differ from the sealed source tokenizer")

    source_record = {
        "directory": str(source_probe_dir),
        "manifest": file_identity(source_probe_dir / initial_probe.MANIFEST_NAME),
        "dataset": file_identity(source_probe_dir / initial_probe.DATASET_NAME),
        "pairs": source_manifest["selection"]["pairs"],
        "tagged_pairs": source_manifest["selection"]["tagged_pairs"],
        "objective": source_manifest["objective"],
        "source_model": source_manifest["inputs"]["model"],
        "validation": source["validation"],
    }

    if checkpoint_step == 0:
        if completion_receipt_path is not None:
            raise ValueError("Matched-precision step 0 must not use a completion receipt")
        if checkpoint_path != source_model_path.expanduser().resolve():
            raise ValueError("Matched-precision step 0 must use the sealed source model")
        source_storage_dtypes = model_storage_dtypes(checkpoint_path)
        if source_storage_dtypes != ["F32"]:
            raise ValueError(f"Matched-precision source storage must be F32, found {source_storage_dtypes}")
        return {
            "source_probe": source_record,
            "checkpoint": {
                "role": "matched_bfloat16_roundtrip_reference",
                "run_dir": None,
                "step": 0,
                "model": initial_probe.model_identity(checkpoint_path),
                "stable_marker": None,
                "architecture": checkpoint_signature,
                "normalized_config": checkpoint_config,
                "tokenizer_semantics": checkpoint_tokenizer,
                "source_storage_dtypes": source_storage_dtypes,
                "probe_weight_transform": (
                    "load source in float32, explicitly round floating parameters and buffers through "
                    "bfloat16, then probe in float32"
                ),
            },
            "completion_receipt": None,
            "implementation": implementation_identity(),
        }

    if checkpoint_path.name != f"step_{checkpoint_step}" or checkpoint_path.parent.name != "weights":
        raise ValueError("Checkpoint path does not match weights/step_<checkpoint_step>")
    stable_path = checkpoint_path / "STABLE"
    if not stable_path.is_file():
        raise FileNotFoundError(stable_path)
    run_dir = checkpoint_path.parent.parent
    if run_dir.parent.parent != PRODUCTION_RUN_ROOT or run_dir.name not in ALLOWED_RUN_ARMS:
        raise ValueError("Checkpoint run is outside the exact four-arm production smoke partition")
    expected_arm_filename = ALLOWED_RUN_ARMS[run_dir.name]
    if completion_receipt_path is None:
        raise ValueError("Trained checkpoints require an adjacent completion receipt")
    completion_receipt_path = completion_receipt_path.expanduser().resolve()
    if completion_receipt_path != run_dir / completion.RECEIPT_NAME:
        raise ValueError("Completion receipt is not adjacent to the checkpoint run")
    storage_dtypes = model_storage_dtypes(checkpoint_path)
    if storage_dtypes != ["BF16"]:
        raise ValueError(f"Trained checkpoint storage dtype must be BF16, found {storage_dtypes}")

    receipt_envelope = completion.validate_receipt_envelope(
        completion_receipt_path,
        supported_dispatch_stages={completion.STAGE1_DISPATCH_STAGE},
    )
    receipt = receipt_envelope["receipt"]
    receipt_inputs = receipt.get("inputs")
    if (
        not isinstance(receipt_inputs, dict)
        or Path(str(receipt_inputs.get("run_dir"))).resolve() != run_dir
        or receipt_inputs.get("arm_filename") != expected_arm_filename
        or Path(str(receipt_inputs.get("initial_launch_intent"))).resolve()
        != PRODUCTION_RUN_ROOT / "submission_intent.json"
    ):
        raise ValueError("Completion receipt belongs to another run")
    run_contract = receipt.get("run_contract")
    eligible_run = run_contract.get("eligible_run") if isinstance(run_contract, dict) else None
    if (
        not isinstance(run_contract, dict)
        or run_contract.get("arm_filename") != expected_arm_filename
        or Path(str(run_contract.get("run_dir"))).resolve() != run_dir
        or not isinstance(eligible_run, dict)
        or eligible_run.get("arm_filename") != expected_arm_filename
        or Path(str(eligible_run.get("output_dir"))).resolve() != run_dir
    ):
        raise ValueError("Completion receipt run contract differs from the exact smoke arm")
    claim_scope = receipt.get("claim_scope")
    expected_claim_scope = {
        "proves_protected_allocation_completed_with_exit_code_zero": True,
        "proves_bound_console_logs_and_final_stable_checkpoint_existed": True,
        "proves_scientific_replay_or_metric_completeness": False,
        "proves_normal_trainer_process_exit": False,
        "requires_or_claims_wandb_exit_record": False,
        "stage2_completion_supported_by_this_materializer": False,
    }
    if claim_scope != expected_claim_scope:
        raise ValueError("Completion receipt does not prove a successful protected allocation")

    return {
        "source_probe": source_record,
        "checkpoint": {
            "role": "trained_hf_readout_checkpoint",
            "arm_filename": expected_arm_filename,
            "run_dir": str(run_dir),
            "step": checkpoint_step,
            "model": initial_probe.model_identity(checkpoint_path),
            "stable_marker": file_identity(stable_path),
            "architecture": checkpoint_signature,
            "normalized_config": checkpoint_config,
            "tokenizer_semantics": checkpoint_tokenizer,
            "source_storage_dtypes": storage_dtypes,
            "probe_weight_transform": "load bfloat16 checkpoint weights into float32 compute",
        },
        "completion_receipt": receipt_envelope["identity"],
        "implementation": implementation_identity(),
    }


def kernel_geometry(kernel: np.ndarray, gradient_norms: np.ndarray) -> dict[str, Any]:
    if kernel.shape != (initial_probe.TAG_COUNT, initial_probe.TAG_COUNT):
        raise ValueError("Kernel matrix must be 6x6")
    if gradient_norms.shape != (initial_probe.TAG_COUNT,) or np.any(gradient_norms <= 0.0):
        raise ValueError("Gradient norms must contain six positive values")
    gram = kernel * np.square(gradient_norms)[None, :]
    symmetry_error = float(np.max(np.abs(gram - gram.T)))
    if symmetry_error > SYMMETRY_ATOL:
        raise ValueError(f"Reconstructed Gram matrix is not symmetric: {symmetry_error}")
    gram = (gram + gram.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    scale = max(float(eigenvalues[-1]), 1.0)
    if float(eigenvalues[0]) < -SYMMETRY_ATOL * scale:
        raise ValueError("Reconstructed Gram matrix is not positive semidefinite")
    eigenvalues = np.maximum(eigenvalues, 0.0)
    if eigenvalues[-1] <= 0.0:
        raise ValueError("Reconstructed Gram matrix has no positive direction")
    top = eigenvectors[:, -1]
    if float(np.sum(top)) < 0.0:
        top = -top
    uniform = np.ones(initial_probe.TAG_COUNT, dtype=np.float64)
    denominator = float(uniform @ gram @ uniform / initial_probe.TAG_COUNT)
    if denominator <= 0.0:
        raise ValueError("Uniform common response is not positive")
    blocks = []
    for selected_tuple in SELECTED_TAG_BLOCKS:
        selected = set(selected_tuple)
        delta = np.asarray([2.0 if tag in selected else -1.0 for tag in range(initial_probe.TAG_COUNT)])
        contrast = np.asarray([0.5 if tag in selected else -0.25 for tag in range(initial_probe.TAG_COUNT)])
        blocks.append(
            {
                "selected_tags": list(selected_tuple),
                "localization_response_ratio": float(contrast @ gram @ delta / denominator),
                "selected_minus_unselected_response_per_unit_p": float(contrast @ gram @ delta),
            }
        )
    return {
        "gram_matrix": gram.tolist(),
        "gram_symmetry_max_abs_error": symmetry_error,
        "eigenvalues_ascending": eigenvalues.tolist(),
        "lambda_second_to_lambda_top": float(eigenvalues[-2] / eigenvalues[-1]),
        "rank_one_frobenius_energy": float(eigenvalues[-1] ** 2 / np.dot(eigenvalues, eigenvalues)),
        "top_eigenvector_positive_sum": top.tolist(),
        "top_mode_weights": np.square(top).tolist(),
        "uniform_common_response_denominator": denominator,
        "blocks": blocks,
    }


def runtime_contract() -> dict[str, Any]:
    return {
        "dtype": "float32",
        "deterministic_algorithms": True,
        "step_size": initial_probe.DEFAULT_STEP_SIZE,
        "batch_size": initial_probe.DEFAULT_BATCH_SIZE,
        "recovery_atol": initial_probe.DEFAULT_RECOVERY_ATOL,
        "recovery_rtol": initial_probe.DEFAULT_RECOVERY_RTOL,
        "minimum_self_delta": initial_probe.DEFAULT_MINIMUM_SELF_DELTA,
        "max_self_linearity_relative_error": initial_probe.DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR,
    }


def load_model_strict(checkpoint_path: Path, checkpoint_step: int, device: Any) -> tuple[Any, dict[str, Any]]:
    import torch
    from transformers import AutoModelForCausalLM

    loaded = AutoModelForCausalLM.from_pretrained(
        str(checkpoint_path),
        dtype=torch.float32,
        attn_implementation="eager",
        trust_remote_code=False,
        output_loading_info=True,
    )
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise RuntimeError("Strict checkpoint loader did not return loading information")
    model, loading_info = loaded
    if not isinstance(loading_info, dict):
        raise RuntimeError("Strict checkpoint loading information is not an object")
    required_empty = ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
    normalized_loading_info = {}
    for key in required_empty:
        values = loading_info.get(key, [])
        if values:
            raise RuntimeError(f"Strict checkpoint load has {key}: {values}")
        normalized_loading_info[key] = []

    rounding = {
        "applied": checkpoint_step == 0,
        "floating_parameter_tensors": 0,
        "floating_buffer_tensors": 0,
        "transform": "none; checkpoint storage is already bfloat16" if checkpoint_step else "float32->bfloat16->float32",
    }
    if checkpoint_step == 0:
        with torch.no_grad():
            for parameter in model.parameters():
                if parameter.is_floating_point():
                    parameter.copy_(parameter.to(dtype=torch.bfloat16).to(dtype=torch.float32))
                    rounding["floating_parameter_tensors"] += 1
            for buffer in model.buffers():
                if buffer.is_floating_point():
                    buffer.copy_(buffer.to(dtype=torch.bfloat16).to(dtype=torch.float32))
                    rounding["floating_buffer_tensors"] += 1
    for name, tensor in (*model.named_parameters(), *model.named_buffers()):
        if tensor.is_floating_point() and tensor.dtype != torch.float32:
            raise RuntimeError(f"Probe tensor is not float32 after loading: {name}={tensor.dtype}")
    model = model.to(device=device, dtype=torch.float32)
    return model, {
        "model_class": f"{model.__class__.__module__}.{model.__class__.__qualname__}",
        "loading_info": normalized_loading_info,
        "rounding": rounding,
    }


def combine_gradients(gradients: list[dict[str, Any]], coefficients: np.ndarray) -> dict[str, Any]:
    import torch

    if len(gradients) != initial_probe.TAG_COUNT or coefficients.shape != (initial_probe.TAG_COUNT,):
        raise ValueError("Combined gradient requires six source gradients and coefficients")
    keys = gradients[0].keys()
    if any(gradient.keys() != keys for gradient in gradients[1:]):
        raise ValueError("Source gradients have different parameter support")
    return {
        name: torch.stack(
            [gradient[name] * float(coefficient) for gradient, coefficient in zip(gradients, coefficients, strict=True)]
        ).sum(dim=0)
        for name in keys
    }


def build_analysis(
    source_probe_dir: Path,
    checkpoint_path: Path,
    completion_receipt_path: Path | None,
    checkpoint_step: int,
) -> dict[str, Any]:
    import safetensors
    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("Checkpoint kernel probing requires a CUDA GPU")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.use_deterministic_algorithms(True)

    context = checkpoint_context(
        source_probe_dir,
        checkpoint_path,
        completion_receipt_path,
        checkpoint_step,
    )
    source_probe_dir = source_probe_dir.expanduser().resolve()
    checkpoint_path = checkpoint_path.expanduser().resolve()
    source_manifest = read_json_object(source_probe_dir / initial_probe.MANIFEST_NAME)
    sequences = load_source_sequences(source_probe_dir, source_manifest)

    device = torch.device("cuda:0")
    model, load_report = load_model_strict(checkpoint_path, checkpoint_step, device)
    model.eval()
    model.config.use_cache = False

    batch_size = initial_probe.DEFAULT_BATCH_SIZE
    recovery_atol = initial_probe.DEFAULT_RECOVERY_ATOL
    recovery_rtol = initial_probe.DEFAULT_RECOVERY_RTOL
    step_size = initial_probe.DEFAULT_STEP_SIZE
    baseline_objectives = initial_probe.objective_vector(
        model,
        sequences,
        batch_size=batch_size,
        device=device,
    )
    baseline_sentinels = [
        initial_probe.sentinel_label_logprobs(model, sequences[tag][0], device=device)
        for tag in range(initial_probe.TAG_COUNT)
    ]
    snapshot = initial_probe._parameter_snapshot(model)
    gradients = []
    source_objectives = []
    for source_tag in range(initial_probe.TAG_COUNT):
        model.zero_grad(set_to_none=True)
        objective = initial_probe.directional_objective(
            model,
            sequences[source_tag],
            batch_size=batch_size,
            device=device,
            backward=True,
        )
        if not math.isclose(objective, baseline_objectives[source_tag], abs_tol=recovery_atol, rel_tol=recovery_rtol):
            raise RuntimeError("Gradient and no-gradient objectives differ")
        source_objectives.append(objective)
        gradients.append(initial_probe._gradient_snapshot(model))
    analytic_kernel, analytic_self_terms = initial_probe._normalized_cross_gradient_kernel(gradients)

    responses = []
    source_normalized_responses = []
    for source_tag in range(initial_probe.TAG_COUNT):
        gradient_norm = math.sqrt(analytic_self_terms[source_tag])
        try:
            initial_probe._apply_gradient_ascent(model, gradients[source_tag], step_size)
            updated = initial_probe.objective_vector(model, sequences, batch_size=batch_size, device=device)
        finally:
            initial_probe._restore_parameters(model, snapshot)
        initial_probe._assert_parameters_exact(model, snapshot)
        recovered = initial_probe.objective_vector(model, sequences, batch_size=batch_size, device=device)
        recovered_sentinels = [
            initial_probe.sentinel_label_logprobs(model, sequences[tag][0], device=device)
            for tag in range(initial_probe.TAG_COUNT)
        ]
        initial_probe._assert_close_vectors(
            recovered,
            baseline_objectives,
            atol=recovery_atol,
            rtol=recovery_rtol,
            name=f"source_{source_tag}_objectives",
        )
        for tag in range(initial_probe.TAG_COUNT):
            initial_probe._assert_close_vectors(
                recovered_sentinels[tag],
                baseline_sentinels[tag],
                atol=recovery_atol,
                rtol=recovery_rtol,
                name=f"source_{source_tag}_tag_{tag}_sentinels",
            )
        deltas = [left - right for left, right in zip(updated, baseline_objectives, strict=True)]
        self_delta = deltas[source_tag]
        if self_delta <= initial_probe.DEFAULT_MINIMUM_SELF_DELTA or not math.isfinite(self_delta):
            raise RuntimeError(f"Source tag {source_tag} has invalid self response {self_delta}")
        normalized = [delta / self_delta for delta in deltas]
        predicted = step_size * gradient_norm**2
        linearity_error = abs(self_delta - predicted) / predicted
        if linearity_error > initial_probe.DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR:
            raise RuntimeError(f"Source tag {source_tag} finite update is outside the linearity contract")
        source_normalized_responses.append(normalized)
        responses.append(
            {
                "source_tag": source_tag,
                "source_objective": source_objectives[source_tag],
                "gradient_norm": gradient_norm,
                "updated_objectives": updated,
                "deltas": deltas,
                "self_delta": self_delta,
                "first_order_predicted_self_delta": predicted,
                "self_linearity_relative_error": linearity_error,
                "normalized_transfer": normalized,
                "parameters_restored_bit_exactly": True,
                "baseline_objectives_recovered": True,
                "baseline_sentinel_logits_recovered": True,
            }
        )
        model.zero_grad(set_to_none=True)

    finite_kernel = [
        [source_normalized_responses[source][target] for source in range(initial_probe.TAG_COUNT)]
        for target in range(initial_probe.TAG_COUNT)
    ]
    norms = np.asarray([response["gradient_norm"] for response in responses], dtype=np.float64)
    geometry = kernel_geometry(np.asarray(analytic_kernel, dtype=np.float64), norms)
    combined_finite_responses = []
    for block in geometry["blocks"]:
        selected = set(block["selected_tags"])
        delta = np.asarray([2.0 if tag in selected else -1.0 for tag in range(initial_probe.TAG_COUNT)])
        contrast = np.asarray([0.5 if tag in selected else -0.25 for tag in range(initial_probe.TAG_COUNT)])
        combined_gradient = combine_gradients(gradients, delta)
        try:
            initial_probe._apply_gradient_ascent(model, combined_gradient, step_size)
            updated = initial_probe.objective_vector(model, sequences, batch_size=batch_size, device=device)
        finally:
            initial_probe._restore_parameters(model, snapshot)
        initial_probe._assert_parameters_exact(model, snapshot)
        recovered = initial_probe.objective_vector(model, sequences, batch_size=batch_size, device=device)
        initial_probe._assert_close_vectors(
            recovered,
            baseline_objectives,
            atol=recovery_atol,
            rtol=recovery_rtol,
            name=f"combined_{block['selected_tags']}_objectives",
        )
        objective_deltas = np.asarray(updated, dtype=np.float64) - np.asarray(
            baseline_objectives,
            dtype=np.float64,
        )
        finite_slope = float(contrast @ objective_deltas / step_size)
        analytic_numerator = float(block["selected_minus_unselected_response_per_unit_p"])
        combined_finite_responses.append(
            {
                "selected_tags": block["selected_tags"],
                "delta_coefficients": delta.tolist(),
                "contrast_coefficients": contrast.tolist(),
                "updated_objectives": updated,
                "objective_deltas": objective_deltas.tolist(),
                "step_size_normalized_localization_slope": finite_slope,
                "analytic_localization_numerator": analytic_numerator,
                "finite_and_analytic_sign_agree": finite_slope * analytic_numerator > 0.0,
                "parameters_restored_bit_exactly": True,
                "baseline_objectives_recovered": True,
            }
        )
    context_after = checkpoint_context(
        source_probe_dir,
        checkpoint_path,
        completion_receipt_path,
        checkpoint_step,
    )
    if context_after != context:
        raise RuntimeError("Checkpoint-kernel inputs changed during GPU computation")
    analysis: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        **context,
        "runtime": {
            **runtime_contract(),
            "checkpoint_weight_mode": context["checkpoint"]["probe_weight_transform"],
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "safetensors_version": safetensors.__version__,
            "numpy_version": np.__version__,
            "python_version": platform.python_version(),
            "python_executable": str(Path(sys.executable).resolve()),
            "cuda_runtime_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),
            "cuda_device": torch.cuda.get_device_name(device),
            "model_load": load_report,
        },
        "baseline_objectives": baseline_objectives,
        "analytic_cross_gradient_kernel": analytic_kernel,
        "finite_step_kernel": finite_kernel,
        "responses": responses,
        "geometry": geometry,
        "combined_finite_responses": combined_finite_responses,
        "input_toctou": {
            "before": {
                key: context[key] for key in ("source_probe", "checkpoint", "completion_receipt", "implementation")
            },
            "after": {
                key: context_after[key]
                for key in ("source_probe", "checkpoint", "completion_receipt", "implementation")
            },
            "identical": True,
        },
        "scope": {
            "fixed_sealed_pairs_measured": True,
            "fresh_on_policy_pairs_measured": False,
            "unclipped_float32_gradient_ascent_measured": True,
            "combined_finite_localization_response_measured": True,
            "production_adam_dppo_update_measured": False,
            "causal_training_effect_identified": False,
            "phase_transition_identified": False,
            "hysteresis_identified": False,
        },
    }
    analysis["payload_without_self_hash_sha256"] = canonical_json_sha256(analysis)
    return analysis


def write_once(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(value)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if resolved.exists():
            if resolved.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace different analysis: {resolved}")
            return file_identity(resolved)
        descriptor, temporary_name = tempfile.mkstemp(dir=resolved.parent, prefix=f".{resolved.name}.")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, resolved)
        finally:
            temporary.unlink(missing_ok=True)
    return file_identity(resolved)


def _matrix(value: object, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (initial_probe.TAG_COUNT, initial_probe.TAG_COUNT) or not np.all(np.isfinite(matrix)):
        raise ValueError(f"{name} must be a finite 6x6 matrix")
    return matrix


def validate(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Checkpoint kernel analysis is writable")
    _, recorded = read_canonical_json(resolved)
    payload = dict(recorded)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError("Checkpoint kernel analysis self hash differs")
    if recorded.get("schema_version") != SCHEMA_VERSION or recorded.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Checkpoint kernel analysis has the wrong schema or artifact type")

    source = recorded.get("source_probe")
    checkpoint = recorded.get("checkpoint")
    receipt = recorded.get("completion_receipt")
    if not isinstance(source, dict) or not isinstance(checkpoint, dict):
        raise ValueError("Checkpoint kernel analysis lacks input records")
    checkpoint_step = int(checkpoint["step"])
    if checkpoint_step == 0:
        if receipt is not None:
            raise ValueError("Step-0 reference unexpectedly binds a completion receipt")
        receipt_path = None
    else:
        if not isinstance(receipt, dict):
            raise ValueError("Trained checkpoint kernel lacks a completion receipt")
        receipt_path = Path(str(receipt["path"]))
    context = checkpoint_context(
        Path(str(source["directory"])),
        Path(str(checkpoint["model"]["configured_name"])),
        receipt_path,
        checkpoint_step,
    )
    for key in ("source_probe", "checkpoint", "completion_receipt", "implementation"):
        if recorded.get(key) != context[key]:
            raise ValueError(f"Checkpoint kernel {key} identity changed")
    expected_runtime = runtime_contract()
    runtime = recorded.get("runtime")
    if not isinstance(runtime, dict) or {key: runtime.get(key) for key in expected_runtime} != expected_runtime:
        raise ValueError("Checkpoint kernel runtime differs from its fixed contract")
    expected_runtime_keys = {
        *expected_runtime,
        "checkpoint_weight_mode",
        "torch_version",
        "transformers_version",
        "safetensors_version",
        "numpy_version",
        "python_version",
        "python_executable",
        "cuda_runtime_version",
        "cudnn_version",
        "cuda_device",
        "model_load",
    }
    if set(runtime) != expected_runtime_keys:
        raise ValueError("Checkpoint kernel runtime contains missing or unexpected fields")
    for name in (
        "torch_version",
        "transformers_version",
        "safetensors_version",
        "numpy_version",
        "python_version",
        "python_executable",
        "cuda_runtime_version",
        "cuda_device",
    ):
        if not isinstance(runtime.get(name), str) or not runtime[name]:
            raise ValueError(f"Checkpoint kernel runtime {name} is invalid")
    if not isinstance(runtime.get("cudnn_version"), int) or runtime["cudnn_version"] < 1:
        raise ValueError("Checkpoint kernel cuDNN version is invalid")
    if runtime.get("checkpoint_weight_mode") != checkpoint.get("probe_weight_transform"):
        raise ValueError("Checkpoint kernel weight mode differs from its checkpoint context")
    load_report = runtime.get("model_load")
    if not isinstance(load_report, dict) or set(load_report) != {"model_class", "loading_info", "rounding"}:
        raise ValueError("Checkpoint kernel strict-load report is invalid")
    if load_report.get("loading_info") != {
        "missing_keys": [],
        "unexpected_keys": [],
        "mismatched_keys": [],
        "error_msgs": [],
    }:
        raise ValueError("Checkpoint kernel load was not strict")
    rounding = load_report.get("rounding")
    if not isinstance(rounding, dict) or rounding.get("applied") is not (checkpoint_step == 0):
        raise ValueError("Checkpoint kernel BF16-rounding report differs from its role")

    analytic = _matrix(recorded.get("analytic_cross_gradient_kernel"), "analytic kernel")
    finite = _matrix(recorded.get("finite_step_kernel"), "finite kernel")
    if not np.allclose(np.diag(analytic), 1.0, atol=1e-10, rtol=0.0):
        raise ValueError("Analytic kernel diagonal is not one")
    if not np.allclose(np.diag(finite), 1.0, atol=1e-10, rtol=0.0):
        raise ValueError("Finite kernel diagonal is not one")
    responses = recorded.get("responses")
    if not isinstance(responses, list) or len(responses) != initial_probe.TAG_COUNT:
        raise ValueError("Checkpoint kernel must contain six response records")
    baseline_objectives = np.asarray(recorded.get("baseline_objectives"), dtype=np.float64)
    if baseline_objectives.shape != (initial_probe.TAG_COUNT,) or not np.all(np.isfinite(baseline_objectives)):
        raise ValueError("Checkpoint kernel baseline objectives are invalid")
    for source_tag, response in enumerate(responses):
        if not isinstance(response, dict) or response.get("source_tag") != source_tag:
            raise ValueError("Checkpoint kernel response order differs")
        for flag in (
            "parameters_restored_bit_exactly",
            "baseline_objectives_recovered",
            "baseline_sentinel_logits_recovered",
        ):
            if response.get(flag) is not True:
                raise ValueError(f"Checkpoint kernel response did not satisfy {flag}")
        normalized = np.asarray(response.get("normalized_transfer"), dtype=np.float64)
        if normalized.shape != (initial_probe.TAG_COUNT,) or not np.all(np.isfinite(normalized)):
            raise ValueError("Checkpoint kernel normalized response is invalid")
        deltas = np.asarray(response.get("deltas"), dtype=np.float64)
        updated = np.asarray(response.get("updated_objectives"), dtype=np.float64)
        if deltas.shape != baseline_objectives.shape or not np.allclose(
            deltas,
            updated - baseline_objectives,
            atol=1e-12,
            rtol=1e-12,
        ):
            raise ValueError("Checkpoint kernel objective deltas differ")
        if not math.isclose(
            float(response.get("source_objective")),
            float(baseline_objectives[source_tag]),
            abs_tol=initial_probe.DEFAULT_RECOVERY_ATOL,
            rel_tol=initial_probe.DEFAULT_RECOVERY_RTOL,
        ):
            raise ValueError("Checkpoint kernel source objective differs from baseline")
        if not np.allclose(finite[:, source_tag], normalized, atol=1e-12, rtol=0.0):
            raise ValueError("Finite kernel differs from response records")
        self_delta = float(response.get("self_delta", 0.0))
        if self_delta <= initial_probe.DEFAULT_MINIMUM_SELF_DELTA:
            raise ValueError("Checkpoint kernel self response is too small")
        if not np.allclose(normalized, deltas / self_delta, atol=1e-12, rtol=1e-12):
            raise ValueError("Checkpoint kernel normalized response differs from objective deltas")
        if response.get("self_linearity_relative_error", math.inf) > initial_probe.DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR:
            raise ValueError("Checkpoint kernel finite response is outside its linearity contract")
        gradient_norm = float(response.get("gradient_norm"))
        expected_self_delta = initial_probe.DEFAULT_STEP_SIZE * gradient_norm**2
        if not math.isclose(
            float(response.get("first_order_predicted_self_delta")),
            expected_self_delta,
            abs_tol=1e-12,
            rel_tol=1e-12,
        ):
            raise ValueError("Checkpoint kernel first-order self response differs")
        expected_linearity_error = abs(self_delta - expected_self_delta) / expected_self_delta
        if not math.isclose(
            float(response.get("self_linearity_relative_error")),
            expected_linearity_error,
            abs_tol=1e-12,
            rel_tol=1e-12,
        ):
            raise ValueError("Checkpoint kernel linearity error differs")

    norms = np.asarray([response["gradient_norm"] for response in responses], dtype=np.float64)
    expected_geometry = kernel_geometry(analytic, norms)
    geometry = recorded.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Checkpoint kernel geometry is absent")
    if not np.allclose(
        np.asarray(geometry.get("gram_matrix"), dtype=np.float64),
        np.asarray(expected_geometry["gram_matrix"], dtype=np.float64),
        atol=1e-10,
        rtol=1e-12,
    ):
        raise ValueError("Checkpoint Gram matrix differs from analytic reconstruction")
    if not np.allclose(
        np.asarray(geometry.get("eigenvalues_ascending"), dtype=np.float64),
        np.asarray(expected_geometry["eigenvalues_ascending"], dtype=np.float64),
        atol=1e-10,
        rtol=1e-12,
    ):
        raise ValueError("Checkpoint Gram eigenvalues differ")
    for scalar in ("lambda_second_to_lambda_top", "rank_one_frobenius_energy"):
        if not math.isclose(float(geometry.get(scalar)), float(expected_geometry[scalar]), abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError(f"Checkpoint geometry {scalar} differs")
    if not math.isclose(
        float(geometry.get("uniform_common_response_denominator")),
        float(expected_geometry["uniform_common_response_denominator"]),
        abs_tol=1e-12,
        rel_tol=1e-12,
    ):
        raise ValueError("Checkpoint common-response denominator differs")
    if not math.isclose(
        float(geometry.get("gram_symmetry_max_abs_error")),
        float(expected_geometry["gram_symmetry_max_abs_error"]),
        abs_tol=1e-12,
        rel_tol=1e-12,
    ):
        raise ValueError("Checkpoint Gram symmetry error differs")
    for vector in ("top_eigenvector_positive_sum", "top_mode_weights"):
        if not np.allclose(
            np.asarray(geometry.get(vector), dtype=np.float64),
            np.asarray(expected_geometry[vector], dtype=np.float64),
            atol=1e-12,
            rtol=1e-12,
        ):
            raise ValueError(f"Checkpoint geometry {vector} differs")
    blocks = geometry.get("blocks")
    expected_blocks = expected_geometry["blocks"]
    if not isinstance(blocks, list) or len(blocks) != len(expected_blocks):
        raise ValueError("Checkpoint localization block inventory differs")
    for block, expected_block in zip(blocks, expected_blocks, strict=True):
        if not isinstance(block, dict) or block.get("selected_tags") != expected_block["selected_tags"]:
            raise ValueError("Checkpoint localization tag block differs")
        for scalar in ("localization_response_ratio", "selected_minus_unselected_response_per_unit_p"):
            if not math.isclose(
                float(block.get(scalar)),
                float(expected_block[scalar]),
                abs_tol=1e-12,
                rel_tol=1e-12,
            ):
                raise ValueError(f"Checkpoint localization {scalar} differs")
    combined = recorded.get("combined_finite_responses")
    if not isinstance(combined, list) or len(combined) != len(expected_blocks):
        raise ValueError("Checkpoint combined finite-response inventory differs")
    for response, block in zip(combined, expected_blocks, strict=True):
        if not isinstance(response, dict) or response.get("selected_tags") != block["selected_tags"]:
            raise ValueError("Checkpoint combined finite-response tag block differs")
        selected = set(block["selected_tags"])
        expected_delta = np.asarray(
            [2.0 if tag in selected else -1.0 for tag in range(initial_probe.TAG_COUNT)],
            dtype=np.float64,
        )
        expected_contrast = np.asarray(
            [0.5 if tag in selected else -0.25 for tag in range(initial_probe.TAG_COUNT)],
            dtype=np.float64,
        )
        if not np.array_equal(np.asarray(response.get("delta_coefficients")), expected_delta):
            raise ValueError("Checkpoint combined finite-response delta differs")
        if not np.array_equal(np.asarray(response.get("contrast_coefficients")), expected_contrast):
            raise ValueError("Checkpoint combined finite-response contrast differs")
        objective_deltas = np.asarray(response.get("objective_deltas"), dtype=np.float64)
        updated = np.asarray(response.get("updated_objectives"), dtype=np.float64)
        if objective_deltas.shape != baseline_objectives.shape or not np.allclose(
            objective_deltas,
            updated - baseline_objectives,
            atol=1e-12,
            rtol=1e-12,
        ):
            raise ValueError("Checkpoint combined finite-response objectives differ")
        expected_slope = float(expected_contrast @ objective_deltas / initial_probe.DEFAULT_STEP_SIZE)
        analytic_numerator = float(block["selected_minus_unselected_response_per_unit_p"])
        if not math.isclose(
            float(response.get("step_size_normalized_localization_slope")),
            expected_slope,
            abs_tol=1e-12,
            rel_tol=1e-12,
        ):
            raise ValueError("Checkpoint combined finite-response slope differs")
        if not math.isclose(
            float(response.get("analytic_localization_numerator")),
            analytic_numerator,
            abs_tol=1e-12,
            rel_tol=1e-12,
        ):
            raise ValueError("Checkpoint combined finite-response analytic numerator differs")
        if response.get("finite_and_analytic_sign_agree") is not (expected_slope * analytic_numerator > 0.0):
            raise ValueError("Checkpoint combined finite-response sign flag differs")
        if response.get("parameters_restored_bit_exactly") is not True or response.get(
            "baseline_objectives_recovered"
        ) is not True:
            raise ValueError("Checkpoint combined finite response did not restore the model")
    expected_toctou = {
        "before": {
            key: context[key] for key in ("source_probe", "checkpoint", "completion_receipt", "implementation")
        },
        "after": {
            key: context[key] for key in ("source_probe", "checkpoint", "completion_receipt", "implementation")
        },
        "identical": True,
    }
    if recorded.get("input_toctou") != expected_toctou:
        raise ValueError("Checkpoint kernel input TOCTOU record differs")
    scope = recorded.get("scope")
    expected_scope = {
        "fixed_sealed_pairs_measured": True,
        "fresh_on_policy_pairs_measured": False,
        "unclipped_float32_gradient_ascent_measured": True,
        "combined_finite_localization_response_measured": True,
        "production_adam_dppo_update_measured": False,
        "causal_training_effect_identified": False,
        "phase_transition_identified": False,
        "hysteresis_identified": False,
    }
    if scope != expected_scope:
        raise ValueError("Checkpoint kernel overstates its measurement scope")
    return file_identity(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--source-probe", type=Path, required=True)
    run.add_argument("--checkpoint", type=Path, required=True)
    run.add_argument("--completion-receipt", type=Path)
    run.add_argument("--checkpoint-step", type=int, choices=ALLOWED_CHECKPOINT_STEPS, required=True)
    run.add_argument("--output", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--analysis", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "run":
        if args.output.expanduser().resolve().exists():
            identity = validate(args.output)
            already_complete = True
        else:
            value = build_analysis(
                args.source_probe,
                args.checkpoint,
                args.completion_receipt,
                args.checkpoint_step,
            )
            identity = write_once(args.output, value)
            validate(args.output)
            already_complete = False
        summary = {"command": "run", "analysis": identity, "already_complete": already_complete}
    else:
        summary = {"command": "validate", "analysis": validate(args.analysis)}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
