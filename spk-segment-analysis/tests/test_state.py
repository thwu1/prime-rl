
"""
Tests for SPK Segment Forensics and Interpolation Accuracy Benchmark.

Independently verifies the agent's deliverables by loading the same SPICE
kernels and performing cross-checks using the toolkit's high-level API.
"""

import json
import os

import numpy as np
import pytest
import spiceypy as spice


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def spice_kernels():
    """Load DE432s and LSK before each test, clean up after."""
    spice.kclear()
    spice.furnsh("/app/data/naif0012.tls")
    spice.furnsh("/app/data/de432s.bsp")
    yield
    spice.kclear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_emb_type2_metadata():
    """Independently extract Type 2 segment metadata for EMB (body 3)."""
    handle = spice.dafopr("/app/data/de432s.bsp")
    spice.dafbfs(handle)
    while spice.daffna():
        summary = spice.dafgs(n=128)
        dc, ic = spice.dafus(summary, 2, 6)
        if int(ic[0]) == 3 and int(ic[1]) == 0 and int(ic[3]) == 2:
            end_addr = int(ic[5])
            meta = spice.dafgda(handle, end_addr - 3, end_addr)
            spice.dafcls(handle)
            return {
                "init_epoch_et": meta[0],
                "intlen_seconds": meta[1],
                "rsize": int(meta[2]),
                "n_records": int(meta[3]),
                "n_coeffs_per_component": (int(meta[2]) - 2) // 3,
                "poly_degree": (int(meta[2]) - 2) // 3 - 1,
            }
    spice.dafcls(handle)
    pytest.fail("EMB Type 2 segment not found in DE432s")


# ===========================================================================
# 1. Segment metadata
# ===========================================================================

class TestSegmentMetadata:
    def test_file_exists(self):
        assert os.path.exists("/app/segment_metadata.json"), \
            "segment_metadata.json not found"

    def test_required_keys(self):
        with open("/app/segment_metadata.json") as f:
            data = json.load(f)
        for key in ("poly_degree", "n_coeffs_per_component", "rsize",
                     "intlen_seconds", "n_records", "init_epoch_et"):
            assert key in data, f"Missing key: {key}"

    def test_correct_values(self):
        with open("/app/segment_metadata.json") as f:
            agent = json.load(f)
        expected = _extract_emb_type2_metadata()

        assert agent["poly_degree"] == expected["poly_degree"], \
            f"poly_degree: {agent['poly_degree']} != {expected['poly_degree']}"
        assert agent["n_coeffs_per_component"] == expected["n_coeffs_per_component"]
        assert agent["rsize"] == expected["rsize"]
        assert abs(agent["intlen_seconds"] - expected["intlen_seconds"]) < 1e-6
        assert agent["n_records"] == expected["n_records"]
        assert abs(agent["init_epoch_et"] - expected["init_epoch_et"]) < 1e-6


# ===========================================================================
# 2. Manual Chebyshev evaluation
# ===========================================================================

class TestManualPosition:
    def test_file_exists(self):
        assert os.path.exists("/app/manual_position.json")

    def test_required_keys(self):
        with open("/app/manual_position.json") as f:
            data = json.load(f)
        for key in ("x_km", "y_km", "z_km"):
            assert key in data, f"Missing key: {key}"

    def test_matches_spice(self):
        """Manual Chebyshev evaluation must match spkgeo within 1e-6 km."""
        with open("/app/manual_position.json") as f:
            pos = json.load(f)

        et = spice.str2et("2020-JAN-01 12:00:00 TDB")
        state, _ = spice.spkgeo(3, et, "J2000", 0)

        assert abs(pos["x_km"] - state[0]) < 1e-6, \
            f"X: {pos['x_km']:.10f} vs {state[0]:.10f}"
        assert abs(pos["y_km"] - state[1]) < 1e-6, \
            f"Y: {pos['y_km']:.10f} vs {state[1]:.10f}"
        assert abs(pos["z_km"] - state[2]) < 1e-6, \
            f"Z: {pos['z_km']:.10f} vs {state[2]:.10f}"

    def test_reasonable_magnitude(self):
        """EMB position should be roughly 1 AU from SSB."""
        with open("/app/manual_position.json") as f:
            pos = json.load(f)
        mag = (pos["x_km"]**2 + pos["y_km"]**2 + pos["z_km"]**2) ** 0.5
        assert 1.0e8 < mag < 2.0e8, f"Position magnitude {mag:.2e} km unreasonable"


