#!/usr/bin/env python3
"""
Test suite for compiler optimization audit task.

"""

import json
import os
import re
import subprocess
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compile_to_asm(source_file, flags, output_file):
    """Compile a C source file to Intel-syntax x86-64 assembly."""
    cmd = (
        ["gcc"]
        + flags.split()
        + ["-S", "-masm=intel", "-fno-asynchronous-unwind-tables",
           "-o", output_file, source_file]
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"gcc failed: {result.stderr}"


def read_file(path):
    with open(path) as fh:
        return fh.read()


def extract_function_asm(full_asm, func_name):
    """Return the assembly lines belonging to *func_name*."""
    lines = full_asm.split("\n")
    collecting = False
    buf = []
    for line in lines:
        stripped = line.strip()
        # Start at the function label (column-0 identifier followed by ':')
        if stripped == f"{func_name}:":
            collecting = True
            continue
        if collecting:
            # Stop at the .size directive for this function
            if re.search(rf"\.size\s+{re.escape(func_name)}\b", line):
                break
            # Stop if we hit another global function label
            if (
                stripped.endswith(":")
                and not stripped.startswith(".L")
                and not stripped.startswith(".")
            ):
                break
            buf.append(line)
    return "\n".join(buf)


def extract_loop_body(func_asm):
    """Return the lines between a backward-branch label and its branch.

    Finds the inner-most loop (last backward branch in the listing).
    """
    lines = func_asm.split("\n")
    labels = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"(\.L\w+):$", stripped)
        if m:
            labels[m.group(1)] = idx

    # Walk backwards to find the last backward branch
    for idx in range(len(lines) - 1, -1, -1):
        stripped = lines[idx].strip()
        m = re.match(r"j\w+\s+(\.L\w+)", stripped)
        if m:
            target = m.group(1)
            if target in labels and labels[target] < idx:
                return "\n".join(lines[labels[target] + 1 : idx])

    return func_asm  # fallback: whole function


def load_report():
    with open("/app/report.json") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Tests — report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.isfile("/app/report.json"), "/app/report.json not found"

    def test_report_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)

    def test_report_has_required_sections(self):
        report = load_report()
        for section in [
            "divide_by_7",
            "modulo_13",
            "accumulate",
            "fill_multiples",
            "sum_floats",
            "categorize",
        ]:
            assert section in report, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Tests — division strength reduction
# ---------------------------------------------------------------------------

class TestDivisionStrengthReduction:
    @pytest.fixture(autouse=True)
    def _compile(self, tmp_path):
        self.asm_path = str(tmp_path / "target_O2.s")
        compile_to_asm("/app/target.c", "-O2", self.asm_path)
        self.full_asm = read_file(self.asm_path)
        self.report = load_report()

    def test_divide_by_7_no_div(self):
        func = extract_function_asm(self.full_asm, "divide_by_7")
        actual = bool(re.search(r"\b[i]?div\b", func, re.I))
        assert self.report["divide_by_7"]["has_div_instruction"] == actual

    def test_divide_by_7_has_mul(self):
        func = extract_function_asm(self.full_asm, "divide_by_7")
        actual = bool(re.search(r"\bi?mul\b", func, re.I))
        assert self.report["divide_by_7"]["has_mul_instruction"] == actual

    def test_modulo_13_no_div(self):
        func = extract_function_asm(self.full_asm, "modulo_13")
        actual = bool(re.search(r"\b[i]?div\b", func, re.I))
        assert self.report["modulo_13"]["has_div_instruction"] == actual

    def test_modulo_13_has_mul(self):
        func = extract_function_asm(self.full_asm, "modulo_13")
        actual = bool(re.search(r"\bi?mul\b", func, re.I))
        assert self.report["modulo_13"]["has_mul_instruction"] == actual


# ---------------------------------------------------------------------------
# Tests — aliasing
# ---------------------------------------------------------------------------

