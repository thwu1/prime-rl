from __future__ import annotations

from pathlib import Path

import numpy as np
import probe_known_cost_checkpoint_kernel as probe
import pytest
import torch
from finalize_known_cost_checkpoint_kernel_attempt import parse_exit_code, terminal_state


def test_kernel_geometry_reconstructs_gram_and_localization_terms() -> None:
    gram = np.asarray(
        [
            [2.0, 0.2, 0.1, 0.1, 0.1, 0.1],
            [0.2, 2.5, 0.1, 0.1, 0.1, 0.1],
            [0.1, 0.1, 3.0, 0.2, 0.1, 0.1],
            [0.1, 0.1, 0.2, 3.5, 0.1, 0.1],
            [0.1, 0.1, 0.1, 0.1, 4.0, 0.2],
            [0.1, 0.1, 0.1, 0.1, 0.2, 4.5],
        ],
        dtype=np.float64,
    )
    norms = np.sqrt(np.diag(gram))
    kernel = gram / np.square(norms)[None, :]

    geometry = probe.kernel_geometry(kernel, norms)

    np.testing.assert_allclose(geometry["gram_matrix"], gram)
    uniform = np.ones(6)
    assert geometry["uniform_common_response_denominator"] == pytest.approx(uniform @ gram @ uniform / 6)
    delta = np.asarray([2.0, 2.0, -1.0, -1.0, -1.0, -1.0])
    contrast = np.asarray([0.5, 0.5, -0.25, -0.25, -0.25, -0.25])
    expected_numerator = float(contrast @ gram @ delta)
    block = geometry["blocks"][0]
    assert block["selected_minus_unselected_response_per_unit_p"] == pytest.approx(expected_numerator)
    assert block["localization_response_ratio"] == pytest.approx(
        expected_numerator / geometry["uniform_common_response_denominator"]
    )


def test_kernel_geometry_accepts_numerically_semidefinite_rank_one_gram() -> None:
    geometry = probe.kernel_geometry(np.ones((6, 6), dtype=np.float64), np.ones(6, dtype=np.float64))

    assert geometry["eigenvalues_ascending"][-1] == pytest.approx(6.0)
    assert min(geometry["eigenvalues_ascending"]) >= 0.0
    assert geometry["rank_one_frobenius_energy"] == pytest.approx(1.0)


def test_same_identity_except_path_requires_frozen_bytes(tmp_path: Path) -> None:
    frozen = tmp_path / "frozen.py"
    current = tmp_path / "current.py"
    frozen.write_bytes(b"same")
    current.write_bytes(b"same")
    left = {"path": str(frozen), "bytes": 4, "sha256": probe.file_sha256(frozen)}
    right = {"path": str(current), "bytes": 4, "sha256": probe.file_sha256(current)}

    probe._same_identity_except_path(left, right, "test")

    right["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bytes differ"):
        probe._same_identity_except_path(left, right, "test")


def test_combine_gradients_uses_exact_source_coefficients() -> None:
    gradients = [{"weight": torch.tensor([float(index), 1.0])} for index in range(6)]
    coefficients = np.asarray([2.0, 2.0, -1.0, -1.0, -1.0, -1.0])

    combined = probe.combine_gradients(gradients, coefficients)

    expected = sum(
        (gradient["weight"] * float(coefficient) for gradient, coefficient in zip(gradients, coefficients)),
        start=torch.zeros(2),
    )
    torch.testing.assert_close(combined["weight"], expected)


def test_terminal_scheduler_fields_fail_closed() -> None:
    assert terminal_state("COMPLETED+") == "COMPLETED"
    assert parse_exit_code("0:0") == (0, 0)

    with pytest.raises(ValueError, match="not terminal"):
        terminal_state("RUNNING")
    with pytest.raises(ValueError, match="ExitCode"):
        parse_exit_code("zero")