# ===========================================================================
# 3. Verification error
# ===========================================================================

class TestVerificationError:
    def test_file_exists(self):
        assert os.path.exists("/app/verification_error.txt")

    def test_near_zero(self):
        with open("/app/verification_error.txt") as f:
            error = float(f.read().strip())
        assert error < 1e-9, \
            f"Verification error {error:.2e} km exceeds 1e-9 km threshold"

    def test_non_negative(self):
        with open("/app/verification_error.txt") as f:
            error = float(f.read().strip())
        assert error >= 0.0


# ===========================================================================
# 4. Chebyshev fitting accuracy
# ===========================================================================

class TestChebyshevAccuracy:
    def test_file_exists(self):
        assert os.path.exists("/app/chebyshev_accuracy.json")

    def test_all_degrees_present(self):
        with open("/app/chebyshev_accuracy.json") as f:
            data = json.load(f)
        for d in ("5", "10", "15", "20", "25"):
            assert d in data, f"Degree {d} missing"

    def test_values_positive(self):
        with open("/app/chebyshev_accuracy.json") as f:
            data = json.load(f)
        for d, v in data.items():
            assert v >= 0, f"Error at degree {d} is negative"

    def test_accuracy_improves_with_degree(self):
        """Higher-degree fits must outperform lower-degree fits."""
        with open("/app/chebyshev_accuracy.json") as f:
            data = json.load(f)
        assert data["5"] > data["15"], \
            f"Deg 5 ({data['5']:.4e}) should exceed deg 15 ({data['15']:.4e})"
        assert data["10"] > data["25"], \
            f"Deg 10 ({data['10']:.4e}) should exceed deg 25 ({data['25']:.4e})"

    def test_independent_cross_check_degree15(self):
        """Independently compute degree-15 max error and cross-check."""
        with open("/app/chebyshev_accuracy.json") as f:
            data = json.load(f)

        et_start = spice.str2et("2020-JAN-01 00:00:00 TDB")
        et_end = spice.str2et("2020-JUL-01 00:00:00 TDB")

        # Same 50 sample points as task spec
        sample_ets = np.linspace(et_start, et_end, 50)
        sample_pos = np.array([
            spice.spkgeo(3, float(e), "J2000", 0)[0][:3] for e in sample_ets
        ])

        # 500 test points (fewer than agent's 5000, for speed)
        test_ets = np.linspace(et_start, et_end, 500)
        test_pos = np.array([
            spice.spkgeo(3, float(e), "J2000", 0)[0][:3] for e in test_ets
        ])

        t_s = 2.0 * (sample_ets - et_start) / (et_end - et_start) - 1.0
        t_t = 2.0 * (test_ets - et_start) / (et_end - et_start) - 1.0

        max_err = 0.0
        for dim in range(3):
            c = np.polynomial.chebyshev.chebfit(t_s, sample_pos[:, dim], 15)
            fitted = np.polynomial.chebyshev.chebval(t_t, c)
            max_err = max(max_err, float(np.max(np.abs(fitted - test_pos[:, dim]))))

        reported = data["15"]
        # Agent uses 5000 test points vs our 500, so their max might be higher,
        # but both should be in the same order of magnitude
        if max_err > 1e-12:
            ratio = reported / max_err
            assert 0.01 < ratio < 100, \
                f"Degree-15 error ratio {ratio:.2f} out of expected range " \
                f"(reported={reported:.4e}, independent={max_err:.4e})"


