
import json
import os
import pickle
import pytest

RESULTS_DIR = "/app/results"
REF_PATH = "/opt/cfd_data/.ref.pkl"
DNA_FP_PATH = "/opt/cfd_data/.dna_fingerprint"

# Load build-time reference answers (DNA-parameterised, no hardcoded values)
with open(REF_PATH, "rb") as _rf:
    _REF = pickle.load(_rf)


def load_json(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), f"Expected output file {path} does not exist"
    with open(path) as f:
        return json.load(f)


def rel_err(computed, expected):
    if expected == 0:
        return abs(computed)
    return abs(computed - expected) / abs(expected)


# ============================================================
# DNA Verification — ensure data was generated from build-time seed
# ============================================================
class TestDNA:
    def test_dna_fingerprint_exists(self):
        assert os.path.exists(DNA_FP_PATH), "DNA fingerprint file missing"

    def test_ref_contains_dna(self):
        assert "dna_fingerprint" in _REF, "Reference missing DNA fingerprint"

    def test_dna_consistency(self):
        with open(DNA_FP_PATH) as f:
            fp = f.read().strip()
        assert fp == _REF["dna_fingerprint"], "DNA fingerprint mismatch"


# ============================================================
# BL Analysis Tests
# ============================================================
class TestBLAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("bl_analysis.json")
        self.ref = _REF["bl_analysis"]

    def test_required_keys(self):
        required = ["delta_star", "theta", "shape_factor", "u_tau", "Cf"]
        for key in required:
            assert key in self.data, f"Missing key '{key}' in bl_analysis.json"

    def test_delta_star(self):
        ds = self.data["delta_star"]
        assert isinstance(ds, (int, float)), "delta_star must be numeric"
        assert ds > 0, "delta_star must be positive"
        assert rel_err(ds, self.ref["delta_star"]) < 0.08, (
            f"delta_star={ds:.7f} deviates >8% from reference {self.ref['delta_star']:.7f}"
        )

    def test_theta(self):
        th = self.data["theta"]
        assert isinstance(th, (int, float)), "theta must be numeric"
        assert th > 0, "theta must be positive"
        assert rel_err(th, self.ref["theta"]) < 0.08, (
            f"theta={th:.7f} deviates >8% from reference {self.ref['theta']:.7f}"
        )

    def test_shape_factor(self):
        H = self.data["shape_factor"]
        assert isinstance(H, (int, float)), "shape_factor must be numeric"
        assert 1.0 < H < 3.0, f"shape_factor={H:.4f} outside physical range [1.0, 3.0]"
        assert rel_err(H, self.ref["shape_factor"]) < 0.05, (
            f"shape_factor={H:.4f} deviates >5% from reference {self.ref['shape_factor']:.4f}"
        )

    def test_u_tau(self):
        ut = self.data["u_tau"]
        assert isinstance(ut, (int, float)), "u_tau must be numeric"
        assert ut > 0, "u_tau must be positive"
        assert rel_err(ut, self.ref["u_tau"]) < 0.05, (
            f"u_tau={ut:.5f} deviates >5% from reference {self.ref['u_tau']:.5f}"
        )

    def test_cf(self):
        cf = self.data["Cf"]
        assert isinstance(cf, (int, float)), "Cf must be numeric"
        assert cf > 0, "Cf must be positive"
        # Internal consistency: Cf = 2*(u_tau/U_e)^2
        with open("/opt/cfd_data/config.json") as f:
            cfg = json.load(f)
        U_e = cfg["flow_conditions"]["U_e"]
        ut = self.data["u_tau"]
        cf_from_ut = 2.0 * (ut / U_e) ** 2
        assert rel_err(cf, cf_from_ut) < 0.01, (
            f"Cf={cf:.7f} inconsistent with u_tau={ut:.5f}"
        )
        assert rel_err(cf, self.ref["Cf"]) < 0.10, (
            f"Cf={cf:.7f} deviates >10% from reference {self.ref['Cf']:.7f}"
        )

    def test_physical_consistency(self):
        assert self.data["delta_star"] > self.data["theta"], (
            "delta_star must be greater than theta"
        )


