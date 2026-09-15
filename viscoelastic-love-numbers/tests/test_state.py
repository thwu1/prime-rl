
import os
import csv
import json
import math
import numpy as np
import pytest


REF_DIR = "/app/taboo_reference"
OUT_DIR = "/app/output"
SPEC_PATH = "/app/model_spec.json"

with open(SPEC_PATH) as _f:
    _spec = json.load(_f)
LMIN = _spec["lmin"]
LMAX = _spec["lmax"]
TIME_POINTS = _spec["time_points_kyr"]
NV = _spec["nv"]

ELASTIC_RTOL = 1e-6
FLUID_RTOL = 1e-5
SPECTRUM_RTOL = 1e-3
HEAVISIDE_RTOL = 5e-4
HEAVISIDE_ATOL = 1e-10


# ============================================================
# Parsers for TABOO reference output files
# ============================================================

def parse_taboo_spectrum(filepath):
    """Parse TABOO spectrum.dat.
    Returns dict: degree -> list of (mode_kk_0based, s_value) for ALL modes,
    in order kk=1..nroots (0-indexed here).
    """
    modes = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                deg = int(parts[0])
                s_val = float(parts[2])
            except (ValueError, IndexError):
                continue
            modes.setdefault(deg, []).append(s_val)
    return modes


def parse_taboo_love(filepath):
    """Parse TABOO h/l/k.dat with El_Fluid_Viscel output.
    Returns dict: degree -> (elastic, fluid, [residue_1, ..., residue_nroots]).
    """
    result = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                deg = int(parts[0])
                elastic = float(parts[1])
                fluid = float(parts[2])
                residues = [float(x) for x in parts[3:]]
            except (ValueError, IndexError):
                continue
            result[deg] = (elastic, fluid, residues)
    return result


def physical_modes_for_degree(all_s_values):
    """Filter physical modes (s < 0) from all modes.
    Returns list of (original_index_0based, s_value) for physical modes.
    """
    physical = []
    for idx, s_val in enumerate(all_s_values):
        if s_val < 0:
            physical.append((idx, s_val))
    return sorted(physical, key=lambda x: x[1])


def compute_heaviside(h_elastic, s_values, residues, t):
    """Compute Heaviside response at time t.
    h^H(l,t) = h_e + sum_k [h_v_k / s_k * (exp(s_k * t) - 1)]
    Only uses physical modes (s < 0).
    """
    val = h_elastic
    for idx, s_val in enumerate(s_values):
        if s_val < 0 and idx < len(residues):
            h_v = residues[idx]
            val += (h_v / s_val) * (math.exp(s_val * t) - 1.0)
    return val


# ============================================================
# Parsers for solver output CSV files
# ============================================================

def parse_solver_modes(filepath):
    """Parse solver modes.csv -> dict: degree -> list of s_kyr_inv sorted ascending."""
    modes = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            deg = int(row["degree"])
            s_val = float(row["s_kyr_inv"])
            modes.setdefault(deg, []).append(s_val)
    for deg in modes:
        modes[deg] = sorted(modes[deg])
    return modes


def parse_solver_love(filepath):
    """Parse solver love_numbers.csv -> dict: degree -> dict of column values."""
    result = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            deg = int(row["degree"])
            result[deg] = {k: float(v) for k, v in row.items() if k != "degree"}
    return result


def parse_solver_heaviside(filepath):
    """Parse solver heaviside CSV -> dict: (degree, t_kyr) -> value."""
    result = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            deg = int(row["degree"])
            t = float(row["t_kyr"])
            val = float(row["value"])
            result[(deg, t)] = val
    return result


def relative_error(computed, reference):
    if abs(reference) < 1e-30:
        return abs(computed - reference)
    return abs(computed - reference) / abs(reference)


def match_modes(sol_modes, ref_modes, rtol):
    """Match solver modes to reference modes. Returns number matched."""
    if not sol_modes or not ref_modes:
        return 0
    matched = 0
    used_ref = set()
    for s_sol in sol_modes:
        best_err = float("inf")
        best_idx = -1
        for i, s_ref in enumerate(ref_modes):
            if i in used_ref:
                continue
            err = relative_error(s_sol, s_ref)
            if err < best_err:
                best_err = err
                best_idx = i
        if best_idx >= 0 and best_err < rtol:
            matched += 1
            used_ref.add(best_idx)
    return matched


