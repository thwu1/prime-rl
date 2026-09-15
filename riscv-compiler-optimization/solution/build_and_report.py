#!/usr/bin/env python3
"""
Cross-compile comparison, build optimized firmware, and generate reports.
"""

import csv
import json
import os
import subprocess
import tempfile

SRC_DIR = "/app/src"
BASELINE_DIR = "/app/baseline"
OPTIMIZED_DIR = "/app/optimized"
RESULTS_DIR = "/app/results"
SOURCE_FILES = ["main.c", "crypto.c", "math_utils.c", "compress.c"]
OBJECTS = ["main.o", "crypto.o", "math_utils.o", "compress.o"]

GCC = "riscv64-linux-gnu-gcc"
CLANG_BASE = [
    "clang", "--target=riscv64-linux-gnu",
    "--sysroot=/usr/riscv64-linux-gnu",
    "--gcc-toolchain=/usr",
]


def get_text_size(obj_path):
    r = subprocess.run(
        ["riscv64-linux-gnu-size", obj_path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"size failed on {obj_path}: {r.stderr}")
    lines = r.stdout.strip().split("\n")
    return int(lines[1].split()[0])


def compile_obj(compiler_cmd, flags, src, out):
    cmd = compiler_cmd + flags + ["-c", src, "-o", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Compile failed: {' '.join(cmd)}\n{r.stderr}")


# ── Step 1: Baseline measurement ───────────────────────────────────────

baseline_sizes = {}
baseline_total = 0
for obj in OBJECTS:
    sz = get_text_size(f"{BASELINE_DIR}/{obj}")
    baseline_sizes[obj] = sz
    baseline_total += sz
print(f"Baseline total .text: {baseline_total}")


# ── Step 2: Comparison matrix ──────────────────────────────────────────

COMMON_FLAGS_GC = ["-march=rv64gc", "-mabi=lp64d"]

gcc_opt_levels = ["-O3", "-O2", "-Os"]
clang_opt_levels = ["-O2", "-Os", "-Oz"]

comparison_rows = []

with tempfile.TemporaryDirectory() as tmpdir:
    for src_name in SOURCE_FILES:
        src_path = f"{SRC_DIR}/{src_name}"

        # GCC variants
        for opt in gcc_opt_levels:
            out = f"{tmpdir}/{src_name}.gcc.{opt}.o"
            compile_obj([GCC], [opt] + COMMON_FLAGS_GC, src_path, out)
            sz = get_text_size(out)
            comparison_rows.append({
                "file": src_name,
                "compiler": "gcc",
                "flags": f"{opt} -march=rv64gc -mabi=lp64d",
                "text_size": sz,
            })

        # Clang variants
        for opt in clang_opt_levels:
            out = f"{tmpdir}/{src_name}.clang.{opt}.o"
            compile_obj(CLANG_BASE, [opt] + COMMON_FLAGS_GC, src_path, out)
            sz = get_text_size(out)
            comparison_rows.append({
                "file": src_name,
                "compiler": "clang",
                "flags": f"{opt} -march=rv64gc -mabi=lp64d",
                "text_size": sz,
            })

# Write comparison CSV
with open(f"{RESULTS_DIR}/comparison.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["file", "compiler", "flags", "text_size"])
    writer.writeheader()
    writer.writerows(comparison_rows)
print(f"Wrote {RESULTS_DIR}/comparison.csv with {len(comparison_rows)} rows.")


# ── Step 3: Determine optimal per-file configuration ───────────────────

best_per_file = {}
for src_name in SOURCE_FILES:
    file_rows = [r for r in comparison_rows if r["file"] == src_name]
    best = min(file_rows, key=lambda r: r["text_size"])
    best_per_file[src_name] = best
    print(f"  Best for {src_name}: {best['compiler']} {best['flags']}"
          f" -> {best['text_size']}")


# ── Step 4: Generate Makefile and build ────────────────────────────────

def make_compile_cmd(best_info):
    """Generate a Makefile compile command from the best configuration."""
    compiler = best_info["compiler"]
    flags = best_info["flags"]
    if compiler == "gcc":
        return (f"riscv64-linux-gnu-gcc {flags}"
                f" -ffunction-sections -fdata-sections -c $< -o $@")
    else:
        return (f"clang --target=riscv64-linux-gnu"
                f" --sysroot=/usr/riscv64-linux-gnu --gcc-toolchain=/usr"
                f" {flags} -ffunction-sections -fdata-sections -c $< -o $@")


makefile_lines = [
    "SRC_DIR = /app/src",
    "OBJS = main.o crypto.o math_utils.o compress.o",
    "",
    "all: $(OBJS) firmware.elf",
    "",
]

for src_name in SOURCE_FILES:
    obj_name = src_name.replace(".c", ".o")
    best = best_per_file[src_name]
    cmd = make_compile_cmd(best)
    makefile_lines.append(
        f"{obj_name}: $(SRC_DIR)/{src_name} $(SRC_DIR)/common.h")
    makefile_lines.append(f"\t{cmd}")
    makefile_lines.append("")

makefile_lines.extend([
    "firmware.elf: $(OBJS)",
    "\triscv64-linux-gnu-gcc $(OBJS) -static -Wl,--gc-sections -lm -o $@",
    "",
    "clean:",
    "\trm -f $(OBJS) firmware.elf",
    "",
    ".PHONY: all clean",
])

makefile_content = "\n".join(makefile_lines) + "\n"

with open(f"{OPTIMIZED_DIR}/Makefile", "w") as f:
    f.write(makefile_content)

# Build via make
r = subprocess.run(["make", "-C", OPTIMIZED_DIR], capture_output=True, text=True)
if r.returncode != 0:
    print(f"make stdout: {r.stdout}")
    print(f"make stderr: {r.stderr}")
    raise RuntimeError("Optimized build failed")
print("Optimized build complete.")


# ── Step 5: Measure optimized sizes ────────────────────────────────────

optimized_sizes = {}
optimized_total = 0
per_file_report = {}
for i, obj in enumerate(OBJECTS):
    sz = get_text_size(f"{OPTIMIZED_DIR}/{obj}")
    optimized_sizes[obj] = sz
    optimized_total += sz
    src = SOURCE_FILES[i]
    best = best_per_file[src]
    per_file_report[src] = {
        "compiler": best["compiler"],
        "flags": best["flags"],
        "text_size": sz,
    }

reduction_pct = (1 - optimized_total / baseline_total) * 100
print(f"Optimized total .text: {optimized_total}")
print(f"Reduction: {reduction_pct:.1f}%")


# ── Step 6: Generate report.json ───────────────────────────────────────

report = {
    "baseline_total_text": baseline_total,
    "optimized_total_text": optimized_total,
    "reduction_pct": round(reduction_pct, 1),
    "per_file": per_file_report,
    "techniques_used": [
        "RISC-V compressed instruction extension (rv64gc: 'C' extension reduces code "
        "size ~25-30% by encoding common instructions in 16 bits instead of 32)",
        "Size optimization flag (-Os/-Oz instead of -O3, avoiding loop unrolling of "
        "XTEA 32-round cipher and 4x4 matrix multiply, and reducing inlining)",
        "Per-file compiler selection (comparing GCC vs Clang across optimization "
        "levels to find the smallest .text output per translation unit)",
        "Function/data section splitting (-ffunction-sections -fdata-sections) with "
        "linker garbage collection (-Wl,--gc-sections) to remove dead code "
        "(unused_bessel_j0, unused_gamma_approx) from the linked binary",
        "Fixed undefined behavior in scale_value() to ensure correctness at all "
        "optimization levels",
    ],
    "bug_description": (
        "scale_value() in math_utils.c multiplies two int arguments (x * factor) "
        "which is undefined behavior when the result overflows signed 32-bit range. "
        "The subsequent overflow check (result / factor != x) is also undefined "
        "because it relies on the result of the UB multiplication. At -O3, the "
        "compiler assumes signed overflow never occurs per the C standard, and "
        "optimizes away the overflow check entirely, causing the function to return "
        "a garbage wrapped value instead of clamping to INT_MAX/INT_MIN. Fixed by "
        "widening the multiplication to int64_t before comparing against INT_MAX/"
        "INT_MIN, which is well-defined at all optimization levels."
    ),
}

with open(f"{RESULTS_DIR}/report.json", "w") as f:
    json.dump(report, f, indent=2)
print(f"Wrote {RESULTS_DIR}/report.json")
