
import json
import os
import subprocess
import pytest
import numpy as np
import h5py

# Reference values computed from correct frequency-domain analysis
REFERENCE_POWER_KW = {
    "1.0_6.0": 13.5142, "1.0_8.0": 19.9012, "1.0_10.0": 24.5140, "1.0_12.0": 30.1406,
    "1.5_6.0": 30.4069, "1.5_8.0": 44.7776, "1.5_10.0": 55.1566, "1.5_12.0": 67.8164,
    "2.0_6.0": 54.0567, "2.0_8.0": 79.6046, "2.0_10.0": 98.0561, "2.0_12.0": 120.5625,
    "2.5_6.0": 84.4636, "2.5_8.0": 124.3822, "2.5_10.0": 153.2127, "2.5_12.0": 188.3788,
    "3.0_6.0": 121.6276, "3.0_8.0": 179.1104, "3.0_10.0": 220.6263, "3.0_12.0": 271.2655,
    "3.5_6.0": 165.5486, "3.5_8.0": 243.7892, "3.5_10.0": 300.2969, "3.5_12.0": 369.2225,
}

REFERENCE_AEP_MWH = 630.92

POWER_RTOL = 0.05
AEP_RTOL = 0.05

HS_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
TP_VALUES = [6.0, 8.0, 10.0, 12.0]


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


# ============================================================
# Output file existence
# ============================================================
class TestOutputFilesExist:
    def test_power_matrix_exists(self):
        assert os.path.isfile("/app/power_matrix.json"), "power_matrix.json not found"

    def test_optimal_pto_exists(self):
        assert os.path.isfile("/app/optimal_pto.json"), "optimal_pto.json not found"

    def test_aep_exists(self):
        assert os.path.isfile("/app/aep.json"), "aep.json not found"

    def test_hdf5_exists(self):
        assert os.path.isfile("/app/rm3_analysis.h5"), "rm3_analysis.h5 not found"

    def test_wec_analysis_exists(self):
        assert os.path.isfile("/app/wec_analysis.py"), "wec_analysis.py not found"


# ============================================================
# Power matrix JSON schema and values
# ============================================================
class TestPowerMatrixSchema:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.data = load_json("/app/power_matrix.json")

    def test_has_hs_values(self):
        assert "Hs_values" in self.data
        assert self.data["Hs_values"] == HS_VALUES

    def test_has_tp_values(self):
        assert "Tp_values" in self.data
        assert self.data["Tp_values"] == TP_VALUES

    def test_has_power_kw(self):
        assert "power_kW" in self.data
        assert len(self.data["power_kW"]) == 24

    def test_all_keys_present(self):
        for key in REFERENCE_POWER_KW:
            assert key in self.data["power_kW"], f"Missing key {key}"

    def test_all_power_positive(self):
        for key, val in self.data["power_kW"].items():
            assert val > 0, f"Power at {key} must be positive, got {val}"


class TestPowerMatrixValues:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.data = load_json("/app/power_matrix.json")

    @pytest.mark.parametrize("key", list(REFERENCE_POWER_KW.keys()))
    def test_power_value(self, key):
        computed = self.data["power_kW"][key]
        reference = REFERENCE_POWER_KW[key]
        rel_err = abs(computed - reference) / reference
        assert rel_err < POWER_RTOL, (
            f"Power at {key}: computed={computed:.4f} kW, "
            f"reference={reference:.4f} kW, rel_err={rel_err:.4f}"
        )


# ============================================================
# Power scaling: Hs^2 for linear system
# ============================================================
class TestPowerScaling:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.data = load_json("/app/power_matrix.json")

    def test_hs_squared_scaling(self):
        """Power at Hs=3.0 should be 9x power at Hs=1.0 for same Tp."""
        for Tp in TP_VALUES:
            p1 = self.data["power_kW"][f"1.0_{Tp}"]
            p3 = self.data["power_kW"][f"3.0_{Tp}"]
            ratio = p3 / p1
            expected = 9.0
            rel_err = abs(ratio - expected) / expected
            assert rel_err < 0.05, (
                f"Tp={Tp}: P(3.0)/P(1.0)={ratio:.2f}, expected {expected:.1f}"
            )


