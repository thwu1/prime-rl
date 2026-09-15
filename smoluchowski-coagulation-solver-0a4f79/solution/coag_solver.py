#!/usr/bin/env python3
"""
Smoluchowski coagulation equation solver.

Compiles PartMC Fortran kernel source into a shared library, calls via
ctypes for kernel evaluations, and writes results as NetCDF4.
"""

import ctypes
import json
import math
import os
import subprocess
import textwrap

import netCDF4
import numpy as np

PI = math.pi
KB = 1.38065e-23
NA = 6.02214076e23
M_AIR = 0.02897
R_GAS = 8.31446

# Fortran iso_c_binding wrapper module source
WRAPPER_F90 = textwrap.dedent("""\
    module coag_c_interface
      use iso_c_binding
      use pmc_coag_kernel_brown
      implicit none
    contains

      function kernel_constant(vi, vj, beta0) result(k) &
           bind(c, name="kernel_constant")
        real(c_double), intent(in), value :: vi, vj, beta0
        real(c_double) :: k
        k = beta0
      end function kernel_constant

      function kernel_additive(vi, vj, beta1) result(k) &
           bind(c, name="kernel_additive")
        real(c_double), intent(in), value :: vi, vj, beta1
        real(c_double) :: k
        k = beta1 * (vi + vj)
      end function kernel_additive

      function kernel_brownian(v1, rho1, v2, rho2, T, P) result(k) &
           bind(c, name="kernel_brownian")
        real(c_double), intent(in), value :: v1, rho1, v2, rho2, T, P
        real(c_double) :: k
        call kernel_brown_helper(v1, rho1, v2, rho2, T, P, k)
      end function kernel_brownian

    end module coag_c_interface
""")


# ---------- Fortran library compilation ----------------------------------------

def compile_library():
    """Write iso_c_binding wrapper and compile Fortran into shared library."""
    wrapper_path = "/app/coag_c_wrapper.F90"
    with open(wrapper_path, "w") as f:
        f.write(WRAPPER_F90)

    src_files = [
        "/app/reference/pmc_constants.F90",
        "/app/reference/aero_helpers.F90",
        "/app/reference/coag_kernel_brown.F90",
        "/app/reference/coag_kernel_constant.F90",
        "/app/reference/coag_kernel_additive.F90",
        wrapper_path,
    ]

    cmd = ["gfortran", "-shared", "-fPIC", "-O2",
           "-o", "/app/libcoag.so"] + src_files
    result = subprocess.run(cmd, capture_output=True, text=True, cwd="/app")
    if result.returncode != 0:
        raise RuntimeError(f"gfortran compilation failed:\n{result.stderr}")

    lib = ctypes.CDLL("/app/libcoag.so")

    lib.kernel_constant.argtypes = [ctypes.c_double] * 3
    lib.kernel_constant.restype = ctypes.c_double

    lib.kernel_additive.argtypes = [ctypes.c_double] * 3
    lib.kernel_additive.restype = ctypes.c_double

    lib.kernel_brownian.argtypes = [ctypes.c_double] * 6
    lib.kernel_brownian.restype = ctypes.c_double

    return lib


# ---------- helpers ------------------------------------------------------------

def rad2vol(r):
    r = np.asarray(r, dtype=np.float64)
    return (4.0 / 3.0) * PI * r ** 3


def vol2rad(v):
    v = np.asarray(v, dtype=np.float64)
    return ((3.0 / (4.0 * PI)) * v) ** (1.0 / 3.0)


# ---------- grid construction --------------------------------------------------

def log_grid(n_bins, r_min, r_max):
    """Return (v_centers, v_edges) on a log-spaced radius grid."""
    r_edges = np.logspace(np.log10(r_min), np.log10(r_max), n_bins + 1)
    r_centers = np.sqrt(r_edges[:-1] * r_edges[1:])
    return rad2vol(r_centers), rad2vol(r_edges)


