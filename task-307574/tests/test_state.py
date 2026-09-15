"""Tests for NF4 reverse engineering task.

Verifies that the agent correctly reverse-engineered the NormalFloat
quantization format construction and extended it to higher bit widths.
"""

import importlib.util
import json
import os

import pytest

RESULTS_DIR = "/app/results"
NF4_PUBLISHED_PATH = "/app/nf4_published.json"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def load_construction():
    """Load the agent's construction module dynamically."""
    path = os.path.join(RESULTS_DIR, "construction.py")
    spec = importlib.util.spec_from_file_location("construction", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.construct_nfn


# ── Alpha parameter ──────────────────────────────────────────────


class TestAlpha:
    def test_alpha_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "alpha.txt"))

    def test_alpha_is_929_over_960(self):
        with open(os.path.join(RESULTS_DIR, "alpha.txt")) as f:
            raw = f.read().strip()
        parts = raw.split("/")
        assert len(parts) == 2, f"Expected fraction a/b, got: {raw}"
        num = int(parts[0].strip())
        den = int(parts[1].strip())
        assert num == 929 and den == 960, f"Expected 929/960, got {num}/{den}"


# ── NF4 reproduction ─────────────────────────────────────────────


class TestNF4Reproduction:
    def test_nf4_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "nf4_reproduced.json"))

    def test_nf4_length(self):
        nf4 = load_json(os.path.join(RESULTS_DIR, "nf4_reproduced.json"))
        assert len(nf4) == 16

    def test_nf4_matches_published(self):
        nf4 = load_json(os.path.join(RESULTS_DIR, "nf4_reproduced.json"))
        published = load_json(NF4_PUBLISHED_PATH)
        for i, (a, b) in enumerate(zip(nf4, published)):
            assert abs(a - b) < 1e-6, (
                f"NF4[{i}]: reproduced={a}, published={b}, diff={abs(a - b)}"
            )

    def test_nf4_endpoints(self):
        nf4 = load_json(os.path.join(RESULTS_DIR, "nf4_reproduced.json"))
        assert nf4[0] == pytest.approx(-1.0, abs=1e-10)
        assert nf4[15] == pytest.approx(1.0, abs=1e-10)

    def test_nf4_zero_at_index_7(self):
        nf4 = load_json(os.path.join(RESULTS_DIR, "nf4_reproduced.json"))
        assert nf4[7] == pytest.approx(0.0, abs=1e-10)


# ── Construction function ────────────────────────────────────────


class TestConstruction:
    def test_construction_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "construction.py"))

    def test_produces_correct_nf4(self):
        construct_nfn = load_construction()
        published = load_json(NF4_PUBLISHED_PATH)
        nf4 = construct_nfn(4, 929 / 960)
        assert len(nf4) == 16
        for i, (a, b) in enumerate(zip(nf4, published)):
            assert abs(a - b) < 1e-6, (
                f"construct_nfn(4)[{i}]={a}, published={b}"
            )

    def test_generalises_to_nf3(self):
        """NF3: 8 values = 3 negative + zero + 4 positive."""
        construct_nfn = load_construction()
        nf3 = construct_nfn(3, 929 / 960)
        assert len(nf3) == 8
        assert nf3[0] == pytest.approx(-1.0, abs=1e-10)
        assert nf3[3] == pytest.approx(0.0, abs=1e-10)
        assert nf3[7] == pytest.approx(1.0, abs=1e-10)
        for i in range(len(nf3) - 1):
            assert nf3[i] < nf3[i + 1], f"Not monotonic at {i}"

    def test_generalises_to_nf5(self):
        """NF5: 32 values = 15 negative + zero + 16 positive."""
        construct_nfn = load_construction()
        nf5 = construct_nfn(5, 929 / 960)
        assert len(nf5) == 32
        assert nf5[0] == pytest.approx(-1.0, abs=1e-10)
        assert nf5[15] == pytest.approx(0.0, abs=1e-10)
        assert nf5[31] == pytest.approx(1.0, abs=1e-10)
        for i in range(31):
            assert nf5[i] < nf5[i + 1]

    def test_adapts_to_different_alpha(self):
        """Verify the function is not hardcoded for alpha=929/960."""
        construct_nfn = load_construction()
        nf4_a = construct_nfn(4, 0.95)
        nf4_b = construct_nfn(4, 0.99)
        # Different alpha must produce different interior values
        assert abs(nf4_a[1] - nf4_b[1]) > 1e-4, (
            "Construction should produce different values for different alpha"
        )
        # Both must still have correct structural properties
        for cb in (nf4_a, nf4_b):
            assert len(cb) == 16
            assert cb[0] == pytest.approx(-1.0, abs=1e-10)
            assert cb[7] == pytest.approx(0.0, abs=1e-10)
            assert cb[15] == pytest.approx(1.0, abs=1e-10)
            for i in range(15):
                assert cb[i] < cb[i + 1]


# ── NF8 codebook ─────────────────────────────────────────────────