class TestAliasing:
    @pytest.fixture(autouse=True)
    def _compile(self, tmp_path):
        self.asm_path = str(tmp_path / "target_O2.s")
        compile_to_asm("/app/target.c", "-O2", self.asm_path)
        self.full_asm = read_file(self.asm_path)
        self.report = load_report()

    def test_accumulate_store_in_loop(self):
        func = extract_function_asm(self.full_asm, "accumulate")
        loop = extract_loop_body(func)
        # Memory store: mov DWORD PTR [...], reg  (destination is memory)
        actual = bool(re.search(r"mov\s+DWORD\s+PTR\s+\[", loop, re.I))
        assert self.report["accumulate"]["has_memory_write_in_loop_body"] == actual

    def test_accumulate_blocker_keyword(self):
        text = self.report["accumulate"]["optimization_blocker"].lower()
        keywords = ["alias", "aliasing", "may point", "overlap", "strict alias"]
        assert any(
            kw in text for kw in keywords
        ), f"Expected aliasing keyword in blocker, got: {text}"


# ---------------------------------------------------------------------------
# Tests — induction variable
# ---------------------------------------------------------------------------

class TestInductionVariable:
    @pytest.fixture(autouse=True)
    def _compile(self, tmp_path):
        self.asm_path = str(tmp_path / "target_O2.s")
        compile_to_asm("/app/target.c", "-O2", self.asm_path)
        self.full_asm = read_file(self.asm_path)
        self.report = load_report()

    def test_fill_multiples_no_imul(self):
        func = extract_function_asm(self.full_asm, "fill_multiples")
        loop = extract_loop_body(func)
        actual = bool(re.search(r"\bimul\b", loop, re.I))
        assert self.report["fill_multiples"]["has_imul_in_loop_body"] == actual

    def test_fill_multiples_add(self):
        func = extract_function_asm(self.full_asm, "fill_multiples")
        loop = extract_loop_body(func)
        actual = bool(re.search(r"\badd\b", loop, re.I))
        assert self.report["fill_multiples"]["has_compiler_introduced_add"] == actual


# ---------------------------------------------------------------------------
# Tests — vectorization
# ---------------------------------------------------------------------------

class TestVectorization:
    @pytest.fixture(autouse=True)
    def _compile(self, tmp_path):
        self.asm_O3 = str(tmp_path / "target_O3.s")
        self.asm_fast = str(tmp_path / "target_fast.s")
        compile_to_asm("/app/target.c", "-O3 -mavx2", self.asm_O3)
        compile_to_asm(
            "/app/target.c", "-O3 -mavx2 -ffast-math", self.asm_fast
        )
        self.report = load_report()

    def test_sum_floats_not_vectorized_O3_avx2(self):
        asm = read_file(self.asm_O3)
        func = extract_function_asm(asm, "sum_floats")
        actual = bool(re.search(r"\bv?addps\b", func, re.I))
        assert self.report["sum_floats"]["vectorized_at_O3_avx2"] == actual

    def test_sum_floats_vectorized_O3_avx2_fastmath(self):
        asm = read_file(self.asm_fast)
        func = extract_function_asm(asm, "sum_floats")
        actual = bool(re.search(r"\bv?addps\b", func, re.I))
        assert (
            self.report["sum_floats"]["vectorized_at_O3_avx2_ffast_math"]
            == actual
        )

    def test_vectorization_blocker_keyword(self):
        text = self.report["sum_floats"]["vectorization_blocker"].lower()
        keywords = [
            "associat",
            "floating",
            "ieee",
            "precision",
            "reorder",
            "ffast-math",
            "fast-math",
        ]
        assert any(
            kw in text for kw in keywords
        ), f"Expected float/associativity keyword in blocker, got: {text}"


# ---------------------------------------------------------------------------
# Tests — switch optimization
# ---------------------------------------------------------------------------