# ---------- initial distributions -----------------------------------------------

def init_exponential(vc, ve, N0, r_mean):
    """n_k = integral of (N0/v_mu)*exp(-v/v_mu) over bin k."""
    vm = float(rad2vol(np.array([r_mean]))[0])
    return N0 * (np.exp(-ve[:-1] / vm) - np.exp(-ve[1:] / vm))


def init_lognormal(vc, ve, N0, r_med, sig_g):
    """n_k = integral of lognormal in radius over bin k."""
    re = vol2rad(ve)
    ls = math.log(sig_g)
    lr = math.log(r_med)
    s2 = math.sqrt(2.0) * ls
    n = np.empty(len(vc))
    for k in range(len(vc)):
        z_lo = (math.log(re[k]) - lr) / s2
        z_hi = (math.log(re[k + 1]) - lr) / s2
        n[k] = N0 / 2.0 * (math.erf(z_hi) - math.erf(z_lo))
    return n


# ---------- kernel matrix construction via Fortran library ----------------------

def kernel_matrix_constant(lib, vc, beta0):
    """Build kernel matrix using compiled Fortran constant kernel."""
    nb = len(vc)
    K = np.empty((nb, nb))
    for i in range(nb):
        for j in range(nb):
            K[i, j] = lib.kernel_constant(vc[i], vc[j], beta0)
    return K


def kernel_matrix_additive(lib, vc, beta1):
    """Build kernel matrix using compiled Fortran additive kernel."""
    nb = len(vc)
    K = np.empty((nb, nb))
    for i in range(nb):
        for j in range(nb):
            K[i, j] = lib.kernel_additive(vc[i], vc[j], beta1)
    return K


def kernel_matrix_brownian(lib, vc, rho_p, T, P):
    """Build kernel matrix using compiled Fortran Brownian kernel."""
    nb = len(vc)
    K = np.empty((nb, nb))
    for i in range(nb):
        for j in range(nb):
            K[i, j] = lib.kernel_brownian(vc[i], rho_p, vc[j], rho_p, T, P)
    return K


# ---------- coagulation mapping -------------------------------------------------

def coag_map(vc):
    """For every (i,j) find target bin and linear-interpolation fraction."""
    nb = len(vc)
    tb = np.zeros((nb, nb), dtype=np.int32)
    tf = np.zeros((nb, nb))
    v_last = vc[-1]

    for i in range(nb):
        for j in range(nb):
            vn = vc[i] + vc[j]
            if vn >= v_last:
                tb[i, j] = nb - 1
                tf[i, j] = 1.0
            else:
                k = int(np.searchsorted(vc, vn, side="right")) - 1
                k = max(0, min(k, nb - 2))
                f = (vc[k + 1] - vn) / (vc[k + 1] - vc[k])
                tb[i, j] = k
                tf[i, j] = max(0.0, min(1.0, f))
    return tb, tf


# ---------- time-stepping -------------------------------------------------------

def solve(n0, vc, K, times, dt_max):
    """Forward-Euler sectional solver with CFL-adaptive sub-stepping."""
    n = n0.copy()
    nb = len(vc)
    tb, tf = coag_map(vc)
    nb_next = np.minimum(tb + 1, nb - 1)

    tb_flat = tb.ravel()
    nb_flat = nb_next.ravel()
    tf_flat = tf.ravel()
    one_minus_tf = 1.0 - tf_flat

    out = {"total_number": [], "total_volume": [], "mean_volume": []}

    def record():
        N = float(np.sum(n))
        V = float(np.dot(n, vc))
        out["total_number"].append(N)
        out["total_volume"].append(V)
        out["mean_volume"].append(V / N if N > 1e-30 else 0.0)

    t = 0.0
    ti = 0

    if ti < len(times) and abs(t - times[ti]) < 1e-10:
        record()
        ti += 1

    while ti < len(times):
        target = times[ti]

        while t < target - 1e-10:
            lc = K @ n

            sig = n > 1e-30
            ml = float(np.max(lc[sig])) if np.any(sig) else 0.0
            dt = min(dt_max, 0.8 / ml) if ml > 0 else dt_max
            dt = min(dt, target - t)
            if dt < 1e-15:
                break

            rates = (K * np.outer(n, n)).ravel()
            gain = np.zeros(nb)
            gain += np.bincount(tb_flat, weights=rates * tf_flat,
                                minlength=nb)[:nb]
            gain += np.bincount(nb_flat, weights=rates * one_minus_tf,
                                minlength=nb)[:nb]
            gain *= 0.5

            n = n + dt * (gain - lc * n)
            n = np.maximum(n, 0.0)
            t += dt

        record()
        ti += 1

    return out