# ============================================================
# Test: TABOO reference files exist
# ============================================================

class TestTabooReference:
    def test_taboo_spectrum_exists(self):
        assert os.path.exists(os.path.join(REF_DIR, "spectrum.dat"))

    def test_taboo_h_exists(self):
        assert os.path.exists(os.path.join(REF_DIR, "h.dat"))

    def test_taboo_l_exists(self):
        assert os.path.exists(os.path.join(REF_DIR, "l.dat"))

    def test_taboo_k_exists(self):
        assert os.path.exists(os.path.join(REF_DIR, "k.dat"))


# ============================================================
# Test: Solver output files exist
# ============================================================

class TestSolverOutputExists:
    def test_modes_csv(self):
        assert os.path.exists(os.path.join(OUT_DIR, "modes.csv")), \
            "modes.csv not found in /app/output/"

    def test_love_numbers_csv(self):
        assert os.path.exists(os.path.join(OUT_DIR, "love_numbers.csv")), \
            "love_numbers.csv not found in /app/output/"

    def test_heaviside_h_csv(self):
        assert os.path.exists(os.path.join(OUT_DIR, "heaviside_h.csv")), \
            "heaviside_h.csv not found in /app/output/"

    def test_heaviside_l_csv(self):
        assert os.path.exists(os.path.join(OUT_DIR, "heaviside_l.csv")), \
            "heaviside_l.csv not found in /app/output/"

    def test_heaviside_k_csv(self):
        assert os.path.exists(os.path.join(OUT_DIR, "heaviside_k.csv")), \
            "heaviside_k.csv not found in /app/output/"


# ============================================================
# Test: Relaxation spectrum accuracy
# ============================================================

class TestSpectrumAccuracy:
    @pytest.fixture(autouse=True)
    def setup(self):
        ref_path = os.path.join(REF_DIR, "spectrum.dat")
        sol_path = os.path.join(OUT_DIR, "modes.csv")
        if not os.path.exists(ref_path) or not os.path.exists(sol_path):
            pytest.skip("Reference or solver spectrum not available")
        raw = parse_taboo_spectrum(ref_path)
        self.ref = {}
        for deg, all_s in raw.items():
            phys = [s for s in all_s if s < 0]
            if phys:
                self.ref[deg] = sorted(phys)
        self.sol = parse_solver_modes(sol_path)

    def test_all_physical_modes_present(self):
        """Every physical mode from TABOO must be matched by the solver."""
        failures = []
        for deg in range(LMIN, LMAX + 1):
            ref_modes = self.ref.get(deg, [])
            sol_modes = self.sol.get(deg, [])
            if not ref_modes:
                continue
            n_matched = match_modes(sol_modes, ref_modes, SPECTRUM_RTOL)
            if n_matched < len(ref_modes):
                failures.append(
                    f"Degree {deg}: {n_matched}/{len(ref_modes)} modes matched "
                    f"(solver has {len(sol_modes)})"
                )
        assert not failures, "Mode matching failures:\n" + "\n".join(failures)

    def test_no_spurious_modes(self):
        """Solver should not report many modes that don't match reference."""
        bad = 0
        total = 0
        for deg in range(LMIN, LMAX + 1):
            ref_modes = self.ref.get(deg, [])
            sol_modes = self.sol.get(deg, [])
            for s_sol in sol_modes:
                total += 1
                best_err = min(
                    (relative_error(s_sol, s_ref) for s_ref in ref_modes),
                    default=float("inf")
                )
                if best_err >= SPECTRUM_RTOL:
                    bad += 1
        if total > 0:
            assert bad / total < 0.1, \
                f"{bad}/{total} solver modes unmatched"


# ============================================================
# Test: Elastic Love numbers
# ============================================================

