
import csv
import json
import os
import subprocess

import pytest

OBJECTS = ["main.o", "crypto.o", "math_utils.o", "compress.o"]
BASELINE_DIR = "/app/baseline"
OPTIMIZED_DIR = "/app/optimized"
RESULTS_DIR = "/app/results"
SRC_DIR = "/app/src"


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kwargs)


def _get_text_size(obj_path):
    """Return .text section size for an ELF object/executable."""
    r = _run(["riscv64-linux-gnu-size", obj_path])
    if r.returncode != 0:
        return None
    lines = r.stdout.strip().split("\n")
    if len(lines) < 2:
        return None
    return int(lines[1].split()[0])


# ── 1. Output files exist ──────────────────────────────────────────────

class TestOutputFiles:
    def test_comparison_csv_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/comparison.csv")

    def test_report_json_exists(self):
        assert os.path.isfile(f"{RESULTS_DIR}/report.json")

    def test_makefile_exists(self):
        assert os.path.isfile(f"{OPTIMIZED_DIR}/Makefile")

    def test_optimized_objects_exist(self):
        for obj in OBJECTS:
            p = f"{OPTIMIZED_DIR}/{obj}"
            assert os.path.isfile(p), f"Missing {p}"

    def test_firmware_exists(self):
        assert os.path.isfile(f"{OPTIMIZED_DIR}/firmware.elf")


# ── 2. ELF validity ────────────────────────────────────────────────────

class TestElfValidity:
    def test_objects_are_riscv_elf(self):
        for obj in OBJECTS:
            p = f"{OPTIMIZED_DIR}/{obj}"
            r = _run(["file", p])
            assert "ELF" in r.stdout, f"{obj} not ELF: {r.stdout}"
            assert "RISC-V" in r.stdout, f"{obj} not RISC-V: {r.stdout}"
            assert "relocatable" in r.stdout, f"{obj} not relocatable: {r.stdout}"

    def test_firmware_is_riscv_elf(self):
        r = _run(["file", f"{OPTIMIZED_DIR}/firmware.elf"])
        assert "ELF" in r.stdout
        assert "RISC-V" in r.stdout


# ── 3. Comparison CSV ──────────────────────────────────────────────────

class TestComparisonCSV:
    @pytest.fixture(autouse=True)
    def load_csv(self):
        with open(f"{RESULTS_DIR}/comparison.csv") as f:
            self.reader_fieldnames = csv.DictReader(f).fieldnames
            f.seek(0)
            self.rows = list(csv.DictReader(f))

    def test_headers(self):
        for col in ("file", "compiler", "flags", "text_size"):
            assert col in self.reader_fieldnames, f"Missing column: {col}"

    def test_at_least_four_files(self):
        files = {r["file"] for r in self.rows}
        assert len(files) >= 4, f"Only {len(files)} files"

    def test_both_compilers_present(self):
        compilers = {r["compiler"].lower() for r in self.rows}
        assert any("gcc" in c for c in compilers), "No GCC results"
        assert any("clang" in c for c in compilers), "No Clang results"

    def test_positive_sizes(self):
        for r in self.rows:
            assert int(r["text_size"]) > 0, f"Bad size: {r}"

    def test_multiple_configs_per_file(self):
        from collections import defaultdict
        configs = defaultdict(set)
        for r in self.rows:
            configs[r["file"]].add((r["compiler"], r["flags"]))
        for f, cfgs in configs.items():
            assert len(cfgs) >= 3, f"Only {len(cfgs)} configs for {f}"


# ── 4. Report JSON ─────────────────────────────────────────────────────

class TestReportJSON:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(f"{RESULTS_DIR}/report.json") as f:
            self.report = json.load(f)

    def test_required_keys(self):
        for key in ("baseline_total_text", "optimized_total_text",
                     "reduction_pct", "per_file", "techniques_used",
                     "bug_description"):
            assert key in self.report, f"Missing key: {key}"

    def test_per_file_structure(self):
        pf = self.report["per_file"]
        assert isinstance(pf, dict)
        assert len(pf) >= 4
        for fname, info in pf.items():
            assert "compiler" in info
            assert "flags" in info
            assert "text_size" in info

    def test_techniques_nonempty(self):
        assert isinstance(self.report["techniques_used"], list)
        assert len(self.report["techniques_used"]) >= 2

    def test_reduction_consistent(self):
        base = self.report["baseline_total_text"]
        opt = self.report["optimized_total_text"]
        pct = self.report["reduction_pct"]
        assert base > 0 and opt > 0
        expected_pct = (1 - opt / base) * 100
        assert abs(pct - expected_pct) < 2.0, \
            f"Claimed {pct:.1f}% but computed {expected_pct:.1f}%"