# ---------- NetCDF output -------------------------------------------------------

def write_netcdf(results, output_path):
    """Write results dict to NetCDF4 file with groups."""
    with netCDF4.Dataset(output_path, "w", format="NETCDF4") as ds:
        for name, data in results.items():
            grp = ds.createGroup(name)
            if "kernel_values" in data:
                n_pairs = len(data["kernel_values"])
                grp.createDimension("pair", n_pairs)
                var = grp.createVariable("kernel_values", "f8", ("pair",))
                var[:] = np.array(data["kernel_values"], dtype=np.float64)
            else:
                n_times = len(data["total_number"])
                grp.createDimension("time", n_times)
                for field in ("total_number", "total_volume", "mean_volume"):
                    var = grp.createVariable(field, "f8", ("time",))
                    var[:] = np.array(data[field], dtype=np.float64)


# ---------- main ----------------------------------------------------------------

def main():
    # Step 1: compile Fortran kernels into shared library
    print("Compiling Fortran kernel library...")
    lib = compile_library()
    print("Library compiled: /app/libcoag.so")

    # Step 2: read config
    with open("/app/config.json") as fh:
        config = json.load(fh)

    results = {}

    for sc in config["scenarios"]:
        name = sc["name"]
        ktype = sc["kernel_type"]
        print(f"Processing scenario: {name} ({ktype})")

        # brownian_pairs: evaluate kernel for each pair, no evolution
        if ktype == "brownian_pairs":
            T, P, rho = sc["temp"], sc["pressure"], sc["rho_p"]
            vals = []
            for r1, r2 in sc["pairs_radii_m"]:
                v1 = float(rad2vol(np.array([r1]))[0])
                v2 = float(rad2vol(np.array([r2]))[0])
                vals.append(lib.kernel_brownian(v1, rho, v2, rho, T, P))
            results[name] = {"kernel_values": vals}
            continue

        # evolution scenarios
        vc, ve = log_grid(sc["n_bins"], sc["r_min"], sc["r_max"])

        # initial distribution
        if "mean_radius" in sc:
            n0 = init_exponential(vc, ve, sc["N0"], sc["mean_radius"])
        else:
            n0 = init_lognormal(
                vc, ve, sc["N0"], sc["median_radius"], sc["sigma_g"]
            )

        # kernel matrix via Fortran library
        if ktype == "constant":
            K = kernel_matrix_constant(lib, vc, sc["beta0"])
        elif ktype == "additive":
            K = kernel_matrix_additive(lib, vc, sc["beta1"])
        elif ktype == "brownian":
            K = kernel_matrix_brownian(
                lib, vc, sc["rho_p"], sc["temp"], sc["pressure"]
            )
        else:
            raise ValueError(f"Unknown kernel type: {ktype}")

        results[name] = solve(n0, vc, K, sc["times"], sc["dt"])

    # Step 3: write NetCDF4 output
    write_netcdf(results, "/app/results.nc")
    print("Results written to /app/results.nc")
    print("All scenarios completed.")


if __name__ == "__main__":
    main()