class TestElasticLoveNumbers:
    @pytest.fixture(autouse=True)
    def setup(self):
        for name in ["h.dat", "l.dat", "k.dat"]:
            if not os.path.exists(os.path.join(REF_DIR, name)):
                pytest.skip(f"Reference {name} missing")
        if not os.path.exists(os.path.join(OUT_DIR, "love_numbers.csv")):
            pytest.skip("Solver love_numbers.csv missing")
        self.ref_h = parse_taboo_love(os.path.join(REF_DIR, "h.dat"))
        self.ref_l = parse_taboo_love(os.path.join(REF_DIR, "l.dat"))
        self.ref_k = parse_taboo_love(os.path.join(REF_DIR, "k.dat"))
        self.sol = parse_solver_love(os.path.join(OUT_DIR, "love_numbers.csv"))

    def test_h_elastic(self):
        for deg in range(LMIN, LMAX + 1):
            assert deg in self.sol, f"Degree {deg} missing from solver output"
            ref_val = self.ref_h[deg][0]
            sol_val = self.sol[deg]["h_elastic"]
            err = relative_error(sol_val, ref_val)
            assert err < ELASTIC_RTOL, \
                f"h_e deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"

    def test_l_elastic(self):
        for deg in range(LMIN, LMAX + 1):
            ref_val = self.ref_l[deg][0]
            sol_val = self.sol[deg]["l_elastic"]
            err = relative_error(sol_val, ref_val)
            assert err < ELASTIC_RTOL, \
                f"l_e deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"

    def test_k_elastic(self):
        for deg in range(LMIN, LMAX + 1):
            ref_val = self.ref_k[deg][0]
            sol_val = self.sol[deg]["k_elastic"]
            err = relative_error(sol_val, ref_val)
            assert err < ELASTIC_RTOL, \
                f"k_e deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"


# ============================================================
# Test: Fluid Love numbers
# ============================================================

class TestFluidLoveNumbers:
    @pytest.fixture(autouse=True)
    def setup(self):
        for name in ["h.dat", "l.dat", "k.dat"]:
            if not os.path.exists(os.path.join(REF_DIR, name)):
                pytest.skip(f"Reference {name} missing")
        if not os.path.exists(os.path.join(OUT_DIR, "love_numbers.csv")):
            pytest.skip("Solver love_numbers.csv missing")
        self.ref_h = parse_taboo_love(os.path.join(REF_DIR, "h.dat"))
        self.ref_l = parse_taboo_love(os.path.join(REF_DIR, "l.dat"))
        self.ref_k = parse_taboo_love(os.path.join(REF_DIR, "k.dat"))
        self.sol = parse_solver_love(os.path.join(OUT_DIR, "love_numbers.csv"))

    def test_h_fluid(self):
        for deg in range(LMIN, LMAX + 1):
            ref_val = self.ref_h[deg][1]
            sol_val = self.sol[deg]["h_fluid"]
            err = relative_error(sol_val, ref_val)
            assert err < FLUID_RTOL, \
                f"h_f deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"

    def test_l_fluid(self):
        for deg in range(LMIN, LMAX + 1):
            ref_val = self.ref_l[deg][1]
            sol_val = self.sol[deg]["l_fluid"]
            err = relative_error(sol_val, ref_val)
            assert err < FLUID_RTOL, \
                f"l_f deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"

    def test_k_fluid(self):
        for deg in range(LMIN, LMAX + 1):
            ref_val = self.ref_k[deg][1]
            sol_val = self.sol[deg]["k_fluid"]
            err = relative_error(sol_val, ref_val)
            assert err < FLUID_RTOL, \
                f"k_f deg {deg}: ref={ref_val:.10e}, sol={sol_val:.10e}, err={err:.2e}"


# ============================================================
# Test: Heaviside response accuracy
# ============================================================

class TestHeavisideResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        for name in ["spectrum.dat", "h.dat", "l.dat", "k.dat"]:
            if not os.path.exists(os.path.join(REF_DIR, name)):
                pytest.skip(f"Reference {name} missing")
        for name in ["heaviside_h.csv", "heaviside_l.csv", "heaviside_k.csv"]:
            if not os.path.exists(os.path.join(OUT_DIR, name)):
                pytest.skip(f"Solver {name} missing")

        self.spectrum = parse_taboo_spectrum(os.path.join(REF_DIR, "spectrum.dat"))
        self.ref_h = parse_taboo_love(os.path.join(REF_DIR, "h.dat"))
        self.ref_l = parse_taboo_love(os.path.join(REF_DIR, "l.dat"))
        self.ref_k = parse_taboo_love(os.path.join(REF_DIR, "k.dat"))

        self.sol_hh = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_h.csv"))
        self.sol_hl = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_l.csv"))
        self.sol_hk = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_k.csv"))

    def _check_heaviside(self, love_data, sol_data, label):
        failures = []
        for deg in range(LMIN, LMAX + 1):
            if deg not in love_data or deg not in self.spectrum:
                continue
            h_e, h_f, residues = love_data[deg]
            all_s = self.spectrum[deg]
            for t in TIME_POINTS:
                expected = compute_heaviside(h_e, all_s, residues, t)
                key = (deg, t)
                if key not in sol_data:
                    failures.append(f"Missing ({deg}, {t})")
                    continue
                actual = sol_data[key]
                if abs(expected) > 1e-8:
                    err = relative_error(actual, expected)
                    if err >= HEAVISIDE_RTOL:
                        failures.append(
                            f"{label} deg={deg} t={t}: exp={expected:.8e} "
                            f"got={actual:.8e} err={err:.2e}"
                        )
                else:
                    abserr = abs(actual - expected)
                    if abserr >= HEAVISIDE_ATOL:
                        failures.append(
                            f"{label} deg={deg} t={t}: exp={expected:.8e} "
                            f"got={actual:.8e} abserr={abserr:.2e}"
                        )
        return failures

    def test_heaviside_h(self):
        failures = self._check_heaviside(self.ref_h, self.sol_hh, "h")
        assert not failures, \
            f"Heaviside h failures ({len(failures)}):\n" + "\n".join(failures[:15])

    def test_heaviside_l(self):
        failures = self._check_heaviside(self.ref_l, self.sol_hl, "l")
        assert not failures, \
            f"Heaviside l failures ({len(failures)}):\n" + "\n".join(failures[:15])

    def test_heaviside_k(self):
        failures = self._check_heaviside(self.ref_k, self.sol_hk, "k")
        assert not failures, \
            f"Heaviside k failures ({len(failures)}):\n" + "\n".join(failures[:15])


# ============================================================
# Test: Degree coverage
# ============================================================

class TestDegreeCoverage:
    def test_love_numbers_coverage(self):
        sol = parse_solver_love(os.path.join(OUT_DIR, "love_numbers.csv"))
        for deg in range(LMIN, LMAX + 1):
            assert deg in sol, f"Degree {deg} missing from love_numbers.csv"

    def test_modes_coverage(self):
        sol = parse_solver_modes(os.path.join(OUT_DIR, "modes.csv"))
        missing = [d for d in range(LMIN, LMAX + 1) if d not in sol]
        assert len(missing) == 0, f"Degrees missing from modes.csv: {missing}"

    def test_heaviside_h_coverage(self):
        sol = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_h.csv"))
        for deg in range(LMIN, LMAX + 1):
            for t in TIME_POINTS:
                assert (deg, t) in sol, \
                    f"Missing (degree={deg}, t={t}) in heaviside_h.csv"

    def test_heaviside_l_coverage(self):
        sol = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_l.csv"))
        for deg in range(LMIN, LMAX + 1):
            for t in TIME_POINTS:
                assert (deg, t) in sol, \
                    f"Missing (degree={deg}, t={t}) in heaviside_l.csv"

    def test_heaviside_k_coverage(self):
        sol = parse_solver_heaviside(os.path.join(OUT_DIR, "heaviside_k.csv"))
        for deg in range(LMIN, LMAX + 1):
            for t in TIME_POINTS:
                assert (deg, t) in sol, \
                    f"Missing (degree={deg}, t={t}) in heaviside_k.csv"
