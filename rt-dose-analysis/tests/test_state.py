"""Verify radiotherapy dose analysis against reference implementations.

Reference implementations use scipy, matplotlib, and numpy to produce
golden values independently. All tolerances are chosen so that correct
implementations pass and incorrect ones (wrong units, wrong contour
handling, missing interpolation) reliably fail.
"""

import json
import math
import os

import numpy as np
import pytest
from matplotlib.path import Path as MplPath
from scipy.ndimage import map_coordinates

DATA_DIR = "/app/data"
RESULTS_FILE = "/app/results/analysis.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_dose_grid(path):
    """Load a dose grid, converting to Gy if needed."""
    data = load_json(path)
    dose = np.array(data["dose"], dtype=np.float64)
    unit = data.get("dose_unit", "Gy")
    if unit.lower() == "cgy":
        dose /= 100.0
    spacing = np.array(data["spacing"], dtype=np.float64)
    origin = np.array(data["origin"], dtype=np.float64)
    x = origin[0] + np.arange(data["nx"]) * spacing[0]
    y = origin[1] + np.arange(data["ny"]) * spacing[1]
    z = origin[2] + np.arange(data["nz"]) * spacing[2]
    return dose, (x, y, z), spacing


def get_structure_doses(dose, axes, spacing, contours):
    """Get dose values for voxels inside a structure (XOR multi-contour)."""
    x, y, z = axes
    all_doses = []
    for z_key, slice_contours in contours.items():
        z_val = float(z_key)
        z_idx = int(np.argmin(np.abs(z - z_val)))
        if abs(z[z_idx] - z_val) > spacing[2] / 2.0 + 0.01:
            continue
        xx, yy = np.meshgrid(x, y, indexing="ij")
        pts = np.column_stack([xx.ravel(), yy.ravel()])
        mask = np.zeros(len(pts), dtype=bool)
        for cd in slice_contours:
            poly = MplPath([(p[0], p[1]) for p in cd["data"]])
            mask = np.logical_xor(mask, poly.contains_points(pts))
        mask = mask.reshape(xx.shape)
        all_doses.extend(dose[:, :, z_idx][mask].tolist())
    return np.array(all_doses) if all_doses else np.array([])


def ref_interp_onto(target_axes, source_dose, source_axes, source_spacing):
    """Interpolate source grid onto target coordinate system."""
    fi = (target_axes[0] - source_axes[0][0]) / source_spacing[0]
    fj = (target_axes[1] - source_axes[1][0]) / source_spacing[1]
    fk = (target_axes[2] - source_axes[2][0]) / source_spacing[2]
    FI, FJ, FK = np.meshgrid(fi, fj, fk, indexing="ij")
    coords = np.array([FI.ravel(), FJ.ravel(), FK.ravel()])
    interp = map_coordinates(source_dose, coords, order=1,
                             mode="constant", cval=0.0)
    return interp.reshape(len(target_axes[0]), len(target_axes[1]),
                          len(target_axes[2]))


def ref_gamma(ref_dose, ref_axes, eval_dose, eval_axes,
              dose_pct, dist_mm, lower_pct, local=False):
    """Brute-force vectorised 3D gamma (per reference point)."""
    rx, ry, rz = ref_axes
    ex, ey, ez = eval_axes
    max_ref = float(np.max(ref_dose))
    lower_cutoff = lower_pct / 100.0 * max_ref
    dose_thresh = dose_pct / 100.0 * max_ref

    ri, rj, rk = np.where(ref_dose >= lower_cutoff)
    n_ref = len(ri)
    if n_ref == 0:
        return 100.0, 0, 0.0, 0.0

    EX, EY, EZ = np.meshgrid(ex, ey, ez, indexing="ij")
    ef_x, ef_y, ef_z = EX.ravel(), EY.ravel(), EZ.ravel()
    ed = eval_dose.ravel()

    gamma_mins = np.full(n_ref, np.inf)
    for idx in range(n_ref):
        px, py, pz = rx[ri[idx]], ry[rj[idx]], rz[rk[idx]]
        pd = ref_dose[ri[idx], rj[idx], rk[idx]]
        dists = np.sqrt((ef_x - px) ** 2 + (ef_y - py) ** 2 +
                        (ef_z - pz) ** 2)
        dd = ed - pd
        dt = (dose_pct / 100.0 * pd) if local else dose_thresh
        gamma = np.sqrt((dd / dt) ** 2 + (dists / dist_mm) ** 2)
        gamma_mins[idx] = np.min(gamma)

    pass_rate = float(np.sum(gamma_mins <= 1.0)) / n_ref * 100.0
    return pass_rate, n_ref, float(np.mean(gamma_mins)), float(np.max(gamma_mins))


