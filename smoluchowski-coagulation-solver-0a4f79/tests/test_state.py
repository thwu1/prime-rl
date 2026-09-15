"""Tests for Fortran-Python hybrid coagulation solver."""
import ctypes
import json
import math
import os
import subprocess

import numpy as np
import netCDF4
import pytest


PI = math.pi
KB = 1.38065e-23
NA = 6.02214076e23
M_AIR = 0.02897
R_GAS = 8.31446


def load_results():
    """Load results from NetCDF4 as a dict of dicts."""
    data = {}
    with netCDF4.Dataset("/app/results.nc", "r") as ds:
        for gname in ds.groups:
            grp = ds.groups[gname]
            d = {}
            for vname in grp.variables:
                d[vname] = grp.variables[vname][:].tolist()
            data[gname] = d
    return data


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


def get_scenario(config, name):
    for s in config["scenarios"]:
        if s["name"] == name:
            return s
    raise ValueError(f"Scenario {name} not found")


def ref_brownian_kernel(r1, r2, rho_p, T, P):
    """Independent reference implementation of the transition-regime
    Brownian coagulation kernel (Jacobson 2005 Eq 15.33)."""
    v1 = (4.0 / 3.0) * PI * r1 ** 3
    v2 = (4.0 / 3.0) * PI * r2 ** 3

    rhoair = P * M_AIR / (R_GAS * T)
    mu = 1.8325e-5 * (416.16 / (T + 120.0)) * (T / 296.16) ** 1.5
    nu = mu / rhoair
    cbar = math.sqrt(8.0 * KB * T * NA / (PI * M_AIR))
    lam = 2.0 * nu / cbar

    def particle(v, r, rho):
        Rm = r
        Kn = lam / Rm
        Cc = 1.0 + Kn * (1.249 + 0.42 * math.exp(-0.87 / Kn))
        D = KB * T * Cc / (6.0 * PI * Rm * mu)
        csq = 8.0 * KB * T / (PI * rho * v)
        ell = 8.0 * D / (PI * math.sqrt(csq))
        t1 = (2.0 * Rm + ell) ** 3
        t2 = (4.0 * Rm ** 2 + ell ** 2) ** 1.5
        dsq = ((t1 - t2) / (6.0 * Rm * ell) - 2.0 * Rm) ** 2
        return D, csq, dsq

    D1, csq1, dsq1 = particle(v1, r1, rho_p)
    D2, csq2, dsq2 = particle(v2, r2, rho_p)

    rs = r1 + r2
    Ds = D1 + D2
    f1 = rs / (rs + math.sqrt(dsq1 + dsq2))
    f2 = 4.0 * Ds / (rs * math.sqrt(csq1 + csq2))
    return 4.0 * PI * rs * Ds / (f1 + f2)


# ---------------------------------------------------------------------------
# Library build verification
# ---------------------------------------------------------------------------