# ============================================================
# Power monotonicity
# ============================================================
class TestPowerMonotonicity:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.pm = load_json("/app/power_matrix.json")

    def test_power_monotonicity_in_hs(self):
        for Tp in TP_VALUES:
            prev = 0
            for Hs in HS_VALUES:
                p = self.pm["power_kW"][f"{Hs}_{Tp}"]
                assert p > prev, (
                    f"Power not increasing: Hs={Hs}, Tp={Tp}, P={p}, prev={prev}"
                )
                prev = p

    def test_power_monotonicity_in_tp(self):
        for Hs in HS_VALUES:
            prev = 0
            for Tp in TP_VALUES:
                p = self.pm["power_kW"][f"{Hs}_{Tp}"]
                assert p > prev, (
                    f"Power not increasing: Hs={Hs}, Tp={Tp}, P={p}, prev={prev}"
                )
                prev = p


# ============================================================
# Optimal PTO
# ============================================================
class TestOptimalPTO:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.data = load_json("/app/optimal_pto.json")

    def test_has_optimal_bpto(self):
        assert "optimal_Bpto_MNsm" in self.data
        assert len(self.data["optimal_Bpto_MNsm"]) == 24

    def test_all_pto_positive(self):
        for key, val in self.data["optimal_Bpto_MNsm"].items():
            assert val > 0, f"Optimal B_PTO at {key} must be positive"

    def test_pto_independent_of_hs(self):
        """In linear theory, optimal B_PTO depends only on Tp, not Hs."""
        for Tp in TP_VALUES:
            values = []
            for Hs in HS_VALUES:
                key = f"{Hs}_{Tp}"
                values.append(self.data["optimal_Bpto_MNsm"][key])
            mean_val = sum(values) / len(values)
            for v in values:
                if mean_val > 0:
                    rel_err = abs(v - mean_val) / mean_val
                    assert rel_err < 0.10, (
                        f"Tp={Tp}: B_PTO varies too much across Hs: {values}"
                    )

    def test_pto_increases_with_tp(self):
        """Optimal B_PTO should increase with Tp."""
        bpto_6 = self.data["optimal_Bpto_MNsm"]["2.0_6.0"]
        bpto_12 = self.data["optimal_Bpto_MNsm"]["2.0_12.0"]
        assert bpto_12 > bpto_6, (
            f"B_PTO at Tp=12 ({bpto_12}) should exceed B_PTO at Tp=6 ({bpto_6})"
        )


# ============================================================
# AEP
# ============================================================
class TestAEP:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.data = load_json("/app/aep.json")

    def test_has_aep(self):
        assert "aep_mwh" in self.data

    def test_aep_value(self):
        computed = self.data["aep_mwh"]
        rel_err = abs(computed - REFERENCE_AEP_MWH) / REFERENCE_AEP_MWH
        assert rel_err < AEP_RTOL, (
            f"AEP: computed={computed:.2f} MWh, "
            f"reference={REFERENCE_AEP_MWH:.2f} MWh, rel_err={rel_err:.4f}"
        )

    def test_aep_positive(self):
        assert self.data["aep_mwh"] > 0


