"""
Verification tests for the TEOS-10 seawater thermodynamics pipeline.

Expected values are computed at test time using the Python gsw package
(official TEOS-10 implementation). Anti-cheat tests call C functions
via ctypes with novel inputs not present in any data file.

"""

import json
import re
import os
import ctypes
import pytest
import numpy as np
import gsw

OUTPUT_PATH = "/app/output.json"
HEADER_PATH = "/app/gsw_check_data.h"
SHARED_LIB = "/app/libgsw_pipeline.so"
ERROR_LIMIT = 1e10
CAST_M = 45
CAST_N = 3


def parse_c_array(text, name):
    """Extract a C double array from header source text."""
    pattern = rf"static\s+const\s+double\s+{name}\s*\[\d*\]\s*=\s*\{{([^}}]+)\}}"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise ValueError(f"Array {name} not found in header")
    tokens = match.group(1).replace("\n", " ").split(",")
    return [float(t.strip()) for t in tokens if t.strip()]


def is_valid(val):
    return abs(val) < ERROR_LIMIT


def load_inputs():
    """Load input arrays by parsing the C header file."""
    with open(HEADER_PATH) as f:
        header = f.read()
    sa = parse_c_array(header, "ref_sa")
    ct = parse_c_array(header, "ref_ct")
    p = parse_c_array(header, "ref_p")
    grav = parse_c_array(header, "ref_grav")
    return sa, ct, p, grav


def load_output():
    assert os.path.exists(OUTPUT_PATH), f"Output file not found: {OUTPUT_PATH}"
    with open(OUTPUT_PATH) as f:
        return json.load(f)


def filter_valid_points(sa, ct, p):
    """Return indices where all three inputs are valid."""
    return [
        i for i in range(len(sa))
        if is_valid(sa[i]) and is_valid(ct[i]) and is_valid(p[i])
    ]


def check_values(computed, reference, name, rtol=1e-8):
    """Check that computed values match reference within relative tolerance."""
    assert len(computed) == len(reference), (
        f"{name}: expected {len(reference)} values, got {len(computed)}"
    )
    for i, (c, r) in enumerate(zip(computed, reference)):
        denom = max(abs(r), 1e-30)
        rel_err = abs(c - r) / denom
        assert rel_err <= rtol, (
            f"{name}[{i}]: computed={c:.17e}, reference={r:.17e}, "
            f"rel_err={rel_err:.3e}, tolerance={rtol:.3e}"
        )