class TestLibraryBuild:
    """Verify the compiled Fortran shared library exists and is functional."""

    def test_library_exists(self):
        assert os.path.exists("/app/libcoag.so"), "libcoag.so not found"

    def test_library_is_elf(self):
        with open("/app/libcoag.so", "rb") as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', "libcoag.so is not a valid ELF shared object"

    def test_exports_kernel_constant(self):
        result = subprocess.run(
            ["nm", "-D", "/app/libcoag.so"],
            capture_output=True, text=True
        )
        assert "kernel_constant" in result.stdout, (
            "kernel_constant not found in dynamic symbol table"
        )

    def test_exports_kernel_additive(self):
        result = subprocess.run(
            ["nm", "-D", "/app/libcoag.so"],
            capture_output=True, text=True
        )
        assert "kernel_additive" in result.stdout, (
            "kernel_additive not found in dynamic symbol table"
        )

    def test_exports_kernel_brownian(self):
        result = subprocess.run(
            ["nm", "-D", "/app/libcoag.so"],
            capture_output=True, text=True
        )
        assert "kernel_brownian" in result.stdout, (
            "kernel_brownian not found in dynamic symbol table"
        )

    def test_kernel_constant_callable(self):
        lib = ctypes.CDLL("/app/libcoag.so")
        lib.kernel_constant.argtypes = [ctypes.c_double] * 3
        lib.kernel_constant.restype = ctypes.c_double
        beta0 = 5.0e-12
        result = lib.kernel_constant(1e-18, 2e-18, beta0)
        assert abs(result - beta0) / beta0 < 1e-10, (
            f"kernel_constant({1e-18}, {2e-18}, {beta0}) = {result}, "
            f"expected {beta0}"
        )

    def test_kernel_additive_callable(self):
        lib = ctypes.CDLL("/app/libcoag.so")
        lib.kernel_additive.argtypes = [ctypes.c_double] * 3
        lib.kernel_additive.restype = ctypes.c_double
        v1, v2, beta1 = 1e-18, 2e-18, 1500.0
        result = lib.kernel_additive(v1, v2, beta1)
        expected = beta1 * (v1 + v2)
        assert abs(result - expected) / expected < 1e-10, (
            f"kernel_additive({v1}, {v2}, {beta1}) = {result}, "
            f"expected {expected}"
        )

    def test_kernel_brownian_callable(self):
        lib = ctypes.CDLL("/app/libcoag.so")
        lib.kernel_brownian.argtypes = [ctypes.c_double] * 6
        lib.kernel_brownian.restype = ctypes.c_double
        r1, r2 = 1e-7, 1e-7
        v1 = (4.0 / 3.0) * PI * r1 ** 3
        v2 = (4.0 / 3.0) * PI * r2 ** 3
        rho, T, P = 1800.0, 300.0, 101325.0
        result = lib.kernel_brownian(v1, rho, v2, rho, T, P)
        ref = ref_brownian_kernel(r1, r2, rho, T, P)
        rel_err = abs(result - ref) / ref
        assert rel_err < 0.001, (
            f"kernel_brownian: result={result:.6e}, ref={ref:.6e}, "
            f"rel_err={rel_err:.6f}"
        )

    def test_kernel_brownian_different_sizes(self):
        """Test Brownian kernel for particles of very different sizes."""
        lib = ctypes.CDLL("/app/libcoag.so")
        lib.kernel_brownian.argtypes = [ctypes.c_double] * 6
        lib.kernel_brownian.restype = ctypes.c_double
        r1, r2 = 1e-8, 1e-6
        v1 = (4.0 / 3.0) * PI * r1 ** 3
        v2 = (4.0 / 3.0) * PI * r2 ** 3
        rho, T, P = 1800.0, 300.0, 101325.0
        result = lib.kernel_brownian(v1, rho, v2, rho, T, P)
        ref = ref_brownian_kernel(r1, r2, rho, T, P)
        rel_err = abs(result - ref) / ref
        assert rel_err < 0.001, (
            f"kernel_brownian (10nm,1um): result={result:.6e}, ref={ref:.6e}, "
            f"rel_err={rel_err:.6f}"
        )


# ---------------------------------------------------------------------------
# NetCDF4 output structure verification
# ---------------------------------------------------------------------------