def ref_max_boost_factor(primary_dose, p_axes, p_spacing,
                         boost_dose, b_axes, b_spacing,
                         structures, constraints):
    """Find max boost factor keeping all OAR constraints satisfied."""
    boost_on_p = ref_interp_onto(p_axes, boost_dose, b_axes, b_spacing)
    voxel_vol = float(np.prod(p_spacing)) / 1000.0
    max_s = float("inf")

    for sname, sdata in structures.items():
        if sdata.get("type") != "OAR" or sname not in constraints:
            continue
        p_d = get_structure_doses(primary_dose, p_axes, p_spacing,
                                 sdata["contours"])
        b_d = get_structure_doses(boost_on_p, p_axes, p_spacing,
                                 sdata["contours"])
        if len(p_d) == 0 or len(b_d) == 0:
            continue

        sc = constraints[sname]

        # Dmax constraint — per-voxel analytical
        if "Dmax_gy_max" in sc:
            lim = sc["Dmax_gy_max"]
            for i in range(len(p_d)):
                if b_d[i] > 1e-10:
                    max_s = min(max_s, (lim - p_d[i]) / b_d[i])

        # Dmean constraint — analytical
        if "Dmean_gy_max" in sc:
            lim = sc["Dmean_gy_max"]
            mb = float(np.mean(b_d))
            if mb > 1e-10:
                max_s = min(max_s, (lim - float(np.mean(p_d))) / mb)

        # V30 constraint — bisection
        if "V30_gy_pct_max" in sc:
            lim_pct = sc["V30_gy_pct_max"]
            v30_0 = float(np.sum(p_d >= 30.0)) / len(p_d) * 100.0
            if v30_0 > lim_pct:
                max_s = min(max_s, 0.0)
            else:
                lo, hi = 0.0, 1000.0
                for _ in range(100):
                    mid = (lo + hi) / 2
                    v30 = (float(np.sum(p_d + mid * b_d >= 30.0))
                           / len(p_d) * 100.0)
                    if v30 <= lim_pct:
                        lo = mid
                    else:
                        hi = mid
                max_s = min(max_s, lo)

        # D0.1cc constraint — bisection
        if "D0_1cc_gy_max" in sc:
            lim = sc["D0_1cc_gy_max"]
            n_01cc = int(math.ceil(0.1 / voxel_vol))
            sorted_p = np.sort(p_d)
            d01_0 = float(sorted_p[0] if n_01cc >= len(sorted_p)
                          else sorted_p[-n_01cc])
            if d01_0 > lim:
                max_s = min(max_s, 0.0)
            else:
                lo, hi = 0.0, 1000.0
                for _ in range(100):
                    mid = (lo + hi) / 2
                    combined = np.sort(p_d + mid * b_d)
                    d01 = float(combined[0] if n_01cc >= len(combined)
                                else combined[-n_01cc])
                    if d01 <= lim:
                        lo = mid
                    else:
                        hi = mid
                max_s = min(max_s, lo)

    return max(0.0, max_s) if max_s != float("inf") else 0.0


# ===================================================================
# Tests
# ===================================================================

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_FILE), \
            f"Results file not found at {RESULTS_FILE}"

    def test_results_valid_json(self):
        r = load_json(RESULTS_FILE)
        assert isinstance(r, dict)
        for key in ("structures", "dose_summation", "gamma",
                     "protocol_compliance"):
            assert key in r, f"Missing top-level key '{key}'"

    def test_structure_keys_present(self):
        s = load_json(RESULTS_FILE)["structures"]
        for name in ("PTV", "Heart", "SpinalCord"):
            assert name in s, f"Missing structure '{name}'"