# ── 5. Size reduction ──────────────────────────────────────────────────

class TestSizeReduction:
    def test_35pct_reduction(self):
        baseline_total = 0
        for obj in OBJECTS:
            sz = _get_text_size(f"{BASELINE_DIR}/{obj}")
            assert sz is not None, f"Cannot measure baseline {obj}"
            baseline_total += sz

        optimized_total = 0
        for obj in OBJECTS:
            sz = _get_text_size(f"{OPTIMIZED_DIR}/{obj}")
            assert sz is not None, f"Cannot measure optimized {obj}"
            optimized_total += sz

        reduction = (1 - optimized_total / baseline_total) * 100
        assert reduction >= 35.0, \
            f"Only {reduction:.1f}% reduction ({baseline_total} -> {optimized_total})"


# ── 6. UB bug fix ──────────────────────────────────────────────────────

class TestBugFix:
    def test_source_modified(self):
        r = _run(["diff",
                   f"{BASELINE_DIR}/original_math_utils.c",
                   f"{SRC_DIR}/math_utils.c"])
        assert r.returncode != 0, "math_utils.c was not modified"

    def test_report_mentions_ub(self):
        with open(f"{RESULTS_DIR}/report.json") as f:
            report = json.load(f)
        desc = report.get("bug_description", "").lower()
        assert any(kw in desc for kw in
                   ("overflow", "undefined", "ub ", "undefined behavior",
                    "int64", "wide")), \
            f"bug_description should mention overflow/UB: {desc}"

    def test_fixed_code_correct_at_O3(self):
        """Compile fixed source at -O3 and verify scale_value output under QEMU."""
        srcs = [f"{SRC_DIR}/{s}" for s in
                ("main.c", "crypto.c", "math_utils.c", "compress.c")]
        r = _run(
            ["riscv64-linux-gnu-gcc", "-O3", "-march=rv64gc", "-mabi=lp64d",
             "-static"] + srcs + ["-o", "/tmp/test_fw_o3", "-lm"]
        )
        assert r.returncode == 0, f"Compilation failed: {r.stderr}"

        r = _run(["qemu-riscv64-static", "/tmp/test_fw_o3"])
        assert r.returncode == 0, f"QEMU failed: {r.stderr}"

        # scale_value(100000, 30000) overflows int32.
        # Correct fix should clamp to INT_MAX = 2147483647.
        assert "2147483647" in r.stdout, \
            f"SCALE2 should be 2147483647 (INT_MAX). Got: {r.stdout}"


# ── 7. Makefile reproducibility ─────────────────────────────────────────

class TestMakefileReproducibility:
    def test_make_clean_and_rebuild(self):
        # Record existing sizes
        orig_sizes = {}
        for obj in OBJECTS:
            p = f"{OPTIMIZED_DIR}/{obj}"
            if os.path.isfile(p):
                orig_sizes[obj] = os.path.getsize(p)

        # Clean
        r = _run(["make", "-C", OPTIMIZED_DIR, "clean"])
        # Verify objects were removed
        for obj in OBJECTS:
            assert not os.path.isfile(f"{OPTIMIZED_DIR}/{obj}"), \
                f"clean did not remove {obj}"

        # Rebuild
        r = _run(["make", "-C", OPTIMIZED_DIR])
        assert r.returncode == 0, f"make failed: {r.stderr}\n{r.stdout}"

        # Verify objects recreated
        for obj in OBJECTS:
            p = f"{OPTIMIZED_DIR}/{obj}"
            assert os.path.isfile(p), f"Rebuild did not produce {obj}"

        # Verify firmware rebuilt
        assert os.path.isfile(f"{OPTIMIZED_DIR}/firmware.elf"), \
            "Rebuild did not produce firmware.elf"