class TestNetCDFStructure:
    """Verify the NetCDF4 output file structure."""

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.nc"), "results.nc not found"

    def test_valid_netcdf4(self):
        ds = netCDF4.Dataset("/app/results.nc", "r")
        assert ds.data_model in ("NETCDF4", "NETCDF4_CLASSIC"), (
            f"Expected NetCDF4 format, got {ds.data_model}"
        )
        ds.close()

    def test_all_groups_present(self):
        with netCDF4.Dataset("/app/results.nc", "r") as ds:
            for name in ("constant", "additive", "brownian_pairs", "brownian_evolve"):
                assert name in ds.groups, f"Missing group: {name}"

    def test_evolution_variables(self):
        with netCDF4.Dataset("/app/results.nc", "r") as ds:
            for name in ("constant", "additive", "brownian_evolve"):
                grp = ds.groups[name]
                for field in ("total_number", "total_volume", "mean_volume"):
                    assert field in grp.variables, (
                        f"Missing variable {field} in group {name}"
                    )

    def test_brownian_pairs_variable(self):
        with netCDF4.Dataset("/app/results.nc", "r") as ds:
            grp = ds.groups["brownian_pairs"]
            assert "kernel_values" in grp.variables, (
                "Missing kernel_values in brownian_pairs group"
            )

    def test_evolution_array_lengths(self):
        data = load_results()
        config = load_config()
        for name in ("constant", "additive", "brownian_evolve"):
            sc = get_scenario(config, name)
            expected_len = len(sc["times"])
            for field in ("total_number", "total_volume", "mean_volume"):
                actual_len = len(data[name][field])
                assert actual_len == expected_len, (
                    f"{name}/{field}: expected {expected_len} values, "
                    f"got {actual_len}"
                )

    def test_brownian_pairs_count(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_pairs")
        expected = len(sc["pairs_radii_m"])
        actual = len(data["brownian_pairs"]["kernel_values"])
        assert actual == expected, (
            f"brownian_pairs/kernel_values: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Constant kernel physics
# ---------------------------------------------------------------------------

class TestConstantKernel:
    def test_total_number_at_each_time(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "constant")

        N0 = sc["N0"]
        beta0 = sc["beta0"]
        times = sc["times"]
        computed = data["constant"]["total_number"]

        assert len(computed) == len(times), (
            f"Expected {len(times)} values, got {len(computed)}"
        )

        for i, t in enumerate(times):
            if t == 0:
                expected = N0
                tol = 0.02
            else:
                tau = N0 * beta0 * t
                expected = 2.0 * N0 / (tau + 2.0)
                tol = 0.05

            rel_err = abs(computed[i] - expected) / expected
            assert rel_err < tol, (
                f"t={t}: computed={computed[i]:.4e}, expected={expected:.4e}, "
                f"rel_err={rel_err:.4f}"
            )

    def test_volume_conservation(self):
        data = load_results()
        vols = data["constant"]["total_volume"]
        V0 = vols[0]
        assert V0 > 0, "Initial volume must be positive"
        for i, V in enumerate(vols):
            rel_err = abs(V - V0) / V0
            assert rel_err < 0.005, (
                f"Volume not conserved at step {i}: V={V:.6e}, V0={V0:.6e}, "
                f"err={rel_err:.6f}"
            )

    def test_number_decreases(self):
        data = load_results()
        nums = data["constant"]["total_number"]
        for i in range(1, len(nums)):
            assert nums[i] < nums[i - 1], (
                f"N[{i}]={nums[i]:.4e} should be < N[{i-1}]={nums[i-1]:.4e}"
            )

    def test_mean_volume_increases(self):
        data = load_results()
        mvs = data["constant"]["mean_volume"]
        for i in range(1, len(mvs)):
            assert mvs[i] > mvs[i - 1], (
                f"v_mean[{i}]={mvs[i]:.4e} should be > "
                f"v_mean[{i-1}]={mvs[i-1]:.4e}"
            )


# ---------------------------------------------------------------------------
# Additive kernel physics
# ---------------------------------------------------------------------------

class TestAdditiveKernel:
    def test_total_number_at_each_time(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "additive")

        N0 = sc["N0"]
        beta1 = sc["beta1"]
        R0 = sc["mean_radius"]
        v_mu = (4.0 / 3.0) * PI * R0 ** 3
        times = sc["times"]
        computed = data["additive"]["total_number"]

        assert len(computed) == len(times)

        for i, t in enumerate(times):
            if t == 0:
                expected = N0
                tol = 0.02
            else:
                rate = beta1 * N0 * v_mu
                expected = N0 * math.exp(-rate * t)
                tol = 0.05

            if expected > 1000:
                rel_err = abs(computed[i] - expected) / expected
                assert rel_err < tol, (
                    f"t={t}: computed={computed[i]:.4e}, "
                    f"expected={expected:.4e}, rel_err={rel_err:.4f}"
                )

    def test_volume_conservation(self):
        data = load_results()
        vols = data["additive"]["total_volume"]
        V0 = vols[0]
        assert V0 > 0
        for i, V in enumerate(vols):
            rel_err = abs(V - V0) / V0
            assert rel_err < 0.005, (
                f"Volume not conserved at step {i}: V={V:.6e}, V0={V0:.6e}, "
                f"err={rel_err:.6f}"
            )

    def test_number_decreases(self):
        data = load_results()
        nums = data["additive"]["total_number"]
        for i in range(1, len(nums)):
            assert nums[i] < nums[i - 1]

    def test_significant_change(self):
        """The additive kernel should produce a large reduction in number."""
        data = load_results()
        nums = data["additive"]["total_number"]
        ratio = nums[-1] / nums[0]
        assert ratio < 0.1, (
            f"Expected >10x decrease, got ratio={ratio:.4f}"
        )


# ---------------------------------------------------------------------------
# Brownian kernel pair values
# ---------------------------------------------------------------------------

class TestBrownianKernelValues:
    def test_kernel_count(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_pairs")
        pairs = sc["pairs_radii_m"]
        computed = data["brownian_pairs"]["kernel_values"]
        assert len(computed) == len(pairs)

    def test_kernel_values_match_reference(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_pairs")

        pairs = sc["pairs_radii_m"]
        T = sc["temp"]
        P = sc["pressure"]
        rho = sc["rho_p"]
        computed = data["brownian_pairs"]["kernel_values"]

        for i, (r1, r2) in enumerate(pairs):
            ref = ref_brownian_kernel(r1, r2, rho, T, P)
            rel_err = abs(computed[i] - ref) / ref
            assert rel_err < 0.02, (
                f"Pair ({r1:.0e}, {r2:.0e}): computed={computed[i]:.4e}, "
                f"ref={ref:.4e}, rel_err={rel_err:.4f}"
            )

    def test_kernel_values_positive(self):
        data = load_results()
        for v in data["brownian_pairs"]["kernel_values"]:
            assert v > 0, f"Kernel value must be positive, got {v}"

    def test_kernel_symmetry(self):
        """K(r1,r2) should equal K(r2,r1); check via self-consistency."""
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_pairs")
        pairs = sc["pairs_radii_m"]
        computed = data["brownian_pairs"]["kernel_values"]

        for i, (r1, r2) in enumerate(pairs):
            if r1 == r2:
                continue
            ref_forward = ref_brownian_kernel(
                r1, r2, sc["rho_p"], sc["temp"], sc["pressure"]
            )
            ref_reverse = ref_brownian_kernel(
                r2, r1, sc["rho_p"], sc["temp"], sc["pressure"]
            )
            assert abs(ref_forward - ref_reverse) / ref_forward < 1e-10


# ---------------------------------------------------------------------------
# Brownian evolution
# ---------------------------------------------------------------------------

class TestBrownianEvolution:
    def test_volume_conservation(self):
        data = load_results()
        vols = data["brownian_evolve"]["total_volume"]
        V0 = vols[0]
        assert V0 > 0
        for i, V in enumerate(vols):
            rel_err = abs(V - V0) / V0
            assert rel_err < 0.01, (
                f"Volume not conserved at step {i}: V={V:.6e}, V0={V0:.6e}, "
                f"err={rel_err:.6f}"
            )

    def test_number_monotonically_decreases(self):
        data = load_results()
        nums = data["brownian_evolve"]["total_number"]
        for i in range(1, len(nums)):
            assert nums[i] < nums[i - 1], (
                f"N[{i}]={nums[i]:.4e} should be < N[{i-1}]={nums[i-1]:.4e}"
            )

    def test_number_decreases_significantly(self):
        """Total number must decrease by at least 0.1% over the simulation."""
        data = load_results()
        nums = data["brownian_evolve"]["total_number"]
        rel_change = (nums[0] - nums[-1]) / nums[0]
        assert rel_change > 0.001, (
            f"Too little change: N0={nums[0]:.4e}, N_final={nums[-1]:.4e}, "
            f"rel_change={rel_change:.6f}"
        )

    def test_initial_number_reasonable(self):
        """At t=0, total number should be close to N0."""
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_evolve")
        N0 = sc["N0"]
        computed_N0 = data["brownian_evolve"]["total_number"][0]
        rel_err = abs(computed_N0 - N0) / N0
        assert rel_err < 0.02, (
            f"Initial N={computed_N0:.4e} too far from N0={N0:.4e}, "
            f"err={rel_err:.4f}"
        )

    def test_mean_volume_increases(self):
        data = load_results()
        mvs = data["brownian_evolve"]["mean_volume"]
        for i in range(1, len(mvs)):
            assert mvs[i] > mvs[i - 1]

    def test_correct_number_of_time_points(self):
        data = load_results()
        config = load_config()
        sc = get_scenario(config, "brownian_evolve")
        expected = len(sc["times"])
        for field in ("total_number", "total_volume", "mean_volume"):
            assert len(data["brownian_evolve"][field]) == expected