# ===========================================================================
# 5. Hermite SPK file
# ===========================================================================

class TestHermiteSPK:
    def test_file_exists(self):
        assert os.path.exists("/app/hermite_emb.bsp"), "hermite_emb.bsp not found"

    def test_file_not_empty(self):
        size = os.path.getsize("/app/hermite_emb.bsp")
        assert size > 1000, f"hermite_emb.bsp too small ({size} bytes)"

    def test_queryable_at_midrange(self):
        """Load Hermite SPK and query at a mid-range epoch."""
        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/hermite_emb.bsp")

        et = spice.str2et("2020-MAR-15 12:00:00 TDB")
        state, _ = spice.spkgeo(3, et, "J2000", 0)
        mag = float(np.linalg.norm(state[:3]))
        assert 1.0e8 < mag < 2.0e8, \
            f"Hermite position magnitude {mag:.2e} km unreasonable"

        spice.kclear()

    def test_accuracy_at_specific_epoch(self):
        """Hermite position at 2020-APR-01 should match DE432s within 1 km."""
        # Ground truth from DE432s
        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/data/de432s.bsp")
        et = spice.str2et("2020-APR-01 00:00:00 TDB")
        truth, _ = spice.spkgeo(3, et, "J2000", 0)

        # Hermite result
        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/hermite_emb.bsp")
        hermite, _ = spice.spkgeo(3, et, "J2000", 0)

        error = float(np.linalg.norm(
            np.array(truth[:3]) - np.array(hermite[:3])
        ))
        assert error < 1.0, \
            f"Hermite error at 2020-APR-01: {error:.4e} km exceeds 1 km"

        spice.kclear()

    def test_velocity_present(self):
        """Hermite SPK should also produce valid velocity."""
        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/hermite_emb.bsp")

        et = spice.str2et("2020-MAR-15 12:00:00 TDB")
        state, _ = spice.spkgeo(3, et, "J2000", 0)
        vel_mag = float(np.linalg.norm(state[3:6]))
        # EMB orbital velocity ~30 km/s
        assert 25.0 < vel_mag < 35.0, \
            f"Velocity magnitude {vel_mag:.2f} km/s unreasonable"

        spice.kclear()


# ===========================================================================
# 6. Hermite max error
# ===========================================================================

class TestHermiteMaxError:
    def test_file_exists(self):
        assert os.path.exists("/app/hermite_max_error.txt")

    def test_reasonable_value(self):
        with open("/app/hermite_max_error.txt") as f:
            error = float(f.read().strip())
        assert error >= 0, "Max error must be non-negative"
        # Daily sampling + degree 7 Hermite should be very accurate
        assert error < 1.0, \
            f"Hermite max error {error:.4e} km exceeds 1 km"

    def test_independently_verified(self):
        """Spot-check Hermite accuracy at multiple epochs."""
        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/data/de432s.bsp")

        # Check at 10 specific epochs spread across coverage
        et_start = spice.str2et("2020-JAN-15 00:00:00 TDB")
        et_end = spice.str2et("2020-JUN-15 00:00:00 TDB")
        check_ets = np.linspace(et_start, et_end, 10)

        truths = np.array([
            spice.spkgeo(3, float(e), "J2000", 0)[0][:3] for e in check_ets
        ])

        spice.kclear()
        spice.furnsh("/app/data/naif0012.tls")
        spice.furnsh("/app/hermite_emb.bsp")

        hermites = np.array([
            spice.spkgeo(3, float(e), "J2000", 0)[0][:3] for e in check_ets
        ])

        errors = np.linalg.norm(truths - hermites, axis=1)
        max_err = float(np.max(errors))
        assert max_err < 1.0, \
            f"Independent Hermite max error {max_err:.4e} km exceeds 1 km"

        spice.kclear()
