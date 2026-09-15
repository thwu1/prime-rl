
import subprocess
import re
import os
import hashlib
import pytest

BENCHMARK_DIR = "/app/build"
BENCHMARK_TIMEOUT = 180

_build_done = False
_build_error = None


def _ensure_built():
    """Build the DGEMM benchmark project (idempotent)."""
    global _build_done, _build_error
    if _build_done:
        if _build_error:
            pytest.fail(_build_error)
        return

    os.makedirs(BENCHMARK_DIR, exist_ok=True)

    r = subprocess.run(
        ["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."],
        cwd=BENCHMARK_DIR, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        _build_error = f"CMake configuration failed:\n{r.stderr}"
        _build_done = True
        pytest.fail(_build_error)

    r = subprocess.run(
        ["make", "-j2"],
        cwd=BENCHMARK_DIR, capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        _build_error = f"Build failed:\n{r.stderr}"
        _build_done = True
        pytest.fail(_build_error)

    _build_done = True


def _run_benchmark(name):
    """Run a DGEMM benchmark variant and return (mflops_list, returncode, stdout, stderr)."""
    cmd = [f"{BENCHMARK_DIR}/benchmark-{name}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=BENCHMARK_TIMEOUT)

    mflops_list = []
    for line in r.stdout.split("\n"):
        m = re.search(r"Mflops/s:\s+([\d.]+)", line)
        if m:
            mflops_list.append(float(m.group(1)))

    return mflops_list, r.returncode, r.stdout, r.stderr


def _file_sha256(path):
    """Compute sha256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_source_integrity():
    """Verify that benchmark harness files have not been tampered with."""
    protected_files = ["dgemm-naive.c", "dgemm-blas.c", "benchmark.cpp", "CMakeLists.txt"]
    for fname in protected_files:
        orig_path = f"/app/originals/{fname}"
        curr_path = f"/app/{fname}"
        assert os.path.isfile(orig_path), f"Original reference {orig_path} missing"
        assert os.path.isfile(curr_path), f"Source file {curr_path} missing"
        expected = _file_sha256(orig_path)
        actual = _file_sha256(curr_path)
        assert actual == expected, (
            f"{fname} has been modified from its original version. "
            f"Only dgemm-blocked.c should be modified."
        )


def test_no_blas_in_source():
    """The implementation must not call BLAS or external math libraries."""
    with open("/app/dgemm-blocked.c") as f:
        code = f.read()

    # Strip C block comments, line comments, and string literals
    stripped = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    stripped = re.sub(r"//.*", "", stripped)
    stripped = re.sub(r'"[^"]*"', '""', stripped)

    assert "cblas_" not in stripped, \
        "Implementation must not call BLAS functions (cblas_*)"
    assert "#include <cblas.h>" not in stripped, \
        "Implementation must not include BLAS headers"
    assert "#include <lapacke.h>" not in stripped, \
        "Implementation must not include LAPACK headers"
    assert "dlopen" not in stripped, \
        "Implementation must not dynamically load libraries"
    assert "dlsym" not in stripped, \
        "Implementation must not dynamically load symbols"
    assert "system(" not in stripped, \
        "Implementation must not use system() calls"
    assert "popen(" not in stripped, \
        "Implementation must not use popen() calls"


def test_builds_successfully():
    """The project must build without errors."""
    _ensure_built()
    assert os.path.isfile(f"{BENCHMARK_DIR}/benchmark-blocked"), \
        "benchmark-blocked executable not found after build"
    assert os.path.isfile(f"{BENCHMARK_DIR}/benchmark-naive"), \
        "benchmark-naive executable not found after build"


def test_numerical_correctness():
    """Optimized DGEMM must produce numerically correct results for all test sizes."""
    _ensure_built()
    _, returncode, stdout, stderr = _run_benchmark("blocked")
    assert "FAILURE" not in stderr, \
        f"Correctness verification failed:\n{stderr}"
    assert returncode == 0, \
        f"Benchmark exited with error code {returncode}:\n{stderr}"


def test_performance_threshold():
    """Optimized DGEMM must achieve >= 4x average speedup over the naive implementation."""
    _ensure_built()

    blocked_mflops, rc_b, _, stderr_b = _run_benchmark("blocked")
    assert rc_b == 0, f"Blocked benchmark failed:\n{stderr_b}"
    assert len(blocked_mflops) >= 5, \
        f"Expected results for at least 5 matrix sizes, got {len(blocked_mflops)}"

    naive_mflops, rc_n, _, stderr_n = _run_benchmark("naive")
    assert rc_n == 0, f"Naive benchmark failed:\n{stderr_n}"
    assert len(naive_mflops) >= 5, \
        f"Expected naive results for at least 5 sizes, got {len(naive_mflops)}"

    avg_blocked = sum(blocked_mflops) / len(blocked_mflops)
    avg_naive = sum(naive_mflops) / len(naive_mflops)
    ratio = avg_blocked / avg_naive

    assert ratio >= 4.0, (
        f"Performance speedup {ratio:.2f}x is below the 4x threshold.\n"
        f"  Average blocked: {avg_blocked:,.0f} Mflops/s\n"
        f"  Average naive:   {avg_naive:,.0f} Mflops/s\n"
        f"  Speedup:         {ratio:.2f}x"
    )


def test_large_matrix_performance():
    """For large matrices (>= 256), the optimized code must show clear speedup."""
    _ensure_built()

    # Run benchmarks on a few large sizes only
    large_sizes = ["256", "512", "768"]
    for sz in large_sizes:
        blocked_cmd = [f"{BENCHMARK_DIR}/benchmark-blocked", sz]
        naive_cmd = [f"{BENCHMARK_DIR}/benchmark-naive", sz]

        rb = subprocess.run(blocked_cmd, capture_output=True, text=True, timeout=120)
        rn = subprocess.run(naive_cmd, capture_output=True, text=True, timeout=120)

        assert rb.returncode == 0, f"Blocked benchmark failed for size {sz}"
        assert rn.returncode == 0, f"Naive benchmark failed for size {sz}"

        mb = re.search(r"Mflops/s:\s+([\d.]+)", rb.stdout)
        mn = re.search(r"Mflops/s:\s+([\d.]+)", rn.stdout)

        assert mb and mn, f"Could not parse Mflops for size {sz}"

        blocked_mf = float(mb.group(1))
        naive_mf = float(mn.group(1))

        speedup = blocked_mf / naive_mf
        assert speedup >= 3.0, (
            f"For N={sz}, speedup is only {speedup:.2f}x (need >= 3x).\n"
            f"  Blocked: {blocked_mf:,.0f} Mflops/s, Naive: {naive_mf:,.0f} Mflops/s"
        )
