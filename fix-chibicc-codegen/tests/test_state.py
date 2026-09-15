
import subprocess
import os
import tempfile

CHIBICC = "/app/chibicc/chibicc"
CHIBICC_DIR = "/app/chibicc"
OPTIMIZER = "/app/optimizer.py"
BENCHMARK = "/app/benchmark.c"


def _compile_run(c_code, optimize=False, timeout=30):
    """Compile C code with chibicc, optionally optimize asm, assemble with gcc, run."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "prog.c")
        asm_path = os.path.join(d, "prog.s")
        opt_path = os.path.join(d, "prog_opt.s")
        binary = os.path.join(d, "prog")

        with open(src, "w") as f:
            f.write(c_code)

        r = subprocess.run(
            [CHIBICC, "-Iinclude", "-S", "-o", asm_path, src],
            cwd=CHIBICC_DIR, capture_output=True, text=True, timeout=timeout,
        )
        assert r.returncode == 0, f"chibicc -S failed: {r.stderr}"

        target = asm_path
        if optimize:
            with open(asm_path) as f:
                asm_text = f.read()
            r = subprocess.run(
                ["python3", OPTIMIZER],
                input=asm_text,
                capture_output=True, text=True, timeout=timeout,
            )
            assert r.returncode == 0, f"optimizer failed (rc={r.returncode}): {r.stderr}"
            with open(opt_path, "w") as f:
                f.write(r.stdout)
            target = opt_path

        r = subprocess.run(
            ["gcc", "-o", binary, target],
            capture_output=True, text=True, timeout=timeout,
        )
        assert r.returncode == 0, f"gcc assemble/link failed: {r.stderr}"

        r = subprocess.run([binary], capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout, r.stderr


def _get_asm(c_code_or_path, is_path=False):
    """Return chibicc assembly output for C code (string or file path)."""
    with tempfile.TemporaryDirectory() as d:
        if is_path:
            src = c_code_or_path
        else:
            src = os.path.join(d, "prog.c")
            with open(src, "w") as f:
                f.write(c_code_or_path)
        asm_path = os.path.join(d, "prog.s")
        r = subprocess.run(
            [CHIBICC, "-Iinclude", "-S", "-o", asm_path, src],
            cwd=CHIBICC_DIR, capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"chibicc failed: {r.stderr}"
        with open(asm_path) as f:
            return f.read()


def _run_optimizer(asm_text):
    """Run the optimizer on assembly text, return optimized text."""
    r = subprocess.run(
        ["python3", OPTIMIZER],
        input=asm_text,
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"optimizer failed: {r.stderr}"
    return r.stdout


def _count_instructions(asm_text):
    """Count machine instructions (indented non-directive, non-label, non-comment lines)."""
    count = 0
    for line in asm_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(".") or stripped.startswith("#"):
            continue
        if stripped.endswith(":"):
            continue
        if line[0] in (" ", "\t"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Meta tests
# ---------------------------------------------------------------------------

def test_optimizer_exists():
    """Optimizer script must exist at /app/optimizer.py."""
    assert os.path.isfile(OPTIMIZER), f"{OPTIMIZER} not found"


def test_optimizer_runs_on_trivial_input():
    """Optimizer must accept valid assembly and produce output."""
    trivial = (
        "  .text\n  .globl main\nmain:\n"
        "  push %rbp\n  mov %rsp, %rbp\n"
        "  mov $0, %eax\n  pop %rbp\n  ret\n"
    )
    r = subprocess.run(
        ["python3", OPTIMIZER],
        input=trivial, capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"Optimizer crashed: {r.stderr}"
    assert "ret" in r.stdout, "Optimizer produced no meaningful output"


# ---------------------------------------------------------------------------
# Correctness: arithmetic
# ---------------------------------------------------------------------------

_ARITH_CODE = r"""
#include <stdio.h>
int f(int a, int b, int c) { return (a + b) * c - a; }
int g(int x) { return x * x + 2 * x + 1; }
int h(int a, int b) { return a / b + a % b; }
int main(void) {
    printf("%d\n", f(3, 4, 5));
    printf("%d\n", g(7));
    printf("%d\n", h(17, 5));
    printf("%d\n", h(-17, 5));
    return 0;
}
"""
_ARITH_EXPECTED = "32\n64\n5\n-5\n"


def test_correctness_arithmetic():
    """Arithmetic with +, *, /, % must produce correct results after optimization."""
    rc, out, _ = _compile_run(_ARITH_CODE, optimize=False)
    assert rc == 0 and out == _ARITH_EXPECTED
    rc, out, _ = _compile_run(_ARITH_CODE, optimize=True)
    assert rc == 0 and out == _ARITH_EXPECTED, f"Optimized output wrong: {out!r}"


# ---------------------------------------------------------------------------
# Correctness: loops and control flow
# ---------------------------------------------------------------------------

_LOOP_CODE = r"""
#include <stdio.h>
int sum_to(int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s = s + i;
    return s;
}
int count_bits(unsigned int x) {
    int c = 0;
    while (x) { c = c + (x & 1); x = x >> 1; }
    return c;
}
int main(void) {
    printf("%d\n", sum_to(10));
    printf("%d\n", sum_to(100));
    printf("%d\n", count_bits(0xff));
    printf("%d\n", count_bits(0x55555555));
    return 0;
}
"""
_LOOP_EXPECTED = "45\n4950\n8\n16\n"


def test_correctness_loops():
    """Loops with labels must be handled correctly (no optimization across labels)."""
    rc, out, _ = _compile_run(_LOOP_CODE, optimize=False)
    assert rc == 0 and out == _LOOP_EXPECTED
    rc, out, _ = _compile_run(_LOOP_CODE, optimize=True)
    assert rc == 0 and out == _LOOP_EXPECTED, f"Optimized output wrong: {out!r}"


# ---------------------------------------------------------------------------
# Correctness: pointers and arrays
# ---------------------------------------------------------------------------

_PTR_CODE = r"""
#include <stdio.h>
int sum_arr(int *a, int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s = s + a[i];
    return s;
}
int main(void) {
    int arr[] = {10, 20, 30, 40, 50};
    printf("%d\n", sum_arr(arr, 5));
    int *p = arr + 2;
    printf("%d\n", *p);
    printf("%d\n", *(p + 1));
    return 0;
}
"""
_PTR_EXPECTED = "150\n30\n40\n"


def test_correctness_pointers():
    """Pointer arithmetic and array indexing must remain correct after optimization."""
    rc, out, _ = _compile_run(_PTR_CODE, optimize=False)
    assert rc == 0 and out == _PTR_EXPECTED
    rc, out, _ = _compile_run(_PTR_CODE, optimize=True)
    assert rc == 0 and out == _PTR_EXPECTED, f"Optimized output wrong: {out!r}"


# ---------------------------------------------------------------------------
# Correctness: structs
# ---------------------------------------------------------------------------

_STRUCT_CODE = r"""
#include <stdio.h>
struct Pt { int x; int y; };
int dot(struct Pt a, struct Pt b) { return a.x * b.x + a.y * b.y; }
int main(void) {
    struct Pt p = {3, 4};
    struct Pt q = {1, 2};
    printf("%d\n", dot(p, q));
    printf("%d\n", p.x + q.y);
    return 0;
}
"""
_STRUCT_EXPECTED = "11\n5\n"


def test_correctness_structs():
    """Struct member access and passing must remain correct after optimization."""
    rc, out, _ = _compile_run(_STRUCT_CODE, optimize=False)
    assert rc == 0 and out == _STRUCT_EXPECTED
    rc, out, _ = _compile_run(_STRUCT_CODE, optimize=True)
    assert rc == 0 and out == _STRUCT_EXPECTED, f"Optimized output wrong: {out!r}"


# ---------------------------------------------------------------------------
# Correctness: the full benchmark program
# ---------------------------------------------------------------------------

_BENCH_EXPECTED = (
    "6\n61\n15\n7\n7\n720\n55\n55\n"
    "6\n6\n2\n0\n52651\n60\n"
    "6\n1024\n111\n15\n330\n"
)


def test_correctness_benchmark():
    """Full benchmark program must produce identical output after optimization."""
    with open(BENCHMARK) as f:
        code = f.read()
    rc, out, err = _compile_run(code, optimize=False)
    assert rc == 0, f"Unoptimized benchmark failed: {err}"
    assert out.strip() == _BENCH_EXPECTED.strip(), f"Unopt wrong: {out!r}"

    rc, out_opt, err = _compile_run(code, optimize=True)
    assert rc == 0, f"Optimized benchmark failed: {err}"
    assert out_opt.strip() == _BENCH_EXPECTED.strip(), (
        f"Optimized output mismatch.\nExpected:\n{_BENCH_EXPECTED}\nGot:\n{out_opt}"
    )


# ---------------------------------------------------------------------------
# Effectiveness: instruction count reduction
# ---------------------------------------------------------------------------

def test_instruction_reduction():
    """Optimizer must achieve >= 12% instruction count reduction on the benchmark."""
    orig_asm = _get_asm(BENCHMARK, is_path=True)
    opt_asm = _run_optimizer(orig_asm)

    orig_count = _count_instructions(orig_asm)
    opt_count = _count_instructions(opt_asm)

    assert orig_count > 0, "No instructions found in original assembly"
    reduction = (orig_count - opt_count) / orig_count * 100
    assert reduction >= 12.0, (
        f"Instruction reduction {reduction:.1f}% < 12.0%. "
        f"Original: {orig_count}, Optimized: {opt_count}"
    )


# ---------------------------------------------------------------------------
# Correctness: complex expression nesting
# ---------------------------------------------------------------------------

_NESTED_CODE = r"""
#include <stdio.h>
int deep(int a, int b, int c, int d) {
    return ((a + b) * (c + d)) - ((a - b) * (c - d));
}
int cond_chain(int x) {
    if (x > 100) return x - 100;
    else if (x > 50) return x - 50;
    else if (x > 0) return x;
    else return -x;
}
int main(void) {
    printf("%d\n", deep(1, 2, 3, 4));
    printf("%d\n", deep(5, 5, 5, 5));
    printf("%d\n", cond_chain(150));
    printf("%d\n", cond_chain(75));
    printf("%d\n", cond_chain(25));
    printf("%d\n", cond_chain(-10));
    return 0;
}
"""
_NESTED_EXPECTED = "20\n100\n50\n25\n25\n10\n"


def test_correctness_nested_expressions():
    """Deeply nested binary expressions must remain correct."""
    rc, out, _ = _compile_run(_NESTED_CODE, optimize=False)
    assert rc == 0 and out == _NESTED_EXPECTED
    rc, out, _ = _compile_run(_NESTED_CODE, optimize=True)
    assert rc == 0 and out == _NESTED_EXPECTED, f"Optimized output wrong: {out!r}"


# ---------------------------------------------------------------------------
# Correctness: function calls with many arguments
# ---------------------------------------------------------------------------

_CALL_CODE = r"""
#include <stdio.h>
int add6(int a, int b, int c, int d, int e, int f) {
    return a + b + c + d + e + f;
}
int main(void) {
    printf("%d\n", add6(1, 2, 3, 4, 5, 6));
    printf("%d\n", add6(10, 20, 30, 40, 50, 60));
    return 0;
}
"""
_CALL_EXPECTED = "21\n210\n"


def test_correctness_many_args():
    """Function calls with 6 register arguments must remain correct."""
    rc, out, _ = _compile_run(_CALL_CODE, optimize=False)
    assert rc == 0 and out == _CALL_EXPECTED
    rc, out, _ = _compile_run(_CALL_CODE, optimize=True)
    assert rc == 0 and out == _CALL_EXPECTED, f"Optimized output wrong: {out!r}"
