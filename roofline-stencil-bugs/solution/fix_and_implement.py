#!/usr/bin/env python3
"""Fix all bugs across the framework and implement missing components.

This script patches buggy Python modules, fixes the C kernel,
repairs the Makefile, and implements the two stub modules.
"""


import os


def patch_file(path, replacements):
    """Apply string replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


# ============================================================
# Fix 1: config_loader.py — bandwidth conversion 1e6 -> 1e9
# ============================================================
patch_file("/app/config_loader.py", [
    ("* 1e6", "* 1e9"),
])

# ============================================================
# Fix 2-4: stencil.py — interior points + write_allocate parameter
# ============================================================
patch_file("/app/stencil.py", [
    ("n_points = nx * ny * nz", "n_points = (nx - 2) * (ny - 2) * (nz - 2)"),
    ("    rfo = 1\n", "    rfo = 1 if write_allocate else 0\n"),
])

# ============================================================
# Fix 5-7: roofline.py — min() + 2 arrays + None L3 guard
# ============================================================
patch_file("/app/roofline.py", [
    ("return bandwidth * oi + peak_flops",
     "return min(peak_flops, bandwidth * oi)"),
    ("return nx * ny * nz * elem_bytes",
     "return 2 * nx * ny * nz * elem_bytes"),
    ('if ws <= config["l3_size"]:',
     'if config["l3_size"] is not None and ws <= config["l3_size"]:'),
])

# ============================================================
# Fix 8-9: scaling.py — Amdahl division + Gustafson subtraction
# ============================================================
patch_file("/app/scaling.py", [
    ("f_serial + f_parallel * num_procs",
     "f_serial + f_parallel / num_procs"),
    ("num_procs + f_serial * (num_procs - 1)",
     "num_procs - f_serial * (num_procs - 1)"),
])

# ============================================================
# Fix 10: metrics.py — harmonic mean
# ============================================================
patch_file("/app/metrics.py", [
    ("return sum(valid) / n",
     "return n / sum(1.0 / e for e in valid)"),
])

# ============================================================
# Fix 11: C kernel — inner loop bound off-by-one
# ============================================================
patch_file("/app/kernels/stencil_kernel.c", [
    ("i <= nx - 1", "i < nx - 1"),
])

# ============================================================
# Fix 12: Makefile — add missing -shared flag for shared library
# ============================================================
with open("/app/Makefile") as f:
    makefile_content = f.read()
makefile_content = makefile_content.replace(
    "$(CC) $(CFLAGS) -o",
    "$(CC) $(CFLAGS) -shared -o"
)
with open("/app/Makefile", "w") as f:
    f.write(makefile_content)

# ============================================================
# Implementation 1: tiling.py — cache-aware 3D tile optimizer
# ============================================================
TILING_CODE = '''"""Cache-aware 3D tile size optimizer for stencil computations."""



def tile_working_set(tx, ty, tz, elem_bytes=8, stencil_radius=1, num_arrays=2):
    """Compute working set size for a tile including ghost zones.

    Working set = num_arrays * (tx + 2r) * (ty + 2r) * (tz + 2r) * elem_bytes
    """
    r = stencil_radius
    return num_arrays * (tx + 2 * r) * (ty + 2 * r) * (tz + 2 * r) * elem_bytes


def validate_tiling(tx, ty, tz, nx, ny, nz, cache_size_bytes,
                    elem_bytes=8, stencil_radius=1, num_arrays=2):
    """Check whether a tile configuration is valid.

    Returns (is_valid, reason) tuple.
    """
    if tx < 1 or ty < 1 or tz < 1:
        return False, "Tile dimensions must be >= 1"
    if tx > nx or ty > ny or tz > nz:
        return False, "Tile dimensions exceed grid dimensions"
    ws = tile_working_set(tx, ty, tz, elem_bytes, stencil_radius, num_arrays)
    if ws > cache_size_bytes:
        return False, f"Working set {ws} exceeds cache size {cache_size_bytes}"
    return True, "Valid"


def optimal_tile_3d(nx, ny, nz, cache_size_bytes, elem_bytes=8,
                    stencil_radius=1, num_arrays=2):
    """Find optimal 3D tile sizes for cache-aware blocking.

    Maximizes tile volume (tx*ty*tz) subject to the working set constraint:
      num_arrays * (tx+2r) * (ty+2r) * (tz+2r) * elem_bytes <= cache_size_bytes

    Uses exhaustive search over a bounded range derived from the constraint.
    """
    r = stencil_radius
    a = 2 * r
    max_elements = cache_size_bytes // (num_arrays * elem_bytes)

    if max_elements < (1 + a) ** 3:
        return (1, 1, 1)

    best = (1, 1, 1)
    best_vol = 1

    max_single = int(max_elements ** (1.0 / 3.0)) + 2

    for tz_val in range(min(nz, max_single), 0, -1):
        sheet = tz_val + a
        if sheet > max_elements:
            continue
        budget_2d = max_elements // sheet
        if budget_2d < (1 + a) * (1 + a):
            continue

        max_ty = min(ny, int(budget_2d ** 0.5) + 1)
        while max_ty > 0 and (max_ty + a) * (1 + a) > budget_2d:
            max_ty -= 1
        if max_ty < 1:
            continue

        for ty_val in range(max_ty, 0, -1):
            col = ty_val + a
            tx_budget = budget_2d // col - a
            if tx_budget < 1:
                break
            tx_val = min(nx, tx_budget)

            total = (tx_val + a) * col * sheet
            while total > max_elements and tx_val > 0:
                tx_val -= 1
                total = (tx_val + a) * col * sheet
            if tx_val < 1:
                break

            vol = tx_val * ty_val * tz_val
            if vol > best_vol:
                best = (tx_val, ty_val, tz_val)
                best_vol = vol

        if tz_val * ny * nx <= best_vol:
            break

    return best
'''

with open("/app/tiling.py", "w") as f:
    f.write(TILING_CODE)


# ============================================================
# Implementation 2: analyze.py — full analysis pipeline
# ============================================================
ANALYZE_CODE = '''"""Analysis pipeline for multi-architecture stencil performance evaluation."""


import ctypes
import json
import sys
sys.path.insert(0, "/app")

from config_loader import load_all_configs
from stencil import jacobi_7pt_flops, jacobi_7pt_bytes, operational_intensity
from roofline import ridge_point, attainable_performance, effective_bandwidth
from scaling import amdahl_speedup, gustafson_speedup
from metrics import performance_portability
from tiling import optimal_tile_3d


def run_analysis():
    """Run the complete analysis pipeline and write results.json."""
    configs = load_all_configs("/app/configs")

    NX, NY, NZ = 100, 100, 100

    architectures = {}
    efficiencies = []

    for name in sorted(configs.keys()):
        cfg = configs[name]

        flops = jacobi_7pt_flops(NX, NY, NZ)
        byte_traffic = jacobi_7pt_bytes(
            NX, NY, NZ,
            elem_bytes=cfg["elem_bytes"],
            write_allocate=cfg["write_allocate"]
        )
        oi = operational_intensity(flops, byte_traffic)

        bw = effective_bandwidth(NX, NY, NZ, cfg)
        predicted = attainable_performance(oi, cfg["peak_flops"], bw)

        tile = optimal_tile_3d(
            NX, NY, NZ,
            cfg["l2_size"],
            elem_bytes=cfg["elem_bytes"],
            stencil_radius=1,
            num_arrays=2
        )

        amdahl = amdahl_speedup(16, 0.95)
        gustafson_val = gustafson_speedup(16, 0.05)

        eff = predicted / cfg["peak_flops"]
        efficiencies.append(eff)

        architectures[name] = {
            "peak_flops": cfg["peak_flops"],
            "dram_bandwidth": cfg["dram_bandwidth"],
            "ridge_point": ridge_point(cfg["peak_flops"], cfg["dram_bandwidth"]),
            "stencil_7pt": {
                "grid": [NX, NY, NZ],
                "flops": flops,
                "bytes": byte_traffic,
                "oi": oi,
                "predicted_perf": predicted,
            },
            "optimal_l2_tile": list(tile),
            "amdahl_16_095": amdahl,
            "gustafson_16_005": gustafson_val,
        }

    phi = performance_portability(efficiencies)

    # Load C verification kernel
    lib = ctypes.CDLL("/app/kernels/stencil_kernel.so")
    lib.stencil_checksum.restype = ctypes.c_double
    lib.stencil_checksum.argtypes = [ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int]
    v_nx, v_ny, v_nz, v_iter = 10, 10, 10, 10
    rms = lib.stencil_checksum(v_nx, v_ny, v_nz, v_iter)

    results = {
        "architectures": architectures,
        "portability": {
            "efficiencies": efficiencies,
            "phi": phi,
        },
        "verification": {
            "grid": [v_nx, v_ny, v_nz],
            "iterations": v_iter,
            "rms_checksum": rms,
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    run_analysis()
'''

with open("/app/analyze.py", "w") as f:
    f.write(ANALYZE_CODE)


print("All bugs fixed and missing components implemented.")
