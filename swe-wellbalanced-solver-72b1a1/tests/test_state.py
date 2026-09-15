"""
Tests for the multi-layer 1D Saint-Venant shallow water equation solver.
Verifies: C library build, ctypes FFI, HDF5 output, physics, parameter parsing, CLI.
"""

import sys
import os
import json
import subprocess
import ctypes
import numpy as np
import pytest

sys.path.insert(0, "/app")

G = 9.81


# ---------- Exact solution helpers ----------

def bump(x):
    """Bump topography used in lake-at-rest, subcritical, and transcritical cases."""
    return np.maximum(0.0, 0.2 - 0.05 * (x - 10.0) ** 2)


def ritter_exact(x, t, h_L, x_dam=25.0):
    """Ritter exact solution for dam break on dry bed."""
    g = G
    c0 = np.sqrt(g * h_L)
    h = np.zeros_like(x)
    u = np.zeros_like(x)
    for i in range(len(x)):
        xi = x[i] - x_dam
        if xi <= -c0 * t:
            h[i] = h_L
            u[i] = 0.0
        elif xi >= 2.0 * c0 * t:
            h[i] = 0.0
            u[i] = 0.0
        else:
            h[i] = (1.0 / (9.0 * g)) * (2.0 * c0 - xi / t) ** 2
            u[i] = (2.0 / 3.0) * (xi / t + c0)
    return h, u


def stoker_exact(x, t, h_L, h_R, x_dam=25.0):
    """Stoker exact solution for dam break on wet bed."""
    g = G
    c_L = np.sqrt(g * h_L)
    h_s = 0.5 * (h_L + h_R)
    for _ in range(200):
        c_s = np.sqrt(g * h_s)
        shock_rhs = np.sqrt(0.5 * g * (h_s + h_R) / (h_s * h_R))
        f_val = 2.0 * c_L * (1.0 - c_s / c_L) - (h_s - h_R) * shock_rhs
        eps = h_s * 1e-8
        h_sp = h_s + eps
        c_sp = np.sqrt(g * h_sp)
        shock_rhs_p = np.sqrt(0.5 * g * (h_sp + h_R) / (h_sp * h_R))
        f_val_p = 2.0 * c_L * (1.0 - c_sp / c_L) - (h_sp - h_R) * shock_rhs_p
        df = (f_val_p - f_val) / eps
        if abs(df) < 1e-30:
            break
        h_s_new = h_s - f_val / df
        if abs(h_s_new - h_s) < 1e-14:
            break
        h_s = h_s_new
    u_s = 2.0 * c_L * (1.0 - np.sqrt(g * h_s) / c_L)
    S_shock = u_s * h_s / (h_s - h_R)
    c_s = np.sqrt(g * h_s)
    h = np.zeros_like(x)
    u = np.zeros_like(x)
    for i in range(len(x)):
        xi = x[i] - x_dam
        if xi <= -c_L * t:
            h[i] = h_L
            u[i] = 0.0
        elif xi <= (u_s - c_s) * t:
            h[i] = (1.0 / (9.0 * g)) * (2.0 * c_L - xi / t) ** 2
            u[i] = (2.0 / 3.0) * (xi / t + c_L)
        elif xi <= S_shock * t:
            h[i] = h_s
            u[i] = u_s
        else:
            h[i] = h_R
            u[i] = 0.0
    return h, u


def subcritical_bump_exact(x, q, h_downstream, zb):
    """Exact steady-state subcritical flow over bump via energy conservation."""
    g = G
    E_downstream = h_downstream + q ** 2 / (2.0 * g * h_downstream ** 2) + zb[-1]
    h_exact = np.zeros_like(x)
    for i in range(len(x)):
        E_local = E_downstream - zb[i]
        h_val = h_downstream
        for _ in range(200):
            f = h_val + q ** 2 / (2.0 * g * h_val ** 2) - E_local
            df = 1.0 - q ** 2 / (g * h_val ** 3)
            if abs(df) < 1e-30:
                break
            h_new = h_val - f / df
            if h_new < 0:
                h_new = 0.01
            if abs(h_new - h_val) < 1e-14:
                break
            h_val = h_new
        h_exact[i] = h_val
    return h_exact


