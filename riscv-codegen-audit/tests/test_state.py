"""Tests for RISC-V cross-compiler codegen analysis task."""

import json
import os
import re
import subprocess

KERNELS = ["saxpy", "matmul", "poly_eval", "stencil"]
GCC = "riscv64-linux-gnu-gcc"
OBJDUMP = "riscv64-linux-gnu-objdump"
QEMU_CMD = "qemu-riscv64 -cpu rv64,v=true,vlen=256"
SCALAR_FLAGS = "-static -O2 -march=rv64gc -mabi=lp64d"
VECTOR_FLAGS = "-static -O2 -march=rv64gcv -mabi=lp64d"


def run(cmd, timeout=120):
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )


# ---------------------------------------------------------------------------
# Analysis report tests
# ---------------------------------------------------------------------------

class TestAnalysisReport:
    def test_analysis_file_exists(self):
        assert os.path.isfile("/app/analysis.json"), "analysis.json not found"

    def test_analysis_schema(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)

        assert "kernels" in data, "top-level 'kernels' key missing"
        assert "optimization_categories" in data, "'optimization_categories' missing"
        assert "summary" in data, "'summary' key missing"

        for k in KERNELS:
            assert k in data["kernels"], f"Kernel '{k}' missing from analysis"
            kd = data["kernels"][k]
            for compiler_key in ("gcc_scalar", "gcc_vector"):
                assert compiler_key in kd, (
                    f"'{compiler_key}' missing for kernel '{k}'"
                )
                entry = kd[compiler_key]
                assert "instruction_count" in entry, (
                    f"instruction_count missing in {k}/{compiler_key}"
                )
                assert isinstance(entry["instruction_count"], int)
                assert entry["instruction_count"] > 0, (
                    f"instruction_count must be > 0 for {k}/{compiler_key}"
                )

    def test_at_least_three_categories(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        cats = data["optimization_categories"]
        assert isinstance(cats, list)
        assert len(cats) >= 3, f"Need >= 3 categories, got {len(cats)}"

    def test_categories_have_required_fields(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)

        valid = {
            "missed_unrolling",
            "redundant_moves",
            "register_pressure",
            "missing_vectorization",
            "addressing_overhead",
            "branch_overhead",
            "constant_materialization",
            "suboptimal_scheduling",
            "spill_fill",
            "missed_fusion",
            "inefficient_prologue_epilogue",
        }
        for cat in data["optimization_categories"]:
            assert "category" in cat, "category field missing"
            assert "description" in cat, "description field missing"
            assert "affected_kernels" in cat, "affected_kernels field missing"
            assert cat["category"] in valid, (
                f"Invalid category: {cat['category']}"
            )
            assert len(cat["description"]) > 10, "description too short"
            assert len(cat["affected_kernels"]) > 0, "no affected kernels"

    def test_summary_field(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        s = data["summary"]
        assert "total_categories_found" in s
        assert isinstance(s["total_categories_found"], int)
        assert s["total_categories_found"] >= 3


# ---------------------------------------------------------------------------
# Optimized-kernel tests
# ---------------------------------------------------------------------------

class TestOptimizedKernels:

    def test_optimized_sources_exist(self):
        for k in KERNELS:
            p = f"/app/optimized/{k}_opt.c"
            assert os.path.isfile(p), f"Missing: {p}"

    def test_optimized_kernels_compile(self):
        os.makedirs("/app/build", exist_ok=True)
        for k in KERNELS:
            src = f"/app/optimized/{k}_opt.c"
            out = f"/app/build/{k}_opt"
            r = run(f"{GCC} {VECTOR_FLAGS} {src} -o {out} -lm")
            assert r.returncode == 0, (
                f"Compile failed for {k}_opt.c:\n{r.stderr}"
            )

    def test_reference_and_optimized_match(self):
        os.makedirs("/app/build", exist_ok=True)
        for k in KERNELS:
            # compile reference (scalar)
            ref_src = f"/app/kernels/{k}.c"
            ref_bin = f"/app/build/{k}_ref"
            r = run(f"{GCC} {SCALAR_FLAGS} {ref_src} -o {ref_bin} -lm")
            assert r.returncode == 0, f"Ref compile fail {k}: {r.stderr}"

            # compile optimized (vector)
            opt_src = f"/app/optimized/{k}_opt.c"
            opt_bin = f"/app/build/{k}_opt"
            r = run(f"{GCC} {VECTOR_FLAGS} {opt_src} -o {opt_bin} -lm")
            assert r.returncode == 0, f"Opt compile fail {k}: {r.stderr}"

            # run reference
            rr = run(f"{QEMU_CMD} {ref_bin}")
            assert rr.returncode == 0, f"Ref run fail {k}: {rr.stderr}"

            # run optimized
            ro = run(f"{QEMU_CMD} {opt_bin}")
            assert ro.returncode == 0, f"Opt run fail {k}: {ro.stderr}"

            ref_out = rr.stdout.strip()
            opt_out = ro.stdout.strip()
            assert ref_out == opt_out, (
                f"Output mismatch for {k}:\n"
                f"  ref: {ref_out}\n"
                f"  opt: {opt_out}"
            )

    def test_vector_instructions_in_optimized(self):
        """Optimized binaries must contain RISC-V vector instructions."""
        os.makedirs("/app/build", exist_ok=True)
        vec_pat = re.compile(
            r"\b(vle\d+|vse\d+|vfmacc|vfmadd|vfmul|vadd|vsub|vfadd|"
            r"vfsub|vmul|vsetvli|vsetivli|vredsum|vfredosum|vfmv|vmv|"
            r"vslide|vmerge|vlse|vsse)\b"
        )
        for k in KERNELS:
            opt_bin = f"/app/build/{k}_opt"
            if not os.path.isfile(opt_bin):
                src = f"/app/optimized/{k}_opt.c"
                run(f"{GCC} {VECTOR_FLAGS} {src} -o {opt_bin} -lm")
            r = run(f"{OBJDUMP} -d {opt_bin}")
            assert r.returncode == 0, f"objdump fail for {k}"
            assert vec_pat.search(r.stdout), (
                f"No RISC-V vector instructions found in optimized {k}"
            )


# ---------------------------------------------------------------------------
# Build infrastructure tests
# ---------------------------------------------------------------------------

class TestBuildInfrastructure:
    def test_build_script_exists(self):
        assert os.path.isfile("/app/build.sh"), "build.sh not found"

    def test_build_script_executable(self):
        assert os.access("/app/build.sh", os.X_OK), "build.sh not executable"
