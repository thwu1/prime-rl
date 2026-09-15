
import os
import subprocess
import tempfile

import numpy as np
import pytest

COMPILE_FLAGS = [
    "g++", "-O3", "-march=native", "-std=c++17", "-I/app"
]
BENCH_TIMEOUT = 180  # seconds per benchmark run


def _build(source_path: str, output_path: str):
    """Compile benchmark with a given correlate source file."""
    cmd = COMPILE_FLAGS + ["-o", output_path, "/app/benchmark.cpp", source_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"Compilation failed for {source_path}:\n{result.stderr}"
    )


def _run(binary: str, n: int, d: int, outfile: str) -> float:
    """Run the benchmark binary, return elapsed time in seconds."""
    cmd = [binary, str(n), str(d), outfile]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=BENCH_TIMEOUT
    )
    assert result.returncode == 0, (
        f"Benchmark failed ({binary} n={n} d={d}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("TIME:"):
            return float(line.split(":")[1])
    raise AssertionError(
        f"No TIME: line in benchmark output:\n{result.stdout}"
    )


def _load_matrix(path: str, n: int) -> np.ndarray:
    """Load a raw float32 binary file into an n x n numpy array."""
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), dtype=np.float32)
    assert data.size == n * n, (
        f"Expected {n*n} floats, got {data.size}"
    )
    return data.reshape(n, n)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def build_dir():
    """Create a temporary directory for compiled binaries and outputs."""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture(scope="module")
def binaries(build_dir):
    """Compile both optimized and naive versions once for all tests."""
    opt_bin = os.path.join(build_dir, "bench_opt")
    naive_bin = os.path.join(build_dir, "bench_naive")
    _build("/app/correlate.cpp", opt_bin)
    _build("/tests/correlate_naive.cpp", naive_bin)
    return opt_bin, naive_bin


# ---------------------------------------------------------------------------
# Correctness tests
# ---------------------------------------------------------------------------

class TestCorrectness:
    """Verify optimised output matches the naive reference."""

    def test_builds(self, binaries):
        """Optimized version compiles without errors."""
        opt_bin, _ = binaries
        assert os.path.isfile(opt_bin)

    def test_matches_naive(self, binaries, build_dir):
        """All entries match within tolerance for n=200, d=100."""
        opt_bin, naive_bin = binaries
        n, d = 200, 100
        opt_out = os.path.join(build_dir, "opt_small.bin")
        naive_out = os.path.join(build_dir, "naive_small.bin")

        _run(opt_bin, n, d, opt_out)
        _run(naive_bin, n, d, naive_out)

        opt_mat = _load_matrix(opt_out, n)
        naive_mat = _load_matrix(naive_out, n)

        max_diff = float(np.max(np.abs(opt_mat - naive_mat)))
        assert max_diff < 1e-3, (
            f"Max absolute difference {max_diff:.6f} exceeds tolerance 1e-3"
        )

    def test_diagonal_is_one(self, binaries, build_dir):
        """Diagonal entries (self-correlation) must be ~1.0."""
        opt_bin, _ = binaries
        n, d = 80, 40
        out = os.path.join(build_dir, "diag.bin")
        _run(opt_bin, n, d, out)
        mat = _load_matrix(out, n)
        diag = np.diag(mat)
        assert np.allclose(diag, 1.0, atol=1e-3), (
            f"Diagonal not all 1.0. First 5 values: {diag[:5]}"
        )

    def test_symmetric(self, binaries, build_dir):
        """Output matrix must be symmetric."""
        opt_bin, _ = binaries
        n, d = 150, 80
        out = os.path.join(build_dir, "sym.bin")
        _run(opt_bin, n, d, out)
        mat = _load_matrix(out, n)
        max_asym = float(np.max(np.abs(mat - mat.T)))
        assert max_asym < 1e-6, (
            f"Matrix not symmetric; max |M-M^T| = {max_asym:.8f}"
        )

    def test_values_in_range(self, binaries, build_dir):
        """All correlation values must be in [-1, 1]."""
        opt_bin, _ = binaries
        n, d = 200, 100
        out = os.path.join(build_dir, "range.bin")
        _run(opt_bin, n, d, out)
        mat = _load_matrix(out, n)
        assert np.all(mat >= -1.0 - 1e-3) and np.all(mat <= 1.0 + 1e-3), (
            f"Values out of range: min={mat.min():.6f}, max={mat.max():.6f}"
        )


# ---------------------------------------------------------------------------
# Performance test
# ---------------------------------------------------------------------------

class TestPerformance:
    """Verify the optimized version meets the speedup target."""

    def test_speedup_10x(self, binaries, build_dir):
        """Optimized must be >= 10x faster than naive for n=1500, d=500."""
        opt_bin, naive_bin = binaries
        n, d = 1500, 500

        naive_out = os.path.join(build_dir, "naive_perf.bin")
        opt_out = os.path.join(build_dir, "opt_perf.bin")

        naive_time = _run(naive_bin, n, d, naive_out)
        opt_time = _run(opt_bin, n, d, opt_out)

        # Also verify correctness at this scale
        naive_mat = _load_matrix(naive_out, n)
        opt_mat = _load_matrix(opt_out, n)
        max_diff = float(np.max(np.abs(opt_mat - naive_mat)))
        assert max_diff < 1e-3, (
            f"Results differ at n={n}: max diff {max_diff:.6f}"
        )

        speedup = naive_time / max(opt_time, 1e-9)
        assert speedup >= 10.0, (
            f"Speedup {speedup:.1f}x < 10x required. "
            f"Naive: {naive_time:.3f}s, Optimized: {opt_time:.3f}s"
        )