# ============================================================
# HDF5 structure and content
# ============================================================
class TestHDF5Structure:
    @pytest.fixture(autouse=True)
    def open_file(self):
        self.f = h5py.File("/app/rm3_analysis.h5", "r")
        yield
        self.f.close()

    def test_omega_shape(self):
        omega = self.f["/hydro/omega"][:]
        assert omega.shape == (260,), f"omega shape {omega.shape} != (260,)"

    def test_omega_values(self):
        omega = self.f["/hydro/omega"][:]
        assert abs(omega[0] - 0.02) < 1e-6, f"omega[0]={omega[0]}, expected 0.02"
        assert abs(omega[-1] - 5.2) < 1e-4, f"omega[-1]={omega[-1]}, expected 5.2"

    @pytest.mark.parametrize("name", ["A33", "A39", "A93", "A99"])
    def test_added_mass_shape(self, name):
        ds = self.f[f"/hydro/added_mass/{name}"][:]
        assert ds.shape == (260,), f"added_mass/{name} shape {ds.shape}"

    @pytest.mark.parametrize("name", ["B33", "B39", "B93", "B99"])
    def test_radiation_damping_shape(self, name):
        ds = self.f[f"/hydro/radiation_damping/{name}"][:]
        assert ds.shape == (260,), f"radiation_damping/{name} shape {ds.shape}"

    @pytest.mark.parametrize("name", ["F3_real", "F3_imag", "F9_real", "F9_imag"])
    def test_excitation_shape(self, name):
        ds = self.f[f"/hydro/excitation/{name}"][:]
        assert ds.shape == (260,), f"excitation/{name} shape {ds.shape}"

    def test_irf_time_shape(self):
        t = self.f["/hydro/radiation_irf/time"][:]
        assert t.shape == (1001,), f"IRF time shape {t.shape}"

    def test_irf_time_values(self):
        t = self.f["/hydro/radiation_irf/time"][:]
        assert abs(t[0]) < 1e-6
        assert abs(t[-1] - 100.0) < 1e-4

    @pytest.mark.parametrize("name", ["K33", "K39", "K93", "K99"])
    def test_irf_shape(self, name):
        K = self.f[f"/hydro/radiation_irf/{name}"][:]
        assert K.shape == (1001,), f"IRF {name} shape {K.shape}"

    def test_power_matrix_shape(self):
        pm = self.f["/results/power_kW"][:]
        assert pm.shape == (6, 4), f"power_kW shape {pm.shape}"

    def test_hs_values_shape(self):
        hs = self.f["/results/Hs_values"][:]
        assert hs.shape == (6,)

    def test_tp_values_shape(self):
        tp = self.f["/results/Tp_values"][:]
        assert tp.shape == (4,)

    def test_optimal_bpto_shape(self):
        bp = self.f["/results/optimal_Bpto_MNsm"][:]
        assert bp.shape == (6, 4), f"optimal_Bpto shape {bp.shape}"


class TestHDF5DimensionalValues:
    """Verify dimensional coefficients are correctly derived."""

    @pytest.fixture(autouse=True)
    def open_file(self):
        self.f = h5py.File("/app/rm3_analysis.h5", "r")
        yield
        self.f.close()

    def test_added_mass_a33_first(self):
        """A33[0] = A33_bar[0] * rho = 1.988329e3 * 1000."""
        A33 = self.f["/hydro/added_mass/A33"][:]
        expected = 1.988329e3 * 1000.0
        rel_err = abs(A33[0] - expected) / abs(expected)
        assert rel_err < 1e-4, f"A33[0]={A33[0]}, expected={expected}"

    def test_radiation_damping_b33_first(self):
        """B33[0] = B33_bar[0] * rho * omega[0] = 1.660938 * 1000 * 0.02."""
        B33 = self.f["/hydro/radiation_damping/B33"][:]
        expected = 1.660938 * 1000.0 * 0.02
        rel_err = abs(B33[0] - expected) / abs(expected)
        assert rel_err < 1e-4, f"B33[0]={B33[0]}, expected={expected}"

    def test_excitation_f3_real_first(self):
        """F3_real[0] = |F3_bar[0]| * rho * g * cos(phase[0]).
        Phase[0]=0 deg, so F3_real[0] = 285.4265 * 1000 * 9.81."""
        F3r = self.f["/hydro/excitation/F3_real"][:]
        expected = 285.4265 * 1000.0 * 9.81
        rel_err = abs(F3r[0] - expected) / abs(expected)
        assert rel_err < 1e-3, f"F3_real[0]={F3r[0]}, expected={expected}"