class TestPTV:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["structures"]["PTV"]
        dose, axes, spacing = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        structs = load_json(f"{DATA_DIR}/structures.json")
        doses = get_structure_doses(dose, axes, spacing,
                                    structs["PTV"]["contours"])
        vv = float(np.prod(spacing)) / 1000.0
        self.ref_vol = len(doses) * vv
        self.ref_D95 = float(np.percentile(doses, 5))
        self.ref_Dmean = float(np.mean(doses))
        self.ref_Dmax = float(np.max(doses))

    def test_has_required_keys(self):
        for k in ("volume_cm3", "D95_gy", "Dmean_gy", "Dmax_gy"):
            assert k in self.results, f"Missing PTV key '{k}'"

    def test_volume(self):
        v = self.results["volume_cm3"]
        assert abs(v - self.ref_vol) / self.ref_vol < 0.15, \
            f"PTV volume {v:.4f} differs >15% from {self.ref_vol:.4f}"

    def test_d95(self):
        d = self.results["D95_gy"]
        tol = max(2.0, 0.12 * self.ref_D95)
        assert abs(d - self.ref_D95) < tol

    def test_dmean(self):
        d = self.results["Dmean_gy"]
        tol = max(1.0, 0.08 * self.ref_Dmean)
        assert abs(d - self.ref_Dmean) < tol

    def test_dmax(self):
        d = self.results["Dmax_gy"]
        tol = max(0.5, 0.05 * self.ref_Dmax)
        assert abs(d - self.ref_Dmax) < tol

    def test_ordering(self):
        assert self.results["D95_gy"] <= self.results["Dmean_gy"] + 0.01
        assert self.results["Dmean_gy"] <= self.results["Dmax_gy"] + 0.01


class TestHeart:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["structures"]["Heart"]
        dose, axes, spacing = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        structs = load_json(f"{DATA_DIR}/structures.json")
        doses = get_structure_doses(dose, axes, spacing,
                                    structs["Heart"]["contours"])
        vv = float(np.prod(spacing)) / 1000.0
        self.ref_vol = len(doses) * vv
        self.ref_Dmean = float(np.mean(doses))
        self.ref_Dmax = float(np.max(doses))
        self.ref_V30 = float(np.sum(doses >= 30.0)) / len(doses) * 100.0

    def test_has_required_keys(self):
        for k in ("volume_cm3", "Dmean_gy", "Dmax_gy", "V30_gy_pct"):
            assert k in self.results, f"Missing Heart key '{k}'"

    def test_volume(self):
        v = self.results["volume_cm3"]
        assert abs(v - self.ref_vol) / self.ref_vol < 0.15

    def test_dmean(self):
        d = self.results["Dmean_gy"]
        tol = max(1.0, 0.10 * self.ref_Dmean)
        assert abs(d - self.ref_Dmean) < tol

    def test_dmax(self):
        d = self.results["Dmax_gy"]
        tol = max(0.5, 0.05 * self.ref_Dmax)
        assert abs(d - self.ref_Dmax) < tol

    def test_v30(self):
        v = self.results["V30_gy_pct"]
        assert abs(v - self.ref_V30) < 8.0, \
            f"Heart V30 {v:.2f}% differs >8pp from {self.ref_V30:.2f}%"


class TestSpinalCord:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["structures"]["SpinalCord"]
        dose, axes, spacing = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        structs = load_json(f"{DATA_DIR}/structures.json")
        doses = get_structure_doses(dose, axes, spacing,
                                    structs["SpinalCord"]["contours"])
        vv = float(np.prod(spacing)) / 1000.0
        self.ref_vol = len(doses) * vv
        self.ref_Dmax = float(np.max(doses))
        n_01cc = int(math.ceil(0.1 / vv))
        sorted_d = np.sort(doses)
        self.ref_D0_1cc = float(
            sorted_d[0] if n_01cc >= len(sorted_d) else sorted_d[-n_01cc])

    def test_has_required_keys(self):
        for k in ("volume_cm3", "Dmax_gy", "D0_1cc_gy"):
            assert k in self.results, f"Missing SpinalCord key '{k}'"

    def test_volume(self):
        v = self.results["volume_cm3"]
        assert abs(v - self.ref_vol) / self.ref_vol < 0.15

    def test_dmax(self):
        d = self.results["Dmax_gy"]
        tol = max(0.5, 0.05 * self.ref_Dmax)
        assert abs(d - self.ref_Dmax) < tol

    def test_d0_1cc(self):
        d = self.results["D0_1cc_gy"]
        tol = max(1.0, 0.10 * self.ref_D0_1cc)
        assert abs(d - self.ref_D0_1cc) < tol

    def test_d0_1cc_le_dmax(self):
        assert self.results["D0_1cc_gy"] <= self.results["Dmax_gy"] + 0.01


