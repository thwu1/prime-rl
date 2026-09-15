"""
Tests for NFIQ2-compatible quality feature extraction pipeline.

Verifies that the implementation produces correct OCL and FDA quality
measures conformant with the NIST NFIQ2 reference C++ implementation.

"""
import json
import os
import math
import pytest
import numpy as np


@pytest.fixture(scope="module")
def output():
    """Load the candidate's output JSON."""
    path = "/app/output.json"
    assert os.path.isfile(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


# ── Structural tests ──────────────────────────────────────────────────────

class TestStructure:
    def test_has_all_images(self, output):
        for key in ("uniform", "diagonal", "degraded"):
            assert key in output, f"Missing image key: {key}"

    def test_has_all_fields(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            entry = output[img]
            for field in ("mu", "mmb", "ocl", "fda"):
                assert field in entry, f"{img}: missing '{field}'"

    def test_ocl_structure(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            ocl = output[img]["ocl"]
            assert "histogram" in ocl
            assert "mean" in ocl
            assert "stddev" in ocl
            assert len(ocl["histogram"]) == 10, f"{img}: OCL histogram must have 10 bins"

    def test_fda_structure(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            fda = output[img]["fda"]
            assert "histogram" in fda
            assert "mean" in fda
            assert "stddev" in fda
            assert len(fda["histogram"]) == 10, f"{img}: FDA histogram must have 10 bins"

    def test_histogram_bins_nonneg(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            for measure in ("ocl", "fda"):
                hist = output[img][measure]["histogram"]
                for i, v in enumerate(hist):
                    assert v >= 0, f"{img}/{measure} bin {i} is negative: {v}"


# ── Uniform image (horizontal ridges) ────────────────────────────────────

class TestUniform:
    """Horizontal sinusoidal ridges: known analytically pure orientation."""

    def test_mu(self, output):
        mu = output["uniform"]["mu"]
        assert abs(mu - 128.0) < 0.5, f"Uniform Mu should be ~128.0, got {mu}"

    def test_mmb(self, output):
        mmb = output["uniform"]["mmb"]
        assert abs(mmb - 128.0) < 0.5, f"Uniform MMB should be ~128.0, got {mmb}"

    def test_ocl_mean_near_one(self, output):
        """Horizontal ridges have gx=0 => OCL=1.0 for every block."""
        m = output["uniform"]["ocl"]["mean"]
        assert abs(m - 1.0) < 0.001, f"Uniform OCL mean should be 1.0, got {m}"

    def test_ocl_stddev_near_zero(self, output):
        s = output["uniform"]["ocl"]["stddev"]
        assert s < 0.001, f"Uniform OCL stddev should be ~0.0, got {s}"

    def test_ocl_histogram_sum(self, output):
        hist = output["uniform"]["ocl"]["histogram"]
        total = sum(hist)
        assert total == 100, f"Uniform OCL histogram sum should be 100 (10x10 grid), got {total}"

    def test_ocl_all_in_top_bin(self, output):
        """All OCL values >= 0.9 should land in bin 9."""
        hist = output["uniform"]["ocl"]["histogram"]
        assert hist[9] == 100, (
            f"All 100 OCL values should be >= 0.9 (bin 9), got bin9={hist[9]}"
        )

    def test_fda_mean_high(self, output):
        """Clean horizontal ridges should have high FDA periodicity scores.
        Requires correct rotation alignment and slanted block geometry."""
        m = output["uniform"]["fda"]["mean"]
        assert m > 0.85, (
            f"Uniform FDA mean should be > 0.85 for clean ridges, got {m}"
        )

    def test_fda_mean_from_full_formula(self, output):
        """FDA scores must come from the full DFT scoring formula, not
        from the mLoc==0 edge case that returns exactly 1.0.

        With correct 32-row crop (SBW=32), the row-mean profile has 32
        elements with 2 ridge periods. The DFT peak is at index 2
        (DC-excluded index 1), so the full formula applies, giving
        scores near but not exactly 1.0.

        With an incorrect 16-row crop, the profile has 16 elements with
        1 period. DFT peak at index 1 (DC-excluded index 0) triggers
        the edge case returning exactly 1.0 for every block."""
        m = output["uniform"]["fda"]["mean"]
        assert m < 0.999, (
            f"Uniform FDA mean should be < 0.999 (full scoring formula, "
            f"not edge-case 1.0). Got {m}"
        )

    def test_fda_histogram_sum(self, output):
        hist = output["uniform"]["fda"]["histogram"]
        total = sum(hist)
        assert total == 81, f"Uniform FDA histogram sum should be 81 (9x9 grid), got {total}"

    def test_fda_top_bins_dominate(self, output):
        """Most FDA values should be in the higher bins for clean ridges."""
        hist = output["uniform"]["fda"]["histogram"]
        top_half = sum(hist[5:])
        assert top_half > 60, (
            f"Expected most FDA values in upper bins for clean ridges, "
            f"got {top_half}/81 in bins 5-9"
        )


# ── Diagonal image (45-degree ridges) ────────────────────────────────────

class TestDiagonal:
    """45-degree diagonal sinusoidal ridges: single dominant orientation."""

    def test_mu(self, output):
        mu = output["diagonal"]["mu"]
        assert abs(mu - 128.0) < 1.0, f"Diagonal Mu should be ~128.0, got {mu}"

    def test_ocl_mean_high(self, output):
        """Diagonal ridges have a single dominant orientation => OCL near 1.0.
        Requires correct eigenvalue computation with c^2 in discriminant."""
        m = output["diagonal"]["ocl"]["mean"]
        assert m > 0.95, (
            f"Diagonal OCL mean should be > 0.95 (single orientation), got {m}"
        )

    def test_ocl_histogram_sum(self, output):
        hist = output["diagonal"]["ocl"]["histogram"]
        total = sum(hist)
        assert total == 100, f"Diagonal OCL histogram sum should be 100, got {total}"

    def test_ocl_mostly_top_bin(self, output):
        """Most blocks should have OCL >= 0.9 for clean diagonal ridges."""
        hist = output["diagonal"]["ocl"]["histogram"]
        assert hist[9] > 80, (
            f"Expected most diagonal OCL values in top bin, got bin9={hist[9]}/100"
        )

    def test_fda_mean_high_with_rotation(self, output):
        """Diagonal ridges should produce high FDA scores when correctly
        rotated. The rotation must include the pi/2 offset so that
        the block's orientation aligns ridges for DFT profiling."""
        m = output["diagonal"]["fda"]["mean"]
        assert m > 0.9, (
            f"Diagonal FDA mean should be > 0.9 with correct rotation, got {m}"
        )

    def test_fda_histogram_sum(self, output):
        hist = output["diagonal"]["fda"]["histogram"]
        total = sum(hist)
        assert total == 81, f"Diagonal FDA histogram sum should be 81, got {total}"


# ── Degraded image (mixed orientations + noise) ─────────────────────────

class TestDegraded:
    """Top-half horizontal, bottom-half vertical ridges with Gaussian noise."""

    def test_mu_approx(self, output):
        mu = output["degraded"]["mu"]
        assert abs(mu - 128.0) < 8.0, f"Degraded Mu should be ~128, got {mu}"

    def test_ocl_mean_reduced(self, output):
        """Noise and mixed orientations reduce OCL from 1.0."""
        m = output["degraded"]["ocl"]["mean"]
        assert m < 0.98, f"Degraded OCL mean should be < 0.98 (noise present), got {m}"
        assert m > 0.2, f"Degraded OCL mean should be > 0.2 (structure present), got {m}"

    def test_ocl_histogram_sum(self, output):
        hist = output["degraded"]["ocl"]["histogram"]
        total = sum(hist)
        assert total == 100, f"Degraded OCL histogram sum should be 100, got {total}"

    def test_fda_histogram_sum(self, output):
        hist = output["degraded"]["fda"]["histogram"]
        total = sum(hist)
        assert total == 81, f"Degraded FDA histogram sum should be 81, got {total}"

    def test_fda_mean_reasonable(self, output):
        """Degraded image should have moderate FDA scores — not as high as
        clean ridges but still positive with proper rotation alignment."""
        m = output["degraded"]["fda"]["mean"]
        assert m > 0.6, (
            f"Degraded FDA mean should be > 0.6 (moderate periodicity), got {m}"
        )


# ── Cross-image consistency ──────────────────────────────────────────────

class TestCrossImage:
    """Comparative quality checks across images."""

    def test_uniform_ocl_higher_than_degraded(self, output):
        u = output["uniform"]["ocl"]["mean"]
        d = output["degraded"]["ocl"]["mean"]
        assert u > d, f"Uniform OCL ({u}) should exceed degraded OCL ({d})"

    def test_uniform_fda_higher_than_degraded(self, output):
        u = output["uniform"]["fda"]["mean"]
        d = output["degraded"]["fda"]["mean"]
        assert u > d, f"Uniform FDA ({u}) should exceed degraded FDA ({d})"

    def test_diagonal_ocl_higher_than_degraded(self, output):
        """Clean diagonal ridges should have higher OCL than noisy mixed."""
        diag = output["diagonal"]["ocl"]["mean"]
        deg = output["degraded"]["ocl"]["mean"]
        assert diag > deg, (
            f"Diagonal OCL ({diag}) should exceed degraded OCL ({deg})"
        )

    def test_diagonal_fda_higher_than_degraded(self, output):
        """Clean diagonal ridges should have higher FDA than noisy mixed."""
        diag = output["diagonal"]["fda"]["mean"]
        deg = output["degraded"]["fda"]["mean"]
        assert diag > deg, (
            f"Diagonal FDA ({diag}) should exceed degraded FDA ({deg})"
        )

    def test_ocl_mean_in_range(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            m = output[img]["ocl"]["mean"]
            assert 0 <= m <= 1.0, f"{img} OCL mean out of [0,1]: {m}"

    def test_ocl_stddev_nonneg(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            s = output[img]["ocl"]["stddev"]
            assert s >= 0, f"{img} OCL stddev is negative: {s}"

    def test_fda_mean_nonneg(self, output):
        for img in ("uniform", "diagonal", "degraded"):
            m = output[img]["fda"]["mean"]
            assert m >= 0, f"{img} FDA mean is negative: {m}"


# ── Algorithm-specific correctness ───────────────────────────────────────

class TestAlgorithmCorrectness:
    """Tests that target specific algorithmic properties of the NFIQ2
    quality measures, verifiable from the reference implementation."""

    def test_uniform_fda_profile_has_correct_periodicity(self, output):
        """For horizontal ridges with period 16 in a 320x320 image:
        After correct rotation and 32x16 crop, the 32-element row-mean
        profile contains 2 cycles. The DFT peak should be at a non-edge
        frequency, producing a score from the full formula (not the edge
        case that returns 1.0).

        The correct FDA mean should be high (near 1.0) but strictly
        less than 1.0 since the full scoring formula adds neighbor
        terms and normalizes by the lower-half denominator."""
        m = output["uniform"]["fda"]["mean"]
        assert 0.9 < m < 0.999, (
            f"Uniform FDA mean should be in (0.9, 0.999) from the full "
            f"scoring formula, got {m}"
        )

    def test_diagonal_ocl_eigenvalue_correctness(self, output):
        """For 45-degree diagonal ridges, gx = gy at every pixel.
        The gradient covariance has a = b and c = a.
        Correct discriminant: sqrt((a-b)^2 + 4*c^2) = sqrt(4a^2) = 2a
        This gives eigv_min = 0, OCL = 1.0.

        A common bug is using 4*c instead of 4*c^2, which gives:
        sqrt(4a) instead of 2a, producing OCL << 1.0."""
        m = output["diagonal"]["ocl"]["mean"]
        assert m > 0.98, (
            f"Diagonal OCL mean should be > 0.98 (eigenvalue formula must "
            f"use c^2 in discriminant), got {m}"
        )

    def test_diagonal_fda_rotation_correctness(self, output):
        """For 45-degree ridges, the FDA rotation must include the pi/2
        offset (matching C++ reference: orientation + M_PI/2) to properly
        align ridges for the DFT row-mean projection. Without the offset,
        ridges remain partially unaligned and FDA scores drop."""
        m = output["diagonal"]["fda"]["mean"]
        assert m > 0.93, (
            f"Diagonal FDA mean should be > 0.93 with correct rotation "
            f"offset (orientation + pi/2), got {m}"
        )

    def test_uniform_fda_not_all_edge_case(self, output):
        """Verify that FDA values are not all from the mLoc==0 edge case.
        With correct 32-row crop, peak is at DFT index 2 (DC-excluded
        index 1), using the full scoring formula. With a 16-row crop,
        peak falls at DC-excluded index 0, triggering return 1.0."""
        m = output["uniform"]["fda"]["mean"]
        assert m < 0.999, (
            f"FDA mean = {m} suggests all blocks hit the mLoc==0 edge case. "
            f"Check that the slanted block crop produces 32 rows (SBW), not 16."
        )