class TestHDF5IRFDecay:
    """Radiation IRFs must decay to near zero by t=100s."""

    @pytest.fixture(autouse=True)
    def open_file(self):
        self.f = h5py.File("/app/rm3_analysis.h5", "r")
        yield
        self.f.close()

    @pytest.mark.parametrize("name", ["K33", "K39", "K93", "K99"])
    def test_irf_decay(self, name):
        K = self.f[f"/hydro/radiation_irf/{name}"][:]
        peak = np.max(np.abs(K))
        if peak > 0:
            ratio = abs(K[-1]) / peak
            assert ratio < 0.01, (
                f"IRF {name} not decayed: |K(100)|/peak = {ratio:.4f}"
            )


class TestHDF5ConsistencyWithJSON:
    """HDF5 result datasets must match JSON outputs."""

    @pytest.fixture(autouse=True)
    def load_all(self):
        self.f = h5py.File("/app/rm3_analysis.h5", "r")
        self.pm_json = load_json("/app/power_matrix.json")
        self.pto_json = load_json("/app/optimal_pto.json")
        yield
        self.f.close()

    def test_power_matrix_matches_json(self):
        pm_h5 = self.f["/results/power_kW"][:]
        for i, Hs in enumerate(HS_VALUES):
            for j, Tp in enumerate(TP_VALUES):
                key = f"{Hs}_{Tp}"
                h5_val = pm_h5[i, j]
                json_val = self.pm_json["power_kW"][key]
                assert abs(h5_val - json_val) < 0.1, (
                    f"Mismatch at {key}: HDF5={h5_val}, JSON={json_val}"
                )

    def test_optimal_bpto_matches_json(self):
        bp_h5 = self.f["/results/optimal_Bpto_MNsm"][:]
        for i, Hs in enumerate(HS_VALUES):
            for j, Tp in enumerate(TP_VALUES):
                key = f"{Hs}_{Tp}"
                h5_val = bp_h5[i, j]
                json_val = self.pto_json["optimal_Bpto_MNsm"][key]
                assert abs(h5_val - json_val) < 0.01, (
                    f"Mismatch at {key}: HDF5={h5_val}, JSON={json_val}"
                )


# ============================================================
# CLI query mode
# ============================================================
class TestCLIQueryMode:
    """Test the wec_analysis.py query mode."""

    def _query(self, hs, tp, bpto):
        result = subprocess.run(
            ["python3", "/app/wec_analysis.py", "query", str(hs), str(tp), str(bpto)],
            capture_output=True, text=True, cwd="/app", timeout=120,
        )
        assert result.returncode == 0, f"Query failed: {result.stderr}"
        data = json.loads(result.stdout.strip().split("\n")[-1])
        assert "power_kW" in data
        return data["power_kW"]

    def test_query_returns_positive_power(self):
        power = self._query(2.0, 8.0, 1200000)
        assert power > 0, f"Query power should be positive, got {power}"

    def test_query_at_optimal_matches_matrix(self):
        """Query at optimal Bpto should match the power matrix value."""
        pto_data = load_json("/app/optimal_pto.json")
        opt_bpto_mnsm = pto_data["optimal_Bpto_MNsm"]["2.0_8.0"]
        opt_bpto = opt_bpto_mnsm * 1e6  # MN·s/m to N·s/m
        power_query = self._query(2.0, 8.0, opt_bpto)
        pm = load_json("/app/power_matrix.json")
        ref = pm["power_kW"]["2.0_8.0"]
        rel_err = abs(power_query - ref) / ref
        assert rel_err < 0.02, (
            f"Query at optimal: {power_query:.4f} vs matrix: {ref:.4f}, err={rel_err:.4f}"
        )

    def test_query_suboptimal_less_power(self):
        """Power at minimum Bpto must be less than optimal."""
        pm = load_json("/app/power_matrix.json")
        opt_power = pm["power_kW"]["2.0_8.0"]
        subopt_power = self._query(2.0, 8.0, 50000)
        assert subopt_power < opt_power, (
            f"Suboptimal power {subopt_power} should be < optimal {opt_power}"
        )

    def test_query_different_sea_state(self):
        """Query for a different sea state also returns positive power."""
        power = self._query(3.5, 12.0, 5000000)
        assert power > 0