class TestSwitchOptimization:
    @pytest.fixture(autouse=True)
    def _compile(self, tmp_path):
        self.asm_path = str(tmp_path / "target_O2.s")
        compile_to_asm("/app/target.c", "-O2", self.asm_path)
        self.full_asm = read_file(self.asm_path)
        self.report = load_report()

    def test_categorize_jump_table(self):
        func = extract_function_asm(self.full_asm, "categorize")
        # indirect jmp through memory: jmp QWORD PTR [table+reg*8]
        has_indirect_jmp = bool(
            re.search(r"jmp\s+.*PTR\s*\[", func, re.I)
        ) or bool(
            # jmp rax  (computed target via register)
            re.search(r"jmp\s+r[a-d]x\b", func, re.I)
        )
        assert self.report["categorize"]["uses_jump_table"] == has_indirect_jmp

    def test_categorize_data_lookup(self):
        func = extract_function_asm(self.full_asm, "categorize")
        # GCC emits .CSWTCH.N labels for data lookup tables
        uses_lookup = bool(re.search(r"CSWTCH", func, re.I))
        assert self.report["categorize"]["uses_data_lookup_table"] == uses_lookup


# ---------------------------------------------------------------------------
# Tests — fixed accumulate
# ---------------------------------------------------------------------------