def transcritical_shock_exact(x, q, h_downstream, zb):
    """Exact transcritical flow with shock over bump."""
    g = G
    h_c = (q ** 2 / g) ** (1.0 / 3.0)
    i_crest = np.argmax(zb)
    zb_crest = zb[i_crest]
    E_total = h_c + q ** 2 / (2.0 * g * h_c ** 2) + zb_crest
    E_downstream = h_downstream + q ** 2 / (2.0 * g * h_downstream ** 2) + zb[-1]

    h_super = np.zeros_like(x)
    for i in range(len(x)):
        E_local = E_total - zb[i]
        h_val = 0.1 * h_c
        for _ in range(200):
            f = h_val + q ** 2 / (2.0 * g * h_val ** 2) - E_local
            df = 1.0 - q ** 2 / (g * h_val ** 3)
            if abs(df) < 1e-30:
                break
            h_new = h_val - f / df
            if h_new < 1e-10:
                h_new = 1e-10
            if abs(h_new - h_val) < 1e-14:
                break
            h_val = h_new
        h_super[i] = h_val

    h_sub = np.zeros_like(x)
    for i in range(len(x)):
        E_local = E_total - zb[i]
        h_val = 2.0 * h_c
        for _ in range(200):
            f = h_val + q ** 2 / (2.0 * g * h_val ** 2) - E_local
            df = 1.0 - q ** 2 / (g * h_val ** 3)
            if abs(df) < 1e-30:
                break
            h_new = h_val - f / df
            if h_new < h_c:
                h_new = h_c * 1.01
            if abs(h_new - h_val) < 1e-14:
                break
            h_val = h_new
        h_sub[i] = h_val

    h_sub_ds = np.zeros_like(x)
    for i in range(len(x)):
        E_local = E_downstream - zb[i]
        h_val = h_downstream
        for _ in range(200):
            f = h_val + q ** 2 / (2.0 * g * h_val ** 2) - E_local
            df = 1.0 - q ** 2 / (g * h_val ** 3)
            if abs(df) < 1e-30:
                break
            h_new = h_val - f / df
            if h_new < 0.01:
                h_new = 0.01
            if abs(h_new - h_val) < 1e-14:
                break
            h_val = h_new
        h_sub_ds[i] = h_val

    shock_idx = len(x) - 1
    for i in range(i_crest + 1, len(x)):
        h1 = h_super[i]
        Fr1_sq = q ** 2 / (g * h1 ** 3)
        h2_conjugate = h1 / 2.0 * (-1.0 + np.sqrt(1.0 + 8.0 * Fr1_sq))
        if abs(h2_conjugate - h_sub_ds[i]) / h_sub_ds[i] < 0.05:
            shock_idx = i
            break

    h_exact = np.zeros_like(x)
    for i in range(len(x)):
        if i <= i_crest:
            h_exact[i] = h_sub[i]
        elif i < shock_idx:
            h_exact[i] = h_super[i]
        else:
            h_exact[i] = h_sub_ds[i]
    return h_exact


# ---------- Build & Library Tests ----------

