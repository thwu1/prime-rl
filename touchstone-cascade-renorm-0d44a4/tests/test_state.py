"""Tests for RF network cascade and renormalization pipeline.

Independently computes golden values from the known input data and compares
against the solver's output files. Also verifies the C library build,
Touchstone v2.0 output format, and gnuplot SVG plot.
"""


import pytest
import json
import os
import ctypes
import numpy as np


def compute_golden():
    """Compute golden values from the known input data.

    This duplicates the entire processing pipeline independently to verify
    the solver's implementation.
    """
    freqs = [1.0, 2.0, 3.0, 4.0, 5.0]
    n_freq = 5
    I2 = np.eye(2)

    # ---- Parse Network A (v1.0, DB format, 50 ohm, legacy 21_12 ordering) ----
    # Data columns: freq, S11_dB, S11_ang, S21_dB, S21_ang, S12_dB, S12_ang, S22_dB, S22_ang
    # Ordering: S11, S21, S12, S22 (legacy 21_12)
    net_a_data = [
        [1.0, -10.0, 150.0, -1.0, -15.0, -1.0, -15.0, -11.0, 155.0],
        [2.0, -20.0, 170.0, -0.2, -5.0, -0.2, -5.0, -22.0, 172.0],
        [3.0, -26.0, -178.0, -0.05, -2.0, -0.05, -2.0, -27.0, -176.0],
        [4.0, -20.0, 168.0, -0.2, -5.5, -0.2, -5.5, -22.0, 170.0],
        [5.0, -10.0, 148.0, -1.0, -16.0, -1.0, -16.0, -11.0, 153.0],
    ]

    def db_to_complex(db_val, ang_deg):
        mag = 10.0 ** (db_val / 20.0)
        return mag * np.exp(1j * np.deg2rad(ang_deg))

    S_A = np.zeros((n_freq, 2, 2), dtype=complex)
    for i, row in enumerate(net_a_data):
        # Legacy 21_12 ordering: S11, S21, S12, S22
        S_A[i, 0, 0] = db_to_complex(row[1], row[2])   # S11
        S_A[i, 1, 0] = db_to_complex(row[3], row[4])   # S21
        S_A[i, 0, 1] = db_to_complex(row[5], row[6])   # S12
        S_A[i, 1, 1] = db_to_complex(row[7], row[8])   # S22

    # ---- Parse Network B (v2.0, RI format, per-port ref [50, 75], 12_21 ordering) ----
    # Data columns: freq, Re(S11), Im(S11), Re(S12), Im(S12), Re(S21), Im(S21), Re(S22), Im(S22)
    # Ordering: S11, S12, S21, S22 (12_21)
    net_b_data = [
        [1.0, 0.100, 0.050, 0.700, -0.200, 0.650, -0.250, -0.050, 0.100],
        [2.0, 0.050, 0.030, 0.800, -0.150, 0.750, -0.180, -0.030, 0.080],
        [3.0, 0.020, 0.010, 0.850, -0.100, 0.820, -0.120, -0.010, 0.050],
        [4.0, 0.050, 0.030, 0.800, -0.150, 0.750, -0.180, -0.030, 0.080],
        [5.0, 0.100, 0.050, 0.700, -0.200, 0.650, -0.250, -0.050, 0.100],
    ]

    S_B = np.zeros((n_freq, 2, 2), dtype=complex)
    for i, row in enumerate(net_b_data):
        # 12_21 ordering: S11, S12, S21, S22
        S_B[i, 0, 0] = complex(row[1], row[2])   # S11
        S_B[i, 0, 1] = complex(row[3], row[4])   # S12
        S_B[i, 1, 0] = complex(row[5], row[6])   # S21
        S_B[i, 1, 1] = complex(row[7], row[8])   # S22

    # ---- Renormalize Network B from per-port [50, 75] to uniform 50 ohm ----
    # Z = sqrt(Z0) * (I + S) * inv(I - S) * sqrt(Z0)
    # S_new = (Z - Z0_new*I) * inv(Z + Z0_new*I)  [for uniform Z0_new]
    sqrt_z0_b = np.diag([np.sqrt(50.0), np.sqrt(75.0)])

    S_B_50 = np.zeros((n_freq, 2, 2), dtype=complex)
    for i in range(n_freq):
        Z_B = sqrt_z0_b @ (I2 + S_B[i]) @ np.linalg.inv(I2 - S_B[i]) @ sqrt_z0_b
        S_B_50[i] = (Z_B - 50.0 * I2) @ np.linalg.inv(Z_B + 50.0 * I2)

    # ---- Cascade via T-parameters ----
    def s_to_t(S):
        S11, S12, S21, S22 = S[0, 0], S[0, 1], S[1, 0], S[1, 1]
        det_S = S11 * S22 - S12 * S21
        T = np.zeros((2, 2), dtype=complex)
        T[0, 0] = -det_S / S21
        T[0, 1] = S11 / S21
        T[1, 0] = -S22 / S21
        T[1, 1] = 1.0 / S21
        return T

    def t_to_s(T):
        T11, T12, T21, T22 = T[0, 0], T[0, 1], T[1, 0], T[1, 1]
        S = np.zeros((2, 2), dtype=complex)
        S[0, 0] = T12 / T22
        S[0, 1] = (T11 * T22 - T12 * T21) / T22
        S[1, 0] = 1.0 / T22
        S[1, 1] = -T21 / T22
        return S

    S_cascade_50 = np.zeros((n_freq, 2, 2), dtype=complex)
    for i in range(n_freq):
        T_A = s_to_t(S_A[i])
        T_B = s_to_t(S_B_50[i])
        T_cascade = T_A @ T_B
        S_cascade_50[i] = t_to_s(T_cascade)

    # ---- Renormalize cascade from 50 ohm to 75 ohm ----
    S_75 = np.zeros((n_freq, 2, 2), dtype=complex)
    Z_params = np.zeros((n_freq, 2, 2), dtype=complex)
    for i in range(n_freq):
        Z_cascade = 50.0 * (I2 + S_cascade_50[i]) @ np.linalg.inv(I2 - S_cascade_50[i])
        S_75[i] = (Z_cascade - 75.0 * I2) @ np.linalg.inv(Z_cascade + 75.0 * I2)
        Z_params[i] = Z_cascade  # Z is invariant under ref impedance change

    # ---- Compute metrics ----
    insertion_loss_db = []
    return_loss_db = []
    for i in range(n_freq):
        il = 20.0 * np.log10(np.abs(S_75[i, 1, 0]))
        rl = -20.0 * np.log10(np.abs(S_75[i, 0, 0]))
        insertion_loss_db.append(float(il))
        return_loss_db.append(float(rl))

    return freqs, S_75, Z_params, insertion_loss_db, return_loss_db


