#!/usr/bin/env python3
"""Analyze the spectral geometry of the known-cost tag kernel."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_kernel_spectrum"
TAG_COUNT = 6
ALPHA = 1.0 / 3.0
BEHAVIOR_TAX = 0.03
DOSES = (0.0075, 0.0125, 0.0225, 0.0375)
SELECTED_TAG_BLOCKS = ((0, 1), (2, 3), (4, 5))
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


def implementation_identity() -> dict[str, Any]:
    path = Path(__file__).resolve()
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    ).resolve()
    relative = path.relative_to(root)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    committed = subprocess.run(
        ["git", "show", f"{commit}:{relative.as_posix()}"],
        capture_output=True,
        check=True,
    ).stdout
    current = path.read_bytes()
    if current != committed:
        raise ValueError("Spectrum analyzer differs from its current Git commit")
    return {
        "commit_sha": commit,
        "repository_path": relative.as_posix(),
        **file_identity(path),
    }


def kernel_geometry(
    kernel: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    matrix = np.asarray(kernel.get("analytic_cross_gradient_kernel"), dtype=np.float64)
    responses = kernel.get("responses")
    if matrix.shape != (TAG_COUNT, TAG_COUNT):
        raise ValueError("Kernel matrix must be 6x6")
    if not isinstance(responses, list) or len(responses) != TAG_COUNT:
        raise ValueError("Kernel responses must cover six source tags")
    if [row.get("source_tag") for row in responses if isinstance(row, dict)] != list(range(TAG_COUNT)):
        raise ValueError("Kernel responses are not in canonical source-tag order")
    norms = np.asarray([row.get("gradient_norm") for row in responses], dtype=np.float64)
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(norms)) or np.any(norms <= 0.0):
        raise ValueError("Kernel matrix or gradient norms are non-finite")
    gram = matrix * np.square(norms)[None, :]
    symmetry_error = float(np.max(np.abs(gram - gram.T)))
    if symmetry_error > SYMMETRY_ATOL:
        raise ValueError(f"Reconstructed Gram matrix is not symmetric: {symmetry_error}")
    gram = (gram + gram.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    if np.any(eigenvalues <= 0.0):
        raise ValueError("Reconstructed Gram matrix is not positive definite")
    top_vector = eigenvectors[:, -1]
    if float(np.sum(top_vector)) < 0.0:
        top_vector = -top_vector
    return gram, norms, eigenvalues, top_vector, symmetry_error


def similar_symmetric_eigenvalues(
    gram_eigenvalues: np.ndarray,
    gram_eigenvectors: np.ndarray,
    payoff: np.ndarray,
) -> np.ndarray:
    square_root = (gram_eigenvectors * np.sqrt(gram_eigenvalues)[None, :]) @ gram_eigenvectors.T
    return np.linalg.eigvalsh(square_root @ np.diag(payoff) @ square_root)


def build_analysis(kernel_path: Path) -> dict[str, Any]:
    raw, kernel = read_canonical_json(kernel_path)
    if kernel.get("schema_version") != 2 or kernel.get("probe_id") != "known-cost-cross-tag-kernel-v2":
        raise ValueError("Input is not the sealed known-cost kernel-v2 result")
    gram, norms, eigenvalues, top_vector, symmetry_error = kernel_geometry(kernel)
    full_eigenvalues, full_eigenvectors = np.linalg.eigh(gram)
    top_weights = np.square(top_vector)
    uniform = np.ones(TAG_COUNT, dtype=np.float64)
    uniform_response = gram @ uniform
    unit_common_response = float(np.mean(uniform_response))
    rank_one_energy = float(eigenvalues[-1] ** 2 / np.dot(eigenvalues, eigenvalues))

    blocks = []
    for selected_tuple in SELECTED_TAG_BLOCKS:
        selected = np.asarray(selected_tuple, dtype=np.int64)
        unselected = np.asarray([index for index in range(TAG_COUNT) if index not in selected_tuple])
        delta = np.full(TAG_COUNT, -1.0, dtype=np.float64)
        delta[selected] = 2.0
        response = gram @ delta
        localization = float(np.mean(response[selected]) - np.mean(response[unselected]))
        selected_weight = float(np.sum(top_weights[selected]))
        common_gain = selected_weight / ALPHA
        blocks.append(
            {
                "selected_tags": list(selected_tuple),
                "unselected_tags": unselected.tolist(),
                "top_mode_selected_weight": selected_weight,
                "common_gain_per_marginal_p": common_gain,
                "rank_one_common_zero_crossing_p": BEHAVIOR_TAX / common_gain,
                "t_minus_g_payoff_per_unit_p": delta.tolist(),
                "t_minus_g_response_per_unit_p": response.tolist(),
                "selected_minus_unselected_response_per_unit_p": localization,
                "localization_to_uniform_common_response_ratio": localization / unit_common_response,
            }
        )

    dose_spectra = []
    for dose in DOSES:
        g_payoff = np.full(TAG_COUNT, dose - BEHAVIOR_TAX, dtype=np.float64)
        for block in blocks:
            selected = set(block["selected_tags"])
            t_payoff = np.asarray(
                [dose / ALPHA - BEHAVIOR_TAX if index in selected else -BEHAVIOR_TAX for index in range(TAG_COUNT)]
            )
            t_eigenvalues = similar_symmetric_eigenvalues(full_eigenvalues, full_eigenvectors, t_payoff)
            dose_spectra.append(
                {
                    "dose": dose,
                    "selected_tags": block["selected_tags"],
                    "g_payoff": g_payoff.tolist(),
                    "g_eigenvalues": np.linalg.eigvalsh(gram * (dose - BEHAVIOR_TAX)).tolist(),
                    "g_spectral_abscissa": float(np.max(np.linalg.eigvalsh(gram * (dose - BEHAVIOR_TAX)))),
                    "g_rank_one_common_rate": float(eigenvalues[-1] * (dose - BEHAVIOR_TAX)),
                    "t_payoff": t_payoff.tolist(),
                    "t_eigenvalues": t_eigenvalues.tolist(),
                    "t_positive_mode_count": int(np.count_nonzero(t_eigenvalues > 1e-12)),
                    "t_spectral_abscissa": float(t_eigenvalues[-1]),
                    "t_spectral_abscissa_to_unit_common_eigenvalue": float(t_eigenvalues[-1] / eigenvalues[-1]),
                    "t_rank_one_common_rate": float(
                        eigenvalues[-1] * (block["common_gain_per_marginal_p"] * dose - BEHAVIOR_TAX)
                    ),
                }
            )

    analysis: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "kernel": {
            "path": str(kernel_path.expanduser().resolve()),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "implementation": implementation_identity(),
        "definitions": {
            "kernel_orientation": "K[target,source] = dot(g_target,g_source) / dot(g_source,g_source)",
            "gram_reconstruction": "G[target,source] = K[target,source] * gradient_norm[source]^2",
            "rank_one_energy": "lambda_max(G)^2 / sum_i lambda_i(G)^2",
            "localization_ratio": "mean_selected(G delta)-mean_unselected(G delta), divided by mean(G 1)",
            "t_payoff": "selected=p/alpha-c0; unselected=-c0",
        },
        "calibration": {
            "alpha": ALPHA,
            "behavior_tax_c0": BEHAVIOR_TAX,
            "doses": list(DOSES),
            "selected_tag_blocks": [list(block) for block in SELECTED_TAG_BLOCKS],
        },
        "geometry": {
            "gradient_norms": norms.tolist(),
            "gram_matrix": gram.tolist(),
            "gram_symmetry_max_abs_error": symmetry_error,
            "eigenvalues_ascending": eigenvalues.tolist(),
            "lambda_second_to_lambda_top": float(eigenvalues[-2] / eigenvalues[-1]),
            "rank_one_frobenius_energy": rank_one_energy,
            "top_eigenvector_positive_sum": top_vector.tolist(),
            "top_mode_weights": top_weights.tolist(),
            "uniform_unit_payoff_response": uniform_response.tolist(),
            "uniform_unit_payoff_mean_response": unit_common_response,
        },
        "blocks": blocks,
        "dose_spectra": dose_spectra,
        "interpretation": {
            "initial_tag_geometry_effectively_rank_one": True,
            "naive_selected_tag_zero_crossing_p": ALPHA * BEHAVIOR_TAX,
            "fast_common_mode_crossing_near_g_crossing": True,
            "material_early_localization_requires_unmeasured_nonlinearity_or_geometry_change": True,
            "causal_training_effect_identified": False,
            "phase_transition_identified": False,
            "hysteresis_identified": False,
        },
        "checks": {
            "kernel_is_canonical": True,
            "gram_reconstruction_is_symmetric": True,
            "gram_is_positive_definite": True,
            "all_spectra_are_finite": True,
            "analysis_is_descriptive_not_causal": True,
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


def validate(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Spectrum analysis is writable")
    raw, recorded = read_canonical_json(resolved)
    payload = dict(recorded)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError("Spectrum analysis self hash differs")
    kernel = recorded.get("kernel")
    if not isinstance(kernel, dict):
        raise ValueError("Spectrum analysis has no kernel identity")
    expected = build_analysis(Path(str(kernel.get("path"))))
    if raw != canonical_json_bytes(expected):
        raise ValueError("Spectrum analysis differs from deterministic replay")
    return file_identity(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--kernel", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--analysis", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "analyze":
        identity = write_once(args.output, build_analysis(args.kernel))
    else:
        identity = validate(args.analysis)
    print(json.dumps({"command": args.command, "analysis": identity}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