class TestBuild:
    """Verify the C shared library builds and loads correctly."""

    def test_library_file_exists(self):
        assert os.path.isfile("/app/lib/libflux.so"), \
            "Compiled library /app/lib/libflux.so not found — run 'make -C /app'"

    def test_library_loads_and_exports(self):
        lib = ctypes.CDLL("/app/lib/libflux.so")
        assert hasattr(lib, "hll_flux"), \
            "Symbol 'hll_flux' not found in libflux.so"

    def test_hll_flux_dam_break(self):
        """HLL flux for h_L=5, h_R=0 must yield positive mass flux."""
        lib = ctypes.CDLL("/app/lib/libflux.so")
        lib.hll_flux.argtypes = [
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.hll_flux.restype = None
        F_h = ctypes.c_double(0.0)
        F_hu = ctypes.c_double(0.0)
        lib.hll_flux(5.0, 0.0, 0.0, 0.0, 9.81,
                     ctypes.byref(F_h), ctypes.byref(F_hu))
        assert F_h.value > 0.0, \
            f"Mass flux should be positive for dry-bed dam break, got {F_h.value}"

    def test_hll_flux_symmetric(self):
        """HLL flux for equal left/right states must return exact physical flux."""
        lib = ctypes.CDLL("/app/lib/libflux.so")
        lib.hll_flux.argtypes = [
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.hll_flux.restype = None
        F_h = ctypes.c_double(0.0)
        F_hu = ctypes.c_double(0.0)
        h_val, hu_val = 2.0, 4.0
        lib.hll_flux(h_val, h_val, hu_val, hu_val, 9.81,
                     ctypes.byref(F_h), ctypes.byref(F_hu))
        assert abs(F_h.value - hu_val) < 1e-10, \
            f"Symmetric mass flux should be {hu_val}, got {F_h.value}"


# ---------- HDF5 Output Tests ----------

class TestHDF5Output:
    """Verify HDF5 output format, datasets, and consistency."""

    def test_hdf5_file_created(self):
        from swe1d import solve
        solve("lake_at_rest")
        assert os.path.isfile("/app/output/lake_at_rest.h5"), \
            "HDF5 output /app/output/lake_at_rest.h5 not created"

    def test_hdf5_required_datasets(self):
        import h5py
        from swe1d import solve
        solve("dam_break_dry")
        with h5py.File("/app/output/dam_break_dry.h5", "r") as f:
            for ds in ["x", "h", "u", "eta"]:
                assert ds in f, f"Missing dataset '{ds}' in HDF5 file"
                assert f[ds].dtype == np.float64, \
                    f"Dataset '{ds}' should be float64, got {f[ds].dtype}"
                assert len(f[ds].shape) == 1, \
                    f"Dataset '{ds}' should be 1D array"
            assert "t_final" in f, "Missing 't_final' dataset in HDF5 file"
            assert "gravity" in f.attrs, \
                "Missing 'gravity' attribute on HDF5 root group"

    def test_hdf5_array_lengths(self):
        import h5py
        from swe1d import solve
        solve("dam_break_wet")
        with h5py.File("/app/output/dam_break_wet.h5", "r") as f:
            assert f["x"].shape[0] == 500, \
                f"Expected 500 elements in x, got {f['x'].shape[0]}"
            assert f["h"].shape[0] == 500

    def test_hdf5_data_matches_return(self):
        import h5py
        from swe1d import solve
        result = solve("lake_at_rest")
        with h5py.File("/app/output/lake_at_rest.h5", "r") as f:
            np.testing.assert_allclose(f["h"][:], result["h"], atol=1e-12,
                                       err_msg="HDF5 h does not match returned h")
            np.testing.assert_allclose(f["u"][:], result["u"], atol=1e-12,
                                       err_msg="HDF5 u does not match returned u")
            np.testing.assert_allclose(f["eta"][:], result["eta"], atol=1e-12,
                                       err_msg="HDF5 eta does not match returned eta")


# ---------- Physics Tests ----------

class TestLakeAtRest:
    """Well-balancedness: lake at rest must be preserved to machine precision."""

    def test_eta_preserved(self):
        from swe1d import solve
        result = solve("lake_at_rest")
        x = result["x"]
        eta = result["eta"]
        assert len(x) == 200, "Expected 200 cells"
        err_eta = np.max(np.abs(eta - 0.5))
        assert err_eta < 1e-10, f"Lake-at-rest eta error {err_eta:.2e} exceeds 1e-10"

    def test_velocity_zero(self):
        from swe1d import solve
        result = solve("lake_at_rest")
        u = result["u"]
        err_u = np.max(np.abs(u))
        assert err_u < 1e-10, f"Lake-at-rest velocity error {err_u:.2e} exceeds 1e-10"

    def test_water_depth_consistent(self):
        from swe1d import solve
        result = solve("lake_at_rest")
        x = result["x"]
        h = result["h"]
        eta = result["eta"]
        zb = bump(x)
        np.testing.assert_allclose(eta, h + zb, atol=1e-12,
                                   err_msg="eta != h + z_b")


class TestDamBreakDry:
    """Dam break on dry bed verified against Ritter exact solution."""

    def test_water_depth_profile(self):
        from swe1d import solve
        result = solve("dam_break_dry")
        x = result["x"]
        h = result["h"]
        t = result["t_final"]
        assert abs(t - 2.0) < 1e-6, f"t_final should be ~2.0, got {t}"

        h_exact, _ = ritter_exact(x, t, h_L=5.0)
        wet = h_exact > 0.01
        l2_rel = np.sqrt(np.mean((h[wet] - h_exact[wet]) ** 2)) / \
                 np.sqrt(np.mean(h_exact[wet] ** 2))
        assert l2_rel < 0.05, \
            f"Dam-break-dry L2 relative error {l2_rel:.4f} > 0.05"

    def test_front_position(self):
        from swe1d import solve
        result = solve("dam_break_dry")
        x = result["x"]
        h = result["h"]
        t = result["t_final"]
        c0 = np.sqrt(G * 5.0)
        x_front_exact = 25.0 + 2.0 * c0 * t
        wet_idx = np.where(h > 1e-4)[0]
        assert len(wet_idx) > 0, "No wet cells found"
        x_front_num = x[wet_idx[-1]]
        x_max = x[-1]
        if x_front_exact > x_max:
            assert x_front_num > x_max - 2.0, \
                f"Front should reach near domain end, got {x_front_num:.2f}"
        else:
            assert abs(x_front_num - x_front_exact) < 2.0, \
                f"Front position error: numerical {x_front_num:.2f} " \
                f"vs exact {x_front_exact:.2f}"

    def test_mass_conservation(self):
        from swe1d import solve
        result = solve("dam_break_dry")
        h = result["h"]
        dx = 50.0 / 500
        mass = np.sum(h) * dx
        mass_initial = 5.0 * 25.0
        rel_err = abs(mass - mass_initial) / mass_initial
        assert rel_err < 0.01, \
            f"Mass conservation error {rel_err:.4f} > 0.01"


class TestDamBreakWet:
    """Dam break on wet bed verified against Stoker exact solution."""

    def test_water_depth_profile(self):
        from swe1d import solve
        result = solve("dam_break_wet")
        x = result["x"]
        h = result["h"]
        t = result["t_final"]
        assert abs(t - 2.0) < 1e-6

        h_exact, _ = stoker_exact(x, t, h_L=5.0, h_R=1.0)
        l2_rel = np.sqrt(np.mean((h - h_exact) ** 2)) / \
                 np.sqrt(np.mean(h_exact ** 2))
        assert l2_rel < 0.05, \
            f"Dam-break-wet L2 relative error {l2_rel:.4f} > 0.05"

    def test_shock_captured(self):
        from swe1d import solve
        result = solve("dam_break_wet")
        h = result["h"]
        dh = np.diff(h)
        min_jump = np.min(dh)
        assert min_jump < -0.1, \
            f"No shock detected: min dh = {min_jump:.4f}"

    def test_rarefaction_head(self):
        from swe1d import solve
        result = solve("dam_break_wet")
        x = result["x"]
        h = result["h"]
        t = result["t_final"]
        c_L = np.sqrt(G * 5.0)
        x_head_exact = 25.0 - c_L * t
        idx_head = np.argmin(np.abs(x - x_head_exact))
        if idx_head > 5:
            assert h[idx_head - 5] > 4.5, \
                "Undisturbed left state not preserved"


class TestSubcriticalBump:
    """Steady subcritical flow over bump."""

    def test_free_surface_profile(self):
        from swe1d import solve
        result = solve("subcritical_bump")
        x = result["x"]
        eta = result["eta"]

        zb = bump(x)
        q = 4.42
        h_downstream = 2.0
        h_exact = subcritical_bump_exact(x, q, h_downstream, zb)
        eta_exact = h_exact + zb

        l2_rel = np.sqrt(np.mean((eta - eta_exact) ** 2)) / \
                 np.sqrt(np.mean(eta_exact ** 2))
        assert l2_rel < 0.01, \
            f"Subcritical bump eta L2 relative error {l2_rel:.4f} > 0.01"

    def test_discharge_uniform(self):
        from swe1d import solve
        result = solve("subcritical_bump")
        h = result["h"]
        u = result["u"]
        q_computed = h * u
        q_std = np.std(q_computed)
        q_mean = np.mean(q_computed)
        assert abs(q_mean - 4.42) < 0.2, \
            f"Mean discharge {q_mean:.3f} != 4.42"
        assert q_std < 0.15, \
            f"Discharge std {q_std:.4f} too large (not steady)"

    def test_subcritical_everywhere(self):
        from swe1d import solve
        result = solve("subcritical_bump")
        h = result["h"]
        u = result["u"]
        Fr = np.abs(u) / np.sqrt(G * h)
        assert np.all(Fr < 1.0), \
            f"Flow not subcritical everywhere: max Fr = {np.max(Fr):.3f}"


class TestTranscriticalShock:
    """Transcritical flow with hydraulic jump over bump."""

    def test_free_surface_profile(self):
        from swe1d import solve
        result = solve("transcritical_shock")
        x = result["x"]
        eta = result["eta"]

        zb = bump(x)
        q = 0.18
        h_downstream = 0.33
        h_exact = transcritical_shock_exact(x, q, h_downstream, zb)
        eta_exact = h_exact + zb

        l2_rel = np.sqrt(np.mean((eta - eta_exact) ** 2)) / \
                 np.sqrt(np.mean(eta_exact ** 2))
        assert l2_rel < 0.05, \
            f"Transcritical shock eta L2 relative error {l2_rel:.4f} > 0.05"

    def test_has_supercritical_region(self):
        from swe1d import solve
        result = solve("transcritical_shock")
        x = result["x"]
        h = result["h"]
        u = result["u"]
        zb = bump(x)
        i_crest = np.argmax(zb)
        region = slice(max(0, i_crest - 2), min(len(x), i_crest + 15))
        Fr = np.abs(u[region]) / np.sqrt(G * np.maximum(h[region], 1e-10))
        assert np.any(Fr > 1.0), \
            "No supercritical region found near crest"

    def test_hydraulic_jump_present(self):
        from swe1d import solve
        result = solve("transcritical_shock")
        x = result["x"]
        h = result["h"]
        zb = bump(x)
        i_crest = np.argmax(zb)
        h_downstream = h[i_crest:]
        dh = np.diff(h_downstream)
        max_jump = np.max(dh)
        assert max_jump > 0.05, \
            f"No hydraulic jump detected downstream of crest: " \
            f"max dh = {max_jump:.4f}"

    def test_discharge_uniform(self):
        from swe1d import solve
        result = solve("transcritical_shock")
        h = result["h"]
        u = result["u"]
        q_computed = h * u
        wet = h > 0.01
        q_wet = q_computed[wet]
        q_std = np.std(q_wet)
        q_mean = np.mean(q_wet)
        assert abs(q_mean - 0.18) < 0.02, \
            f"Mean discharge {q_mean:.3f} != 0.18"
        assert q_std < 0.02, \
            f"Discharge std {q_std:.4f} too large"


# ---------- Interface Tests ----------

class TestSolverInterface:
    """Basic interface checks."""

    def test_returns_required_keys(self):
        from swe1d import solve
        for scenario in ["lake_at_rest", "dam_break_dry", "dam_break_wet",
                         "subcritical_bump", "transcritical_shock"]:
            result = solve(scenario)
            for key in ["x", "h", "u", "eta", "t_final"]:
                assert key in result, \
                    f"Missing key '{key}' in {scenario} result"

    def test_arrays_are_numpy(self):
        from swe1d import solve
        result = solve("lake_at_rest")
        for key in ["x", "h", "u", "eta"]:
            assert isinstance(result[key], np.ndarray), \
                f"{key} is not numpy array"

    def test_no_negative_depth(self):
        from swe1d import solve
        for scenario in ["lake_at_rest", "dam_break_dry", "dam_break_wet",
                         "subcritical_bump", "transcritical_shock"]:
            result = solve(scenario)
            assert np.all(result["h"] >= -1e-10), \
                f"Negative water depth in {scenario}: " \
                f"min h = {np.min(result['h'])}"


# ---------- Parameter Parsing Tests ----------

class TestParseParams:
    """Parameter file parsing."""

    def test_parse_lake_at_rest(self):
        from swe1d import parse_params
        params = parse_params("/app/params/lake_at_rest.dat")
        assert isinstance(params, dict)
        assert params["DomainMin"] == pytest.approx(0.0)
        assert params["DomainMax"] == pytest.approx(25.0)
        assert params["NumberOfCells"] == pytest.approx(200.0)
        assert params["TopographyType"] == "Bump"
        assert params["LeftBoundaryCondition"] == "Wall"

    def test_parse_dam_break_dry(self):
        from swe1d import parse_params
        params = parse_params("/app/params/dam_break_dry.dat")
        assert params["FinalTime"] == pytest.approx(2.0)
        assert params["LeftBoundaryCondition"] == "Transmissive"
        assert params["RightWaterHeight"] == pytest.approx(0.0)

    def test_parse_all_files(self):
        from swe1d import parse_params
        for name in ["lake_at_rest", "dam_break_dry", "dam_break_wet",
                     "subcritical_bump", "transcritical_shock"]:
            params = parse_params(f"/app/params/{name}.dat")
            assert "GravityAcceleration" in params, \
                f"Missing GravityAcceleration in {name}"
            assert params["GravityAcceleration"] == pytest.approx(9.81)


# ---------- CLI Tests ----------

class TestCLI:
    """CLI mode verification."""

    def test_cli_lake_at_rest(self):
        result = subprocess.run(
            ["python3", "/app/swe1d.py", "lake_at_rest"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        data = json.loads(result.stdout)
        for key in ["x", "h", "u", "eta", "t_final"]:
            assert key in data, f"Missing key '{key}' in CLI output"
        assert isinstance(data["x"], list)
        assert len(data["x"]) == 200
        assert os.path.isfile("/app/output/lake_at_rest.h5"), \
            "CLI mode should also write HDF5 output file"

    def test_cli_dam_break_wet(self):
        result = subprocess.run(
            ["python3", "/app/swe1d.py", "dam_break_wet"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data["x"]) == 500
        assert isinstance(data["t_final"], (int, float))