def parse_ts_output(filepath):
    """Parse a Touchstone v2.0 RI format output file for verification."""
    with open(filepath) as f:
        content = f.read()

    lines = content.split('\n')
    ref_z = None
    n_freqs_declared = None
    in_data = False
    data_rows = []
    keywords = {
        'version': False, 'nports': False, 'order': False,
        'nfreqs': False, 'network_data': False, 'end': False,
        'reference': False,
    }

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('!'):
            continue
        lower = stripped.lower()

        if lower.startswith('[version]'):
            keywords['version'] = True
        elif lower.startswith('[number of ports]'):
            keywords['nports'] = True
        elif lower.startswith('[two-port data order]'):
            keywords['order'] = True
        elif lower.startswith('[number of frequencies]'):
            keywords['nfreqs'] = True
            parts = stripped.split()
            n_freqs_declared = int(parts[-1])
        elif lower.startswith('[reference]'):
            keywords['reference'] = True
            idx = stripped.index(']') + 1
            vals_str = stripped[idx:].strip()
            if '!' in vals_str:
                vals_str = vals_str[:vals_str.index('!')].strip()
            ref_z = [float(v) for v in vals_str.split() if v]
        elif lower.startswith('[network data]'):
            keywords['network_data'] = True
            in_data = True
        elif lower.startswith('[end]'):
            keywords['end'] = True
            in_data = False
        elif lower.startswith('['):
            continue
        elif stripped.startswith('#'):
            continue
        elif in_data:
            if '!' in stripped:
                stripped = stripped[:stripped.index('!')].strip()
            try:
                vals = list(map(float, stripped.split()))
                if len(vals) == 9:
                    data_rows.append(vals)
            except ValueError:
                continue

    return keywords, ref_z, n_freqs_declared, data_rows


class TestOutputFilesExist:
    """Check that all required output files were created."""

    def test_cascade_sparams_exists(self):
        assert os.path.exists("/app/output/cascade_sparams.json"), \
            "Missing /app/output/cascade_sparams.json"

    def test_z_matrix_exists(self):
        assert os.path.exists("/app/output/z_matrix.json"), \
            "Missing /app/output/z_matrix.json"

    def test_metrics_exists(self):
        assert os.path.exists("/app/output/metrics.json"), \
            "Missing /app/output/metrics.json"

    def test_touchstone_output_exists(self):
        assert os.path.exists("/app/output/cascade_output.ts"), \
            "Missing /app/output/cascade_output.ts"

    def test_svg_plot_exists(self):
        assert os.path.exists("/app/output/frequency_response.svg"), \
            "Missing /app/output/frequency_response.svg"


