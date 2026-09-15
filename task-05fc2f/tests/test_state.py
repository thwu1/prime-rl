
"""
Tests for the chibicc peephole optimizer task.

Compiles C programs with chibicc, runs the optimizer on the assembly output,
assembles and links the optimized result, runs the binary, and checks
both correctness (exit code) and optimization effectiveness (instruction
count reduction).

The C programs here are NOT present in the Docker image — the optimizer
must be genuinely general-purpose.
"""

import os
import subprocess
import tempfile
import re
import pytest

CHIBICC = "/app/chibicc/chibicc"
OPTIMIZER = "/app/optimize"

# ---------------------------------------------------------------------------
# Test C programs: each returns 0 on success, non-zero on failure.
# These are deliberately different from the /app/examples/ programs.
# ---------------------------------------------------------------------------

PROGRAMS = {
    "sequential_arith": r"""
int main() {
    int a = 10;
    int b = 20;
    int c = 30;
    int x = a + b;
    int y = b * c;
    int z = x + y;
    int w = z - a + b;
    if (w != 640) return 1;
    int p = a * b + c;
    int q = p - x + y;
    if (q != 800) return 2;
    return 0;
}
""",

    "function_calls": r"""
int add(int a, int b) { return a + b; }
int mul(int a, int b) { return a * b; }
int sub(int a, int b) { return a - b; }

int main() {
    int x = add(3, 4);
    if (x != 7) return 1;
    int y = mul(x, 5);
    if (y != 35) return 2;
    int z = add(y, mul(2, 3));
    if (z != 41) return 3;
    int w = sub(mul(add(1, 2), 10), 5);
    if (w != 25) return 4;
    return 0;
}
""",

    "loop_sum": r"""
int main() {
    int sum = 0;
    for (int i = 1; i <= 100; i = i + 1) {
        sum = sum + i;
    }
    if (sum != 5050) return 1;

    int prod = 1;
    for (int j = 1; j <= 6; j = j + 1) {
        prod = prod * j;
    }
    if (prod != 720) return 2;

    return 0;
}
""",

    "nested_conditionals": r"""
int classify(int n) {
    if (n < 0) return 0 - 1;
    if (n == 0) return 0;
    if (n < 10) return 1;
    if (n < 100) return 2;
    return 3;
}

int main() {
    int a = classify(0 - 5);
    int b = classify(0);
    int c = classify(7);
    int d = classify(42);
    int e = classify(100);
    int sum = a + b + c + d + e;
    if (sum != 5) return 1;
    if (a != 0 - 1) return 2;
    if (e != 3) return 3;
    return 0;
}
""",

    "multi_expression": r"""
int compute(int a, int b, int c, int d) {
    int r1 = a + b;
    int r2 = c + d;
    int r3 = r1 * r2;
    int r4 = r3 - a;
    int r5 = r4 + b * c;
    return r5;
}

int main() {
    int v = compute(2, 3, 4, 5);
    if (v != 55) return 1;
    int w = compute(1, 1, 1, 1);
    if (w != 4) return 2;
    int x = compute(10, 20, 30, 40);
    if (x != 2690) return 3;
    return 0;
}
""",

    "chained_ops": r"""
int main() {
    int a = 5;
    int b = 10;
    int c = 15;
    int d = 20;
    int e = 25;

    int r1 = a + b + c + d + e;
    if (r1 != 75) return 1;

    int r2 = a * b + c * d - e;
    if (r2 != 325) return 2;

    int r3 = (a + b) * (c - d) + e;
    if (r3 != 0 - 50) return 3;

    int r4 = a + b * c + d * e;
    if (r4 != 655) return 4;

    int r5 = (r1 + r2) * 2 - r4;
    if (r5 != 145) return 5;

    return 0;
}
""",
}