class TestDoseSummation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["dose_summation"]
        dp, ap, sp = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        ds, a_s, ss = load_dose_grid(f"{DATA_DIR}/dose_secondary.json")
        interp_s = ref_interp_onto(ap, ds, a_s, ss)
        self.ref_sum = dp + interp_s

    def test_has_required_keys(self):
        for k in ("max_dose_gy", "mean_dose_gy"):
            assert k in self.results

    def test_max_dose(self):
        rm = float(np.max(self.ref_sum))
        sm = self.results["max_dose_gy"]
        assert abs(sm - rm) / rm < 0.10, \
            f"Sum max {sm:.4f} differs >10% from {rm:.4f}"

    def test_mean_dose(self):
        rm = float(np.mean(self.ref_sum))
        sm = self.results["mean_dose_gy"]
        tol = max(0.5, 0.15 * rm)
        assert abs(sm - rm) < tol

    def test_max_ge_mean(self):
        assert self.results["max_dose_gy"] >= \
            self.results["mean_dose_gy"] - 0.01


class TestGamma:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["gamma"]
        protocol = load_json(f"{DATA_DIR}/protocol.json")
        gc = protocol["gamma"]
        dp, ap, _ = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        ds, a_s, _ = load_dose_grid(f"{DATA_DIR}/dose_secondary.json")
        local = gc.get("normalization", "global") == "local"
        self.ref_rate, self.ref_n, self.ref_mean, self.ref_max = ref_gamma(
            dp, ap, ds, a_s,
            gc["dose_threshold_pct"], gc["distance_threshold_mm"],
            gc["lower_dose_cutoff_pct"], local)

    def test_has_required_keys(self):
        for k in ("pass_rate_pct", "mean_gamma", "max_gamma",
                   "evaluated_points"):
            assert k in self.results

    def test_pass_rate(self):
        sr = self.results["pass_rate_pct"]
        assert abs(sr - self.ref_rate) < 5.0, \
            f"Gamma pass rate {sr:.2f}% differs >5pp from {self.ref_rate:.2f}%"

    def test_evaluated_points(self):
        sp = self.results["evaluated_points"]
        assert abs(sp - self.ref_n) / max(self.ref_n, 1) < 0.15

    def test_mean_gamma(self):
        sm = self.results["mean_gamma"]
        tol = max(0.5, 0.20 * self.ref_mean)
        assert abs(sm - self.ref_mean) < tol

    def test_pass_rate_bounds(self):
        assert 0 <= self.results["pass_rate_pct"] <= 100