class TestNF8:
    def test_nf8_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "nf8_values.json"))

    def test_nf8_length(self):
        nf8 = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        assert len(nf8) == 256

    def test_nf8_endpoints(self):
        nf8 = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        assert nf8[0] == pytest.approx(-1.0, abs=1e-10)
        assert nf8[255] == pytest.approx(1.0, abs=1e-10)

    def test_nf8_zero_at_index_127(self):
        nf8 = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        assert nf8[127] == pytest.approx(0.0, abs=1e-10)

    def test_nf8_monotonic(self):
        nf8 = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        for i in range(255):
            assert nf8[i] < nf8[i + 1], f"Not monotonic at index {i}"

    def test_nf8_range(self):
        nf8 = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        for i, v in enumerate(nf8):
            assert -1.0 <= v <= 1.0, f"NF8[{i}]={v} out of [-1,1]"

    def test_nf8_matches_construction(self):
        """NF8 output file must agree with the construction function."""
        construct_nfn = load_construction()
        nf8_file = load_json(os.path.join(RESULTS_DIR, "nf8_values.json"))
        nf8_computed = construct_nfn(8, 929 / 960)
        assert len(nf8_file) == len(nf8_computed)
        for i, (a, b) in enumerate(zip(nf8_file, nf8_computed)):
            assert abs(a - b) < 1e-10, (
                f"NF8[{i}]: file={a}, construction={b}"
            )


# ── NF6 codebook ─────────────────────────────────────────────────


class TestNF6:
    def test_nf6_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "nf6_values.json"))

    def test_nf6_length(self):
        nf6 = load_json(os.path.join(RESULTS_DIR, "nf6_values.json"))
        assert len(nf6) == 64

    def test_nf6_endpoints(self):
        nf6 = load_json(os.path.join(RESULTS_DIR, "nf6_values.json"))
        assert nf6[0] == pytest.approx(-1.0, abs=1e-10)
        assert nf6[63] == pytest.approx(1.0, abs=1e-10)

    def test_nf6_zero_at_index_31(self):
        nf6 = load_json(os.path.join(RESULTS_DIR, "nf6_values.json"))
        assert nf6[31] == pytest.approx(0.0, abs=1e-10)

    def test_nf6_monotonic(self):
        nf6 = load_json(os.path.join(RESULTS_DIR, "nf6_values.json"))
        for i in range(63):
            assert nf6[i] < nf6[i + 1], f"Not monotonic at index {i}"

    def test_nf6_matches_construction(self):
        construct_nfn = load_construction()
        nf6_file = load_json(os.path.join(RESULTS_DIR, "nf6_values.json"))
        nf6_computed = construct_nfn(6, 929 / 960)
        assert len(nf6_file) == len(nf6_computed)
        for i, (a, b) in enumerate(zip(nf6_file, nf6_computed)):
            assert abs(a - b) < 1e-10, (
                f"NF6[{i}]: file={a}, construction={b}"
            )


# ── Quantization errors ──────────────────────────────────────────


class TestQuantizationErrors:
    def test_errors_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )

    def test_all_keys_present(self):
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        expected = {"nf4", "nf6", "nf8", "uniform4", "uniform6", "uniform8"}
        assert set(errors.keys()) == expected, (
            f"Missing keys: {expected - set(errors.keys())}"
        )

    def test_errors_positive(self):
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        for k, v in errors.items():
            assert v > 0, f"{k} error must be positive, got {v}"

    def test_nf_beats_uniform(self):
        """NF codebooks should outperform uniform for Gaussian data."""
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        assert errors["nf4"] < errors["uniform4"], (
            f"NF4 ({errors['nf4']}) should beat uniform4 ({errors['uniform4']})"
        )
        assert errors["nf6"] < errors["uniform6"], (
            f"NF6 ({errors['nf6']}) should beat uniform6 ({errors['uniform6']})"
        )
        assert errors["nf8"] < errors["uniform8"], (
            f"NF8 ({errors['nf8']}) should beat uniform8 ({errors['uniform8']})"
        )

    def test_more_bits_less_error(self):
        """More bits must reduce quantization error."""
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        assert errors["nf8"] < errors["nf6"] < errors["nf4"], (
            f"NF errors not monotonically decreasing: "
            f"nf4={errors['nf4']}, nf6={errors['nf6']}, nf8={errors['nf8']}"
        )
        assert errors["uniform8"] < errors["uniform6"] < errors["uniform4"]

    def test_nf4_error_plausible(self):
        """NF4 MSE should be in a plausible range for N(0,1) data."""
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        assert 0.005 < errors["nf4"] < 0.20, (
            f"NF4 MSE {errors['nf4']} outside plausible range [0.005, 0.20]"
        )

    def test_nf8_much_smaller_than_nf4(self):
        """NF8 MSE should be substantially smaller than NF4."""
        errors = load_json(
            os.path.join(RESULTS_DIR, "quantization_errors.json")
        )
        assert errors["nf8"] < errors["nf4"] / 5, (
            f"NF8 ({errors['nf8']}) should be at least 5x smaller "
            f"than NF4 ({errors['nf4']})"
        )