def is_instruction(line: str) -> bool:
    """Check if an assembly line is an actual instruction (not label/directive/comment/empty)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("#") or s.startswith("//"):
        return False
    if s.endswith(":"):
        return False
    if s.startswith("."):
        return False
    return True


def count_instructions(asm_path: str) -> int:
    """Count actual instructions in an assembly file."""
    with open(asm_path) as f:
        return sum(1 for line in f if is_instruction(line))


def compile_optimize_run(name: str, src: str, tmpdir: str):
    """Compile C source with chibicc, optimize, assemble, link, and run.

    Returns (exit_code, orig_count, opt_count).
    """
    src_path = os.path.join(tmpdir, f"{name}.c")
    orig_asm = os.path.join(tmpdir, f"{name}.s")
    opt_asm = os.path.join(tmpdir, f"{name}_opt.s")
    binary = os.path.join(tmpdir, name)

    with open(src_path, "w") as f:
        f.write(src)

    # Compile to assembly with chibicc
    r = subprocess.run(
        [CHIBICC, "-S", "-o", orig_asm, src_path],
        capture_output=True, text=True, timeout=30,
        cwd="/app/chibicc",
    )
    assert r.returncode == 0, f"chibicc failed on {name}:\n{r.stderr}"

    orig_count = count_instructions(orig_asm)

    # Run optimizer
    assert os.path.isfile(OPTIMIZER), f"Optimizer not found at {OPTIMIZER}"
    assert os.access(OPTIMIZER, os.X_OK), f"Optimizer at {OPTIMIZER} is not executable"

    with open(opt_asm, "w") as out_f:
        r = subprocess.run(
            [OPTIMIZER, orig_asm],
            stdout=out_f, stderr=subprocess.PIPE, text=True, timeout=30,
        )
    assert r.returncode == 0, f"Optimizer failed on {name}:\n{r.stderr}"

    opt_count = count_instructions(opt_asm)

    # Assemble and link with gcc
    r = subprocess.run(
        ["gcc", "-o", binary, opt_asm, "-no-pie"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"gcc failed to assemble/link {name}:\n{r.stderr}"

    # Run
    r = subprocess.run(
        [binary],
        capture_output=True, text=True, timeout=10,
    )

    return r.returncode, orig_count, opt_count


class TestOptimizerCorrectness:
    """Verify that optimized assembly produces correct runtime behavior."""

    @pytest.fixture(scope="class")
    def results(self):
        """Compile, optimize, and run all programs once."""
        tmpdir = tempfile.mkdtemp(prefix="opttest_")
        out = {}
        for name, src in PROGRAMS.items():
            out[name] = compile_optimize_run(name, src, tmpdir)
        return out

    @pytest.mark.parametrize("name", list(PROGRAMS.keys()))
    def test_correctness(self, results, name):
        """Optimized binary must exit with code 0."""
        exit_code, orig, opt = results[name]
        assert exit_code == 0, (
            f"Program '{name}' exited with code {exit_code} after optimization "
            f"(orig={orig} insns, opt={opt} insns) — optimization broke correctness"
        )

    @pytest.mark.parametrize("name", list(PROGRAMS.keys()))
    def test_reduction_nonzero(self, results, name):
        """Each optimized program must have strictly fewer instructions."""
        _, orig, opt = results[name]
        assert opt < orig, (
            f"Program '{name}': no reduction (orig={orig}, opt={opt}). "
            f"Optimizer must reduce instruction count."
        )

    def test_average_reduction(self, results):
        """Average instruction count reduction must be >= 10%."""
        reductions = []
        for name, (_, orig, opt) in results.items():
            reduction = (orig - opt) / orig
            reductions.append(reduction)
        avg = sum(reductions) / len(reductions)
        details = "; ".join(
            f"{n}: {r[1]}->{r[2]} ({(r[1]-r[2])/r[1]*100:.1f}%)"
            for n, r in results.items()
        )
        assert avg >= 0.10, (
            f"Average reduction {avg*100:.1f}% < 10% required. "
            f"Per-program: {details}"
        )
