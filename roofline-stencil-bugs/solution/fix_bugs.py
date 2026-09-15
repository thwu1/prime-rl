#!/usr/bin/env python3
"""Fix all 7 bugs in the HPC proxy app performance analysis framework.

Bug 1 (stencil.py): jacobi_7pt_flops counts all grid points instead of interior.
Bug 2 (stencil.py): jacobi_7pt_bytes has spurious + elem_size in bytes_per_point.
Bug 3 (roofline.py): attainable_performance uses + instead of min().
Bug 4 (roofline.py): effective_bandwidth counts 1 array instead of 2 for working set.
Bug 5 (scaling.py): amdahl_speedup multiplies f_parallel * p instead of f_parallel / p.
Bug 6 (scaling.py): gustafson_speedup uses + instead of - for serial overhead.
Bug 7 (metrics.py): performance_portability computes arithmetic mean instead of harmonic.
"""


import os

def fix_file(path, replacements):
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)


# Bug 1: stencil FLOP count should use interior points only
# Bug 2: byte count should not have extra + elem_size
fix_file("/app/stencil.py", [
    (
        "n_points = nx * ny * nz",
        "n_points = (nx - 2) * (ny - 2) * (nz - 2)",
    ),
    (
        "(reads_per_point + writes_per_point) * elem_size + elem_size",
        "(reads_per_point + writes_per_point) * elem_size",
    ),
])

# Bug 3: roofline model uses min, not addition
# Bug 4: Jacobi working set = 2 arrays (input + output)
fix_file("/app/roofline.py", [
    (
        "return peak_bandwidth * oi + peak_flops",
        "return min(peak_flops, peak_bandwidth * oi)",
    ),
    (
        "working_set = nx * ny * nz * elem_size",
        "working_set = 2 * nx * ny * nz * elem_size",
    ),
])

# Bug 5: Amdahl divides parallel fraction by p
# Bug 6: Gustafson subtracts serial overhead
fix_file("/app/scaling.py", [
    (
        "return 1.0 / (f_serial + f_parallel * num_procs)",
        "return 1.0 / (f_serial + f_parallel / num_procs)",
    ),
    (
        "return num_procs + f_serial * (num_procs - 1)",
        "return num_procs - f_serial * (num_procs - 1)",
    ),
])

# Bug 7: performance portability uses harmonic mean
fix_file("/app/metrics.py", [
    (
        "return sum(valid) / n",
        "return n / sum(1.0 / e for e in valid)",
    ),
])

print("All 7 bugs fixed successfully.")