class TestTEOS10Pipeline:
    """Test suite verifying pipeline output against Python gsw."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_output()
        self.sa, self.ct, self.p, self.grav = load_inputs()
        self.valid_idx = filter_valid_points(self.sa, self.ct, self.p)

    def test_output_has_required_keys(self):
        required = ["specvol", "rho", "alpha", "beta", "sigma0", "n2", "p_mid_n2"]
        for key in required:
            assert key in self.data, f"Missing key in output: {key}"

    def test_specvol_count(self):
        expected_count = len(self.valid_idx)
        assert len(self.data["specvol"]) == expected_count, (
            f"specvol: expected {expected_count} values, got {len(self.data['specvol'])}"
        )

    def test_specvol_accuracy(self):
        expected = [
            float(gsw.specvol(self.sa[i], self.ct[i], self.p[i]))
            for i in self.valid_idx
        ]
        check_values(self.data["specvol"], expected, "specvol", rtol=1e-10)

    def test_rho_accuracy(self):
        expected = [
            float(gsw.rho(self.sa[i], self.ct[i], self.p[i]))
            for i in self.valid_idx
        ]
        check_values(self.data["rho"], expected, "rho", rtol=1e-10)

    def test_alpha_accuracy(self):
        expected = [
            float(gsw.alpha(self.sa[i], self.ct[i], self.p[i]))
            for i in self.valid_idx
        ]
        check_values(self.data["alpha"], expected, "alpha", rtol=1e-10)

    def test_beta_accuracy(self):
        expected = [
            float(gsw.beta(self.sa[i], self.ct[i], self.p[i]))
            for i in self.valid_idx
        ]
        check_values(self.data["beta"], expected, "beta", rtol=1e-10)

    def test_sigma0_accuracy(self):
        expected = [
            float(gsw.sigma0(self.sa[i], self.ct[i]))
            for i in self.valid_idx
        ]
        check_values(self.data["sigma0"], expected, "sigma0", rtol=1e-10)

    def test_n2_accuracy(self):
        """Verify N2 against manual computation using Python gsw."""
        sa_all = self.sa
        ct_all = self.ct
        p_all = self.p
        grav_all = self.grav
        db_to_pa = 1e4

        expected_n2 = []
        expected_p_mid = []

        for cast in range(CAST_N):
            k = cast * CAST_M
            n_valid = 0
            for i in range(CAST_M):
                idx = k + i
                if (is_valid(sa_all[idx]) and is_valid(ct_all[idx])
                        and is_valid(p_all[idx])):
                    n_valid += 1
                else:
                    break

            for i in range(n_valid - 1):
                idx = k + i
                sa_mid = 0.5 * (sa_all[idx] + sa_all[idx + 1])
                ct_mid = 0.5 * (ct_all[idx] + ct_all[idx + 1])
                pm = 0.5 * (p_all[idx] + p_all[idx + 1])
                dp = p_all[idx + 1] - p_all[idx]
                dsa = sa_all[idx + 1] - sa_all[idx]
                dct = ct_all[idx + 1] - ct_all[idx]

                v = float(gsw.specvol(sa_mid, ct_mid, pm))
                a = float(gsw.alpha(sa_mid, ct_mid, pm))
                b = float(gsw.beta(sa_mid, ct_mid, pm))
                g = 0.5 * (grav_all[idx] + grav_all[idx + 1])

                n2_val = (g * g) / (v * db_to_pa * dp) * (b * dsa - a * dct)
                expected_n2.append(n2_val)
                expected_p_mid.append(pm)

        check_values(self.data["n2"], expected_n2, "n2", rtol=1e-8)
        check_values(self.data["p_mid_n2"], expected_p_mid, "p_mid_n2", rtol=1e-10)

    def test_n2_count(self):
        """N2 array should have correct number of entries."""
        sa_all = self.sa
        ct_all = self.ct
        p_all = self.p
        expected_count = 0
        for cast in range(CAST_N):
            k = cast * CAST_M
            n_valid = 0
            for i in range(CAST_M):
                idx = k + i
                if (is_valid(sa_all[idx]) and is_valid(ct_all[idx])
                        and is_valid(p_all[idx])):
                    n_valid += 1
                else:
                    break
            if n_valid > 0:
                expected_count += n_valid - 1
        assert len(self.data["n2"]) == expected_count, (
            f"n2: expected {expected_count} values, got {len(self.data['n2'])}"
        )


class TestAntiCheat:
    """Verify C functions work with arbitrary inputs (not just check data).

    These tests call the compiled C functions via ctypes with novel inputs
    that do not appear in any data file, preventing hardcoded solutions.
    """

    @pytest.fixture(autouse=True)
    def load_library(self):
        if not os.path.exists(SHARED_LIB):
            pytest.skip(f"Shared library {SHARED_LIB} not found")
        self.lib = ctypes.CDLL(SHARED_LIB)
        self.lib.gsw_specvol.restype = ctypes.c_double
        self.lib.gsw_specvol.argtypes = [
            ctypes.c_double, ctypes.c_double, ctypes.c_double
        ]
        self.lib.gsw_rho.restype = ctypes.c_double
        self.lib.gsw_rho.argtypes = [
            ctypes.c_double, ctypes.c_double, ctypes.c_double
        ]
        self.lib.gsw_specvol_alpha_beta.restype = None
        self.lib.gsw_specvol_alpha_beta.argtypes = [
            ctypes.c_double, ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        self.lib.gsw_sigma0.restype = ctypes.c_double
        self.lib.gsw_sigma0.argtypes = [ctypes.c_double, ctypes.c_double]

    def test_specvol_novel_inputs(self):
        """Specific volume must be correct for inputs not in the check data."""
        test_cases = [
            (35.0, 20.0, 100.0),
            (34.5, 5.0, 2000.0),
            (33.5, 0.5, 4000.0),
            (36.5, 25.0, 0.0),
            (34.0, 10.0, 500.0),
            (35.5, 15.0, 1000.0),
            (33.0, 2.0, 3000.0),
        ]
        for sa, ct, p in test_cases:
            c_val = self.lib.gsw_specvol(sa, ct, p)
            py_val = float(gsw.specvol(sa, ct, p))
            rel_err = abs(c_val - py_val) / max(abs(py_val), 1e-30)
            assert rel_err < 1e-9, (
                f"specvol({sa},{ct},{p}): C={c_val:.17e}, Python={py_val:.17e}, "
                f"rel_err={rel_err:.3e}"
            )

    def test_alpha_beta_novel_inputs(self):
        """Alpha and beta must be correct for novel inputs."""
        test_cases = [
            (35.0, 20.0, 100.0),
            (34.5, 5.0, 2000.0),
            (33.5, 0.5, 4000.0),
            (36.5, 25.0, 0.0),
            (34.0, 10.0, 500.0),
        ]
        for sa, ct, p in test_cases:
            sv = ctypes.c_double()
            a = ctypes.c_double()
            b = ctypes.c_double()
            self.lib.gsw_specvol_alpha_beta(
                sa, ct, p,
                ctypes.byref(sv), ctypes.byref(a), ctypes.byref(b)
            )
            py_a = float(gsw.alpha(sa, ct, p))
            py_b = float(gsw.beta(sa, ct, p))
            py_sv = float(gsw.specvol(sa, ct, p))

            rel_err_sv = abs(sv.value - py_sv) / max(abs(py_sv), 1e-30)
            rel_err_a = abs(a.value - py_a) / max(abs(py_a), 1e-30)
            rel_err_b = abs(b.value - py_b) / max(abs(py_b), 1e-30)
            assert rel_err_sv < 1e-9, (
                f"specvol_alpha_beta specvol({sa},{ct},{p}): "
                f"C={sv.value:.17e}, Python={py_sv:.17e}"
            )
            assert rel_err_a < 1e-9, (
                f"alpha({sa},{ct},{p}): C={a.value:.17e}, Python={py_a:.17e}"
            )
            assert rel_err_b < 1e-9, (
                f"beta({sa},{ct},{p}): C={b.value:.17e}, Python={py_b:.17e}"
            )

    def test_rho_novel_inputs(self):
        """Density must be correct for novel inputs."""
        test_cases = [
            (35.0, 20.0, 100.0),
            (34.5, 5.0, 2000.0),
            (36.5, 25.0, 0.0),
            (33.0, 2.0, 3000.0),
        ]
        for sa, ct, p in test_cases:
            c_val = self.lib.gsw_rho(sa, ct, p)
            py_val = float(gsw.rho(sa, ct, p))
            rel_err = abs(c_val - py_val) / max(abs(py_val), 1e-30)
            assert rel_err < 1e-9, (
                f"rho({sa},{ct},{p}): C={c_val:.17e}, Python={py_val:.17e}"
            )

    def test_sigma0_novel_inputs(self):
        """Sigma0 must be correct for novel inputs."""
        test_cases = [
            (35.0, 20.0),
            (34.5, 5.0),
            (36.5, 25.0),
            (33.0, 2.0),
        ]
        for sa, ct in test_cases:
            c_val = self.lib.gsw_sigma0(sa, ct)
            py_val = float(gsw.sigma0(sa, ct))
            rel_err = abs(c_val - py_val) / max(abs(py_val), 1e-30)
            assert rel_err < 1e-9, (
                f"sigma0({sa},{ct}): C={c_val:.17e}, Python={py_val:.17e}"
            )