class TestFixedAccumulate:
    def test_fixed_file_exists(self):
        assert os.path.isfile("/app/fixed_accumulate.c"), \
            "/app/fixed_accumulate.c not found"

    def test_fixed_compiles(self, tmp_path):
        out = str(tmp_path / "fixed_O2.s")
        compile_to_asm("/app/fixed_accumulate.c", "-O2", out)

    def test_fixed_no_store_in_loop(self, tmp_path):
        out = str(tmp_path / "fixed_O2.s")
        compile_to_asm("/app/fixed_accumulate.c", "-O2", out)
        asm = read_file(out)
        func = extract_function_asm(asm, "accumulate")
        loop = extract_loop_body(func)
        has_store = bool(re.search(r"mov\s+DWORD\s+PTR\s+\[", loop, re.I))
        assert not has_store, (
            "Fixed accumulate still has a memory store in the loop body:\n"
            + loop
        )

    def test_fixed_correctness(self, tmp_path):
        """Link fixed_accumulate.c with a test harness and run."""
        harness = tmp_path / "harness.c"
        harness.write_text(
            '#include <stdio.h>\n'
            'extern void accumulate(int *total, const int *data, int n);\n'
            'int main(void) {\n'
            '    int data[] = {1,2,3,4,5,6,7,8,9,10};\n'
            '    int t = 0;\n'
            '    accumulate(&t, data, 10);\n'
            '    if (t != 55) { printf("FAIL: 55 != %d\\n", t); return 1; }\n'
            '    t = 100;\n'
            '    accumulate(&t, data, 5);\n'
            '    if (t != 115) { printf("FAIL: 115 != %d\\n", t); return 1; }\n'
            '    t = 0;\n'
            '    accumulate(&t, data, 0);\n'
            '    if (t != 0) { printf("FAIL: 0 != %d\\n", t); return 1; }\n'
            '    t = -10;\n'
            '    accumulate(&t, data, 3);\n'
            '    if (t != -4) { printf("FAIL: -4 != %d\\n", t); return 1; }\n'
            '    printf("PASS\\n");\n'
            '    return 0;\n'
            '}\n'
        )
        exe = str(tmp_path / "test_fixed")
        r = subprocess.run(
            ["gcc", "-O2", "-o", exe, str(harness), "/app/fixed_accumulate.c"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Link failed: {r.stderr}"
        r = subprocess.run([exe], capture_output=True, text=True)
        assert r.returncode == 0, f"Correctness check failed: {r.stdout}"
        assert "PASS" in r.stdout


# ---------------------------------------------------------------------------
# Tests — vectorized sum (create deliverable)
# ---------------------------------------------------------------------------

class TestVectorizedSum:
    def test_file_exists(self):
        assert os.path.isfile("/app/vectorized_sum.c"), \
            "/app/vectorized_sum.c not found"

    def test_compiles_with_mavx2(self, tmp_path):
        out = str(tmp_path / "vsum.s")
        compile_to_asm("/app/vectorized_sum.c", "-O3 -mavx2", out)

    def test_contains_packed_simd_add(self, tmp_path):
        """The implementation must use packed SIMD float additions."""
        out = str(tmp_path / "vsum.s")
        compile_to_asm("/app/vectorized_sum.c", "-O3 -mavx2", out)
        asm = read_file(out)
        func = extract_function_asm(asm, "sum_floats")
        has_packed = bool(re.search(r"\bv?addps\b", func, re.I))
        assert has_packed, (
            "vectorized_sum.c: sum_floats does not contain packed SIMD "
            "float additions (vaddps/addps) when compiled at -O3 -mavx2 "
            "(without -ffast-math):\n" + func
        )

    def test_no_ffast_math_flag_needed(self, tmp_path):
        """Confirm vectorization occurs at -O3 -mavx2 alone, not just
        with -ffast-math (which the original already achieves)."""
        out = str(tmp_path / "vsum_nofm.s")
        compile_to_asm("/app/vectorized_sum.c", "-O3 -mavx2", out)
        asm = read_file(out)
        func = extract_function_asm(asm, "sum_floats")
        assert re.search(r"\bv?addps\b", func, re.I), \
            "SIMD additions must appear without -ffast-math"

    def test_correctness(self, tmp_path):
        """Link vectorized_sum.c with a harness and verify results."""
        harness = tmp_path / "vsum_harness.c"
        harness.write_text(
            '#include <stdio.h>\n'
            'extern float sum_floats(const float *arr, int n);\n'
            'static int check(float got, float want, const char *label) {\n'
            '    float d = got - want;\n'
            '    if (d < 0.0f) d = -d;\n'
            '    if (d > 0.01f) {\n'
            '        printf("FAIL %s: expected %f got %f\\n",\n'
            '               label, (double)want, (double)got);\n'
            '        return 1;\n'
            '    }\n'
            '    return 0;\n'
            '}\n'
            'int main(void) {\n'
            '    int err = 0;\n'
            '    /* n=0 edge case */\n'
            '    float a0[] = {999.0f};\n'
            '    err |= check(sum_floats(a0, 0), 0.0f, "n=0");\n'
            '    /* n=1 */\n'
            '    float a1[] = {3.14f};\n'
            '    err |= check(sum_floats(a1, 1), 3.14f, "n=1");\n'
            '    /* n=10 (non-multiple of 8) */\n'
            '    float a10[] = {1,2,3,4,5,6,7,8,9,10};\n'
            '    err |= check(sum_floats(a10, 10), 55.0f, "n=10");\n'
            '    /* n=17 (odd, larger than one SIMD width) */\n'
            '    float a17[17];\n'
            '    for (int i = 0; i < 17; i++) a17[i] = (float)(i+1);\n'
            '    err |= check(sum_floats(a17, 17), 153.0f, "n=17");\n'
            '    /* n=64 (multiple of 8, larger) */\n'
            '    float a64[64];\n'
            '    for (int i = 0; i < 64; i++) a64[i] = 1.0f;\n'
            '    err |= check(sum_floats(a64, 64), 64.0f, "n=64");\n'
            '    if (err) return 1;\n'
            '    printf("PASS\\n");\n'
            '    return 0;\n'
            '}\n'
        )
        exe = str(tmp_path / "test_vsum")
        r = subprocess.run(
            ["gcc", "-O3", "-mavx2", "-o", exe, str(harness),
             "/app/vectorized_sum.c"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"Compilation failed: {r.stderr}"
        r = subprocess.run([exe], capture_output=True, text=True)
        assert r.returncode == 0, f"Correctness check failed: {r.stdout}"
        assert "PASS" in r.stdout