class TestLibMatrix:
    """Verify the C shared library was compiled and works correctly."""

    def test_library_exists(self):
        assert os.path.exists("/app/libmatrix.so"), \
            "/app/libmatrix.so not found — was it compiled?"

    def test_library_loadable(self):
        lib = ctypes.CDLL("/app/libmatrix.so")
        assert lib is not None

    def test_exported_functions(self):
        lib = ctypes.CDLL("/app/libmatrix.so")
        for fn_name in ['cmat2_multiply', 'cmat2_invert', 'cmat2_add',
                         'cmat2_subtract', 'cmat2_identity', 'cmat2_determinant',
                         'cmat2_scale', 'cmat2_diag']:
            assert hasattr(lib, fn_name), f"Missing exported function: {fn_name}"

    def test_multiply_identity(self):
        """Verify A * I = A for a known matrix."""
        lib = ctypes.CDLL("/app/libmatrix.so")
        D8 = ctypes.c_double * 8
        A = D8(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
        I = D8(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        C = D8()
        lib.cmat2_multiply(A, I, C)
        for k in range(8):
            assert abs(C[k] - A[k]) < 1e-12, \
                f"A * I != A at index {k}: {C[k]} != {A[k]}"

    def test_invert_identity(self):
        """Verify inv(I) = I."""
        lib = ctypes.CDLL("/app/libmatrix.so")
        D8 = ctypes.c_double * 8
        I = D8(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        Iinv = D8()
        ret = lib.cmat2_invert(I, Iinv)
        assert ret == 0, "Identity matrix reported as singular"
        for k in range(8):
            assert abs(Iinv[k] - I[k]) < 1e-12


class TestCascadeSparams:
    """Verify cascaded S-parameter values against golden computation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.freqs, self.S_75, self.Z_params, self.il, self.rl = compute_golden()
        with open("/app/output/cascade_sparams.json") as f:
            self.data = json.load(f)

    def test_reference_impedance(self):
        assert self.data["reference_impedance_ohm"] == pytest.approx(75.0, abs=1e-6)

    def test_frequency_count(self):
        assert len(self.data["s_parameters"]) == 5

    def test_frequencies(self):
        for i, sp in enumerate(self.data["s_parameters"]):
            assert sp["freq_ghz"] == pytest.approx(self.freqs[i], abs=1e-6)

    def test_s11_values(self):
        for i, sp in enumerate(self.data["s_parameters"]):
            S = self.S_75[i]
            assert sp["S11_re"] == pytest.approx(S[0, 0].real, abs=1e-6), \
                f"S11_re mismatch at freq={self.freqs[i]} GHz"
            assert sp["S11_im"] == pytest.approx(S[0, 0].imag, abs=1e-6), \
                f"S11_im mismatch at freq={self.freqs[i]} GHz"

    def test_s12_values(self):
        for i, sp in enumerate(self.data["s_parameters"]):
            S = self.S_75[i]
            assert sp["S12_re"] == pytest.approx(S[0, 1].real, abs=1e-6), \
                f"S12_re mismatch at freq={self.freqs[i]} GHz"
            assert sp["S12_im"] == pytest.approx(S[0, 1].imag, abs=1e-6), \
                f"S12_im mismatch at freq={self.freqs[i]} GHz"

    def test_s21_values(self):
        for i, sp in enumerate(self.data["s_parameters"]):
            S = self.S_75[i]
            assert sp["S21_re"] == pytest.approx(S[1, 0].real, abs=1e-6), \
                f"S21_re mismatch at freq={self.freqs[i]} GHz"
            assert sp["S21_im"] == pytest.approx(S[1, 0].imag, abs=1e-6), \
                f"S21_im mismatch at freq={self.freqs[i]} GHz"

    def test_s22_values(self):
        for i, sp in enumerate(self.data["s_parameters"]):
            S = self.S_75[i]
            assert sp["S22_re"] == pytest.approx(S[1, 1].real, abs=1e-6), \
                f"S22_re mismatch at freq={self.freqs[i]} GHz"
            assert sp["S22_im"] == pytest.approx(S[1, 1].imag, abs=1e-6), \
                f"S22_im mismatch at freq={self.freqs[i]} GHz"


class TestZMatrix:
    """Verify Z-parameter matrix values against golden computation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.freqs, self.S_75, self.Z_params, self.il, self.rl = compute_golden()
        with open("/app/output/z_matrix.json") as f:
            self.data = json.load(f)

    def test_frequency_count(self):
        assert len(self.data["z_parameters"]) == 5

    def test_z11_values(self):
        for i, zp in enumerate(self.data["z_parameters"]):
            Z = self.Z_params[i]
            assert zp["Z11_re"] == pytest.approx(Z[0, 0].real, abs=1e-4), \
                f"Z11_re mismatch at freq={self.freqs[i]} GHz"
            assert zp["Z11_im"] == pytest.approx(Z[0, 0].imag, abs=1e-4), \
                f"Z11_im mismatch at freq={self.freqs[i]} GHz"

    def test_z12_values(self):
        for i, zp in enumerate(self.data["z_parameters"]):
            Z = self.Z_params[i]
            assert zp["Z12_re"] == pytest.approx(Z[0, 1].real, abs=1e-4), \
                f"Z12_re mismatch at freq={self.freqs[i]} GHz"
            assert zp["Z12_im"] == pytest.approx(Z[0, 1].imag, abs=1e-4), \
                f"Z12_im mismatch at freq={self.freqs[i]} GHz"

    def test_z21_values(self):
        for i, zp in enumerate(self.data["z_parameters"]):
            Z = self.Z_params[i]
            assert zp["Z21_re"] == pytest.approx(Z[1, 0].real, abs=1e-4), \
                f"Z21_re mismatch at freq={self.freqs[i]} GHz"
            assert zp["Z21_im"] == pytest.approx(Z[1, 0].imag, abs=1e-4), \
                f"Z21_im mismatch at freq={self.freqs[i]} GHz"

    def test_z22_values(self):
        for i, zp in enumerate(self.data["z_parameters"]):
            Z = self.Z_params[i]
            assert zp["Z22_re"] == pytest.approx(Z[1, 1].real, abs=1e-4), \
                f"Z22_re mismatch at freq={self.freqs[i]} GHz"
            assert zp["Z22_im"] == pytest.approx(Z[1, 1].imag, abs=1e-4), \
                f"Z22_im mismatch at freq={self.freqs[i]} GHz"


class TestMetrics:
    """Verify insertion loss and return loss metrics."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.freqs, self.S_75, self.Z_params, self.il, self.rl = compute_golden()
        with open("/app/output/metrics.json") as f:
            self.data = json.load(f)

    def test_frequency_count(self):
        assert len(self.data["frequencies_ghz"]) == 5
        assert len(self.data["insertion_loss_db"]) == 5
        assert len(self.data["return_loss_db"]) == 5

    def test_frequencies(self):
        for i in range(5):
            assert self.data["frequencies_ghz"][i] == pytest.approx(
                self.freqs[i], abs=1e-6
            )

    def test_insertion_loss(self):
        for i in range(5):
            assert self.data["insertion_loss_db"][i] == pytest.approx(
                self.il[i], abs=1e-3
            ), f"Insertion loss mismatch at freq={self.freqs[i]} GHz"

    def test_return_loss(self):
        for i in range(5):
            assert self.data["return_loss_db"][i] == pytest.approx(
                self.rl[i], abs=1e-3
            ), f"Return loss mismatch at freq={self.freqs[i]} GHz"


class TestTouchstoneOutput:
    """Verify Touchstone v2.0 output file format and values."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.freqs, self.S_75, self.Z_params, self.il, self.rl = compute_golden()
        self.ts_path = "/app/output/cascade_output.ts"

    def test_required_keywords_present(self):
        kw, _, _, _ = parse_ts_output(self.ts_path)
        for name, present in kw.items():
            assert present, f"Missing required Touchstone v2.0 keyword: {name}"

    def test_data_order_is_12_21(self):
        with open(self.ts_path) as f:
            content = f.read()
        assert "12_21" in content, "Output must use 12_21 data ordering"

    def test_reference_impedance(self):
        _, ref_z, _, _ = parse_ts_output(self.ts_path)
        assert ref_z is not None, "Missing [Reference] values"
        assert len(ref_z) == 2, "Expected 2 reference impedance values"
        for z in ref_z:
            assert z == pytest.approx(75.0, abs=1e-6), \
                f"Reference impedance should be 75.0, got {z}"

    def test_frequency_count(self):
        _, _, n_freqs, data = parse_ts_output(self.ts_path)
        assert n_freqs == 5, f"[Number of Frequencies] should be 5, got {n_freqs}"
        assert len(data) == 5, f"Expected 5 data rows, got {len(data)}"

    def test_sparams_values(self):
        """Parse the Touchstone output and verify S-parameter values match golden."""
        _, _, _, data = parse_ts_output(self.ts_path)
        for i, row in enumerate(data):
            S = self.S_75[i]
            freq = row[0]
            assert freq == pytest.approx(self.freqs[i], abs=1e-4), \
                f"Frequency mismatch at index {i}"
            # 12_21 ordering: S11, S12, S21, S22
            assert row[1] == pytest.approx(S[0, 0].real, abs=1e-5), \
                f"S11_re mismatch at {freq} GHz"
            assert row[2] == pytest.approx(S[0, 0].imag, abs=1e-5), \
                f"S11_im mismatch at {freq} GHz"
            assert row[3] == pytest.approx(S[0, 1].real, abs=1e-5), \
                f"S12_re mismatch at {freq} GHz"
            assert row[4] == pytest.approx(S[0, 1].imag, abs=1e-5), \
                f"S12_im mismatch at {freq} GHz"
            assert row[5] == pytest.approx(S[1, 0].real, abs=1e-5), \
                f"S21_re mismatch at {freq} GHz"
            assert row[6] == pytest.approx(S[1, 0].imag, abs=1e-5), \
                f"S21_im mismatch at {freq} GHz"
            assert row[7] == pytest.approx(S[1, 1].real, abs=1e-5), \
                f"S22_re mismatch at {freq} GHz"
            assert row[8] == pytest.approx(S[1, 1].imag, abs=1e-5), \
                f"S22_im mismatch at {freq} GHz"


class TestFrequencyResponsePlot:
    """Verify SVG frequency response plot."""

    def test_valid_svg(self):
        with open("/app/output/frequency_response.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "File is not valid SVG"

    def test_has_curve_labels(self):
        with open("/app/output/frequency_response.svg") as f:
            content = f.read()
        assert "Insertion" in content, \
            "SVG missing 'Insertion' loss curve label"
        assert "Return" in content, \
            "SVG missing 'Return' loss curve label"

    def test_has_axis_labels(self):
        with open("/app/output/frequency_response.svg") as f:
            content = f.read()
        content_lower = content.lower()
        has_freq = "frequency" in content_lower or "ghz" in content_lower
        has_mag = "db" in content_lower or "magnitude" in content_lower
        assert has_freq, "SVG missing frequency axis label"
        assert has_mag, "SVG missing magnitude/dB axis label"


class TestPhysicalConsistency:
    """Verify that the cascaded result is physically reasonable."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/output/cascade_sparams.json") as f:
            self.sparams = json.load(f)
        with open("/app/output/z_matrix.json") as f:
            self.zmatrix = json.load(f)

    def test_passive_network_s_magnitude(self):
        """All S-parameter magnitudes should be <= 1 for a passive network."""
        for sp in self.sparams["s_parameters"]:
            for key_re, key_im in [
                ("S11_re", "S11_im"),
                ("S12_re", "S12_im"),
                ("S21_re", "S21_im"),
                ("S22_re", "S22_im"),
            ]:
                mag = abs(complex(sp[key_re], sp[key_im]))
                assert mag <= 1.05, \
                    f"|{key_re[:-3]}| = {mag} > 1 at freq={sp['freq_ghz']} GHz"

    def test_z_params_positive_real_diagonal(self):
        """Diagonal Z-parameters should have positive real part for passive network."""
        for zp in self.zmatrix["z_parameters"]:
            assert zp["Z11_re"] > 0, \
                f"Z11 real part negative at freq={zp['freq_ghz']} GHz"
            assert zp["Z22_re"] > 0, \
                f"Z22 real part negative at freq={zp['freq_ghz']} GHz"

    def test_insertion_loss_negative(self):
        """Insertion loss should be negative (passive network)."""
        with open("/app/output/metrics.json") as f:
            metrics = json.load(f)
        for i, il in enumerate(metrics["insertion_loss_db"]):
            assert il <= 0.01, \
                f"Insertion loss positive ({il} dB) at freq={metrics['frequencies_ghz'][i]} GHz"

    def test_return_loss_positive(self):
        """Return loss should be positive (passive network)."""
        with open("/app/output/metrics.json") as f:
            metrics = json.load(f)
        for i, rl in enumerate(metrics["return_loss_db"]):
            assert rl >= -0.01, \
                f"Return loss negative ({rl} dB) at freq={metrics['frequencies_ghz'][i]} GHz"
