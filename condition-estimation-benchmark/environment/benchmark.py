#!/usr/bin/env python3
"""Benchmark driver: generates results.json from all estimators."""
import json
import ctypes
import os
import sys
import numpy as np
from matrices import moler, pascal_matrix, frank, cauchy_matrix, parter
from estimators import tricond_nopiv, tricond_piv, hager_cond1, exact_cond2

GENERATORS = {
    "moler": moler,
    "pascal": pascal_matrix,
    "frank": frank,
    "cauchy": cauchy_matrix,
    "parter": parter,
}


def load_c_estimator(lib_path):
    """Load C shared library for blocked condition estimator."""
    try:
        lib = ctypes.CDLL(lib_path)
        lib.blocked_cond1.restype = ctypes.c_double
        lib.blocked_cond1.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.c_int,
        ]
        return lib
    except OSError:
        return None


def c_blocked_cond1(lib, A, max_iter):
    """Call C blocked condition estimator."""
    n = A.shape[0]
    A_flat = A.flatten().astype(np.float64)
    A_ptr = A_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
    result = lib.blocked_cond1(A_ptr, n, max_iter)
    return float(result)


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    families = config["matrix_families"]
    sizes = config["sizes"]
    max_iter = config.get("hager_max_iter", 6)

    c_lib = load_c_estimator(config.get("c_library_path",
                                        "/app/c_src/libblocked_est.so"))
    if c_lib:
        print("C blocked estimator loaded successfully.")
    else:
        print("Warning: C blocked estimator not available, blocked_cond1 "
              "will be null.")

    all_results = {}
    crossover = {}

    for fam in families:
        gen = GENERATORS[fam]
        all_results[fam] = {}
        max_crossover = None

        for n in sizes:
            A = gen(n)
            ec2 = exact_cond2(A)
            tn = tricond_nopiv(A)
            tp = tricond_piv(A)
            hc = hager_cond1(A)

            if c_lib:
                bc = c_blocked_cond1(c_lib, A, max_iter)
            else:
                bc = None

            sn = tn / ec2
            sp = tp / ec2

            all_results[fam][str(n)] = {
                "exact_cond2": ec2,
                "tricond_nopiv": tn,
                "tricond_piv": tp,
                "hager_cond1": hc,
                "blocked_cond1": bc,
                "score_nopiv": sn,
                "score_piv": sp,
            }

            if np.isfinite(sn) and sn >= 0.5:
                max_crossover = n

        crossover[fam] = max_crossover

    output = {"results": all_results, "crossover_nopiv": crossover}
    with open(config["output_file"], "w") as f:
        json.dump(output, f, indent=2)
    print("Benchmark complete.")


if __name__ == "__main__":
    main()