# ============================================================
# Grid Convergence Tests (SA model)
# ============================================================
class TestGridConvergenceSA:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("grid_convergence_sa.json")
        self.ref_st = _REF["grid_convergence_sa"]["stations"]

    def test_has_stations(self):
        assert "stations" in self.data, "Missing 'stations' key"
        assert len(self.data["stations"]) == len(self.ref_st), (
            f"Expected {len(self.ref_st)} stations, got {len(self.data['stations'])}"
        )

    def test_station_keys(self):
        required = ["x", "p", "f_ext", "gci_fine", "asymp_ratio"]
        for station in self.data["stations"]:
            for key in required:
                assert key in station, f"Missing '{key}' at station x={station.get('x', '?')}"

    @pytest.mark.parametrize("idx", range(7))
    def test_observed_order(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["p"], expected["p"]) < 0.02, (
            f"SA x={expected['x']}: p={station['p']:.6f}, ref {expected['p']:.6f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_extrapolated_value(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["f_ext"], expected["f_ext"]) < 0.01, (
            f"SA x={expected['x']}: f_ext={station['f_ext']:.8f}, ref {expected['f_ext']:.8f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_gci(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["gci_fine"], expected["gci_fine"]) < 0.05, (
            f"SA x={expected['x']}: GCI={station['gci_fine']:.8f}, ref {expected['gci_fine']:.8f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_asymptotic_range(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["asymp_ratio"], expected["asymp_ratio"]) < 0.02, (
            f"SA x={expected['x']}: asymp={station['asymp_ratio']:.6f}, ref {expected['asymp_ratio']:.6f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_order_physical_range(self, idx):
        p = self.data["stations"][idx]["p"]
        assert 0.5 < p < 4.0, f"Order p={p:.4f} outside physical range"


# ============================================================
# Grid Convergence Tests (SST model)
# ============================================================
class TestGridConvergenceSST:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("grid_convergence_sst.json")
        self.ref_st = _REF["grid_convergence_sst"]["stations"]

    def test_has_stations(self):
        assert "stations" in self.data, "Missing 'stations' key"
        assert len(self.data["stations"]) == len(self.ref_st), (
            f"Expected {len(self.ref_st)} stations, got {len(self.data['stations'])}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_observed_order(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["p"], expected["p"]) < 0.02, (
            f"SST x={expected['x']}: p={station['p']:.6f}, ref {expected['p']:.6f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_extrapolated_value(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["f_ext"], expected["f_ext"]) < 0.01, (
            f"SST x={expected['x']}: f_ext={station['f_ext']:.8f}, ref {expected['f_ext']:.8f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_gci(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["gci_fine"], expected["gci_fine"]) < 0.05, (
            f"SST x={expected['x']}: GCI={station['gci_fine']:.8f}, ref {expected['gci_fine']:.8f}"
        )

    @pytest.mark.parametrize("idx", range(7))
    def test_asymptotic_range(self, idx):
        station = self.data["stations"][idx]
        expected = self.ref_st[idx]
        assert rel_err(station["asymp_ratio"], expected["asymp_ratio"]) < 0.02, (
            f"SST x={expected['x']}: asymp={station['asymp_ratio']:.6f}, ref {expected['asymp_ratio']:.6f}"
        )


# ============================================================
# Model Comparison Tests
# ============================================================
class TestModelComparison:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("model_comparison.json")
        self.ref = _REF["model_comparison"]

    def test_required_keys(self):
        for key in ["rms_rel_diff_pct", "max_rel_diff_pct", "max_diff_station"]:
            assert key in self.data, f"Missing key '{key}' in model_comparison.json"

    def test_rms_diff(self):
        rms = self.data["rms_rel_diff_pct"]
        assert isinstance(rms, (int, float))
        assert rel_err(rms, self.ref["rms_rel_diff_pct"]) < 0.05, (
            f"rms_rel_diff_pct={rms:.4f}%, ref {self.ref['rms_rel_diff_pct']:.4f}%"
        )

    def test_max_diff(self):
        mx = self.data["max_rel_diff_pct"]
        assert isinstance(mx, (int, float))
        assert rel_err(mx, self.ref["max_rel_diff_pct"]) < 0.05, (
            f"max_rel_diff_pct={mx:.4f}%, ref {self.ref['max_rel_diff_pct']:.4f}%"
        )

    def test_max_diff_station(self):
        station = self.data["max_diff_station"]
        assert abs(station - self.ref["max_diff_station"]) < 0.01, (
            f"max_diff_station={station}, ref {self.ref['max_diff_station']}"
        )

    def test_has_station_diffs(self):
        assert "stations" in self.data, "Missing 'stations' key"
        assert len(self.data["stations"]) == len(self.ref["stations"]), (
            f"Expected {len(self.ref['stations'])} stations"
        )

    def test_station_diff_values(self):
        for s in self.data["stations"]:
            assert "x" in s
            assert "sa_ext" in s
            assert "sst_ext" in s
            assert "rel_diff_pct" in s
            assert s["rel_diff_pct"] >= 0, "rel_diff_pct must be non-negative"