class TestProtocolCompliance:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_json(RESULTS_FILE)["protocol_compliance"]
        protocol = load_json(f"{DATA_DIR}/protocol.json")
        structs = load_json(f"{DATA_DIR}/structures.json")
        dp, ap, sp = load_dose_grid(f"{DATA_DIR}/dose_primary.json")
        db, ab, sb = load_dose_grid(f"{DATA_DIR}/dose_boost.json")
        constraints = protocol["constraints"]
        vv = float(np.prod(sp)) / 1000.0

        ptv_d = get_structure_doses(dp, ap, sp,
                                    structs["PTV"]["contours"])
        heart_d = get_structure_doses(dp, ap, sp,
                                      structs["Heart"]["contours"])
        cord_d = get_structure_doses(dp, ap, sp,
                                     structs["SpinalCord"]["contours"])

        self.ref_PTV_D95 = (float(np.percentile(ptv_d, 5))
                            >= constraints["PTV"]["D95_gy_min"])
        self.ref_Heart_Dmean = (float(np.mean(heart_d))
                                <= constraints["Heart"]["Dmean_gy_max"])
        self.ref_Heart_V30 = (
            float(np.sum(heart_d >= 30.0)) / len(heart_d) * 100.0
            <= constraints["Heart"]["V30_gy_pct_max"])
        self.ref_SC_Dmax = (float(np.max(cord_d))
                            <= constraints["SpinalCord"]["Dmax_gy_max"])
        n01 = int(math.ceil(0.1 / vv))
        s_cd = np.sort(cord_d)
        d01 = float(s_cd[0] if n01 >= len(s_cd) else s_cd[-n01])
        self.ref_SC_D01 = d01 <= constraints["SpinalCord"]["D0_1cc_gy_max"]
        self.ref_overall = all([self.ref_PTV_D95, self.ref_Heart_Dmean,
                                self.ref_Heart_V30, self.ref_SC_Dmax,
                                self.ref_SC_D01])
        self.ref_boost = ref_max_boost_factor(
            dp, ap, sp, db, ab, sb, structs, constraints)

    def test_has_required_keys(self):
        for k in ("PTV_D95", "Heart_Dmean", "Heart_V30",
                   "SpinalCord_Dmax", "SpinalCord_D0_1cc",
                   "overall_pass", "max_boost_factor"):
            assert k in self.results, \
                f"Missing protocol_compliance key '{k}'"

    def test_ptv_d95(self):
        assert self.results["PTV_D95"] == self.ref_PTV_D95

    def test_heart_dmean(self):
        assert self.results["Heart_Dmean"] == self.ref_Heart_Dmean

    def test_heart_v30(self):
        assert self.results["Heart_V30"] == self.ref_Heart_V30

    def test_sc_dmax(self):
        assert self.results["SpinalCord_Dmax"] == self.ref_SC_Dmax

    def test_sc_d01cc(self):
        assert self.results["SpinalCord_D0_1cc"] == self.ref_SC_D01

    def test_overall_pass(self):
        assert self.results["overall_pass"] == self.ref_overall

    def test_max_boost_factor(self):
        ref = self.ref_boost
        val = self.results["max_boost_factor"]
        if ref < 0.01:
            assert val < 0.1, \
                f"max_boost_factor should be ~0 but got {val}"
        else:
            tol = max(0.5, 0.20 * ref)
            assert abs(val - ref) < tol, \
                f"max_boost_factor {val:.4f} differs >{tol:.2f} from " \
                f"reference {ref:.4f}"

    def test_max_boost_factor_nonneg(self):
        assert self.results["max_boost_factor"] >= 0.0


class TestConsistency:
    """Sanity checks independent of reference implementation."""

    def test_structure_volumes_positive(self):
        s = load_json(RESULTS_FILE)["structures"]
        for name in ("PTV", "Heart", "SpinalCord"):
            assert s[name]["volume_cm3"] > 0, \
                f"{name} volume must be positive"

    def test_ptv_dose_positive(self):
        ptv = load_json(RESULTS_FILE)["structures"]["PTV"]
        assert ptv["Dmax_gy"] > 0
        assert ptv["Dmean_gy"] > 0

    def test_gamma_positive(self):
        g = load_json(RESULTS_FILE)["gamma"]
        assert g["evaluated_points"] > 0
        assert g["mean_gamma"] >= 0

    def test_summation_positive(self):
        ds = load_json(RESULTS_FILE)["dose_summation"]
        assert ds["max_dose_gy"] > 0
        assert ds["mean_dose_gy"] > 0

    def test_unit_conversion_plausible(self):
        """Dose summation max should be reasonable; catches cGy vs Gy bugs."""
        ds = load_json(RESULTS_FILE)["dose_summation"]
        assert ds["max_dose_gy"] < 500, \
            f"Sum max {ds['max_dose_gy']:.1f} Gy implausibly high — " \
            f"possible unit conversion error"

    def test_summation_includes_secondary(self):
        """Sum should exceed primary-only max (~60 Gy)."""
        ds = load_json(RESULTS_FILE)["dose_summation"]
        assert ds["max_dose_gy"] > 80, \
            "Sum too low — secondary contribution may be missing"
