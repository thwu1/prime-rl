"""Tests for OpenMP parallel kernel fixes.

Verifies correctness (against sequential references), determinism (across
multiple runs and thread counts to surface concurrency defects), compilation,
and continued use of OpenMP directives.
"""

import subprocess
import os
import math
import pytest


def compile_c(src, output, flags, compiler="gcc"):
    """Compile a C source file. Puts -l flags after source for correct linking."""
    cflags = [f for f in flags if not f.startswith('-l')]
    ldflags = [f for f in flags if f.startswith('-l')]
    cmd = [compiler] + cflags + ["-o", output, src] + ldflags
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Compilation failed for {src} ({compiler}):\n{result.stderr}"


def run_exe(exe, env_extra=None, timeout=120):
    """Run an executable, return (stdout, stderr, returncode)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run([exe], capture_output=True, text=True, timeout=timeout, env=env)
    return result.stdout, result.stderr, result.returncode


def parse_output(stdout):
    """Parse key=value output lines into a dict of floats."""
    vals = {}
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if '=' in line:
            key, val = line.split('=', 1)
            try:
                vals[key.strip()] = float(val.strip())
            except ValueError:
                vals[key.strip()] = val.strip()
    return vals


def assert_values_close(ref, actual, rel_tol=1e-5, abs_tol=1e-3):
    """Assert all reference values match actual values within tolerance."""
    for key in ref:
        assert key in actual, f"Missing output key: {key}"
        r, a = ref[key], actual[key]
        if isinstance(r, (int, float)) and isinstance(a, (int, float)):
            assert math.isclose(r, a, rel_tol=rel_tol, abs_tol=abs_tol), \
                f"Value mismatch for {key}: expected {r}, got {a}"
        else:
            assert str(r) == str(a), f"Value mismatch for {key}: expected {r}, got {a}"


def collect_runs(exe, thread_counts, runs_per_count=2):
    """Run executable multiple times with different thread counts, return outputs."""
    outputs = []
    for tc in thread_counts:
        for _ in range(runs_per_count):
            out, _, rc = run_exe(exe, {"OMP_NUM_THREADS": str(tc)})
            assert rc == 0, f"Execution failed with OMP_NUM_THREADS={tc}"
            outputs.append(out.strip())
    return outputs


class TestHistogram:
    @classmethod
    def setup_class(cls):
        compile_c("/tests/ref_histogram.c", "/tmp/ref_histogram", ["-O2", "-lm"])

    def test_compiles(self):
        """histogram.c compiles with gcc -fopenmp -O2"""
        compile_c("/app/src/histogram.c", "/tmp/par_histogram",
                  ["-fopenmp", "-O2", "-lm"])

    def test_correctness(self):
        """Parallel histogram output matches sequential reference"""
        compile_c("/app/src/histogram.c", "/tmp/par_histogram",
                  ["-fopenmp", "-O2", "-lm"])
        ref_out, _, rc = run_exe("/tmp/ref_histogram")
        assert rc == 0, "Reference histogram failed to run"
        par_out, _, rc = run_exe("/tmp/par_histogram", {"OMP_NUM_THREADS": "4"})
        assert rc == 0, "Parallel histogram failed to run"
        ref_vals = parse_output(ref_out)
        par_vals = parse_output(par_out)
        assert_values_close(ref_vals, par_vals, rel_tol=0, abs_tol=0)
        assert par_vals["total"] == 500000, \
            f"Total should be 500000, got {par_vals['total']}"

    def test_deterministic(self):
        """Parallel histogram yields identical output across runs and thread counts"""
        compile_c("/app/src/histogram.c", "/tmp/par_histogram",
                  ["-fopenmp", "-O2", "-lm"])
        outputs = collect_runs("/tmp/par_histogram", [2, 4, 3], runs_per_count=2)
        unique = set(outputs)
        assert len(unique) == 1, \
            f"Non-deterministic output across {len(outputs)} runs (data race suspected):\n" + \
            "\n---\n".join(list(unique)[:3])

    def test_has_openmp(self):
        """histogram.c still uses OpenMP directives"""
        with open("/app/src/histogram.c") as f:
            code = f.read()
        assert "#pragma omp" in code, "OpenMP directives were removed"


class TestJacobi:
    @classmethod
    def setup_class(cls):
        compile_c("/tests/ref_jacobi.c", "/tmp/ref_jacobi", ["-O2", "-lm"])

    def test_compiles(self):
        """jacobi.c compiles with gcc -fopenmp -O2"""
        compile_c("/app/src/jacobi.c", "/tmp/par_jacobi",
                  ["-fopenmp", "-O2", "-lm"])

    def test_correctness(self):
        """Parallel Jacobi output matches sequential double-buffered reference"""
        compile_c("/app/src/jacobi.c", "/tmp/par_jacobi",
                  ["-fopenmp", "-O2", "-lm"])
        ref_out, _, rc = run_exe("/tmp/ref_jacobi")
        assert rc == 0, "Reference Jacobi failed to run"
        par_out, _, rc = run_exe("/tmp/par_jacobi", {"OMP_NUM_THREADS": "4"})
        assert rc == 0, "Parallel Jacobi failed to run"
        ref_vals = parse_output(ref_out)
        par_vals = parse_output(par_out)
        assert_values_close(ref_vals, par_vals, rel_tol=1e-4, abs_tol=1e-2)

    def test_deterministic(self):
        """Parallel Jacobi yields identical output across runs and thread counts"""
        compile_c("/app/src/jacobi.c", "/tmp/par_jacobi",
                  ["-fopenmp", "-O2", "-lm"])
        outputs = collect_runs("/tmp/par_jacobi", [2, 4, 3], runs_per_count=2)
        unique = set(outputs)
        assert len(unique) == 1, \
            f"Non-deterministic output across {len(outputs)} runs (data race suspected):\n" + \
            "\n---\n".join(list(unique)[:3])

    def test_has_openmp(self):
        """jacobi.c still uses OpenMP directives"""
        with open("/app/src/jacobi.c") as f:
            code = f.read()
        assert "#pragma omp" in code, "OpenMP directives were removed"


class TestNbody:
    @classmethod
    def setup_class(cls):
        compile_c("/tests/ref_nbody.c", "/tmp/ref_nbody", ["-O2", "-lm"])

    def test_compiles(self):
        """nbody.c compiles with gcc -fopenmp -O2"""
        compile_c("/app/src/nbody.c", "/tmp/par_nbody",
                  ["-fopenmp", "-O2", "-lm"])

    def test_correctness(self):
        """Parallel N-body output matches sequential reference"""
        compile_c("/app/src/nbody.c", "/tmp/par_nbody",
                  ["-fopenmp", "-O2", "-lm"])
        ref_out, _, rc = run_exe("/tmp/ref_nbody")
        assert rc == 0, "Reference N-body failed to run"
        par_out, _, rc = run_exe("/tmp/par_nbody", {"OMP_NUM_THREADS": "4"})
        assert rc == 0, "Parallel N-body failed to run"
        ref_vals = parse_output(ref_out)
        par_vals = parse_output(par_out)
        assert_values_close(ref_vals, par_vals, rel_tol=1e-6, abs_tol=1e-4)

    def test_deterministic(self):
        """Parallel N-body yields identical output across runs and thread counts"""
        compile_c("/app/src/nbody.c", "/tmp/par_nbody",
                  ["-fopenmp", "-O2", "-lm"])
        outputs = collect_runs("/tmp/par_nbody", [2, 4, 3], runs_per_count=2)
        unique = set(outputs)
        assert len(unique) == 1, \
            f"Non-deterministic output across {len(outputs)} runs (data race suspected):\n" + \
            "\n---\n".join(list(unique)[:3])

    def test_has_openmp(self):
        """nbody.c still uses OpenMP directives"""
        with open("/app/src/nbody.c") as f:
            code = f.read()
        assert "#pragma omp" in code, "OpenMP directives were removed"


class TestConvolve:
    @classmethod
    def setup_class(cls):
        compile_c("/tests/ref_convolve.c", "/tmp/ref_convolve", ["-O2", "-lm"])

    def test_compiles(self):
        """convolve.c compiles with gcc -fopenmp -O2"""
        compile_c("/app/src/convolve.c", "/tmp/par_convolve",
                  ["-fopenmp", "-O2", "-lm"])

    def test_correctness(self):
        """Parallel convolution output matches sequential reference"""
        compile_c("/app/src/convolve.c", "/tmp/par_convolve",
                  ["-fopenmp", "-O2", "-lm"])
        ref_out, _, rc = run_exe("/tmp/ref_convolve")
        assert rc == 0, "Reference convolve failed to run"
        par_out, _, rc = run_exe("/tmp/par_convolve", {"OMP_NUM_THREADS": "4"})
        assert rc == 0, "Parallel convolve failed to run"
        ref_vals = parse_output(ref_out)
        par_vals = parse_output(par_out)
        assert_values_close(ref_vals, par_vals, rel_tol=1e-8, abs_tol=1e-6)

    def test_deterministic(self):
        """Parallel convolution yields identical output across runs and thread counts"""
        compile_c("/app/src/convolve.c", "/tmp/par_convolve",
                  ["-fopenmp", "-O2", "-lm"])
        outputs = collect_runs("/tmp/par_convolve", [2, 4, 3], runs_per_count=2)
        unique = set(outputs)
        assert len(unique) == 1, \
            f"Non-deterministic output across {len(outputs)} runs (data race suspected):\n" + \
            "\n---\n".join(list(unique)[:3])

    def test_has_openmp(self):
        """convolve.c still uses OpenMP directives"""
        with open("/app/src/convolve.c") as f:
            code = f.read()
        assert "#pragma omp" in code, "OpenMP directives were removed"


class TestPrefixScan:
    @classmethod
    def setup_class(cls):
        compile_c("/tests/ref_prefix_scan.c", "/tmp/ref_prefix_scan", ["-O2", "-lm"])

    def test_compiles(self):
        """prefix_scan.c compiles with gcc -fopenmp -O2"""
        compile_c("/app/src/prefix_scan.c", "/tmp/par_prefix_scan",
                  ["-fopenmp", "-O2", "-lm"])

    def test_correctness(self):
        """Parallel prefix scan output matches sequential reference"""
        compile_c("/app/src/prefix_scan.c", "/tmp/par_prefix_scan",
                  ["-fopenmp", "-O2", "-lm"])
        ref_out, _, rc = run_exe("/tmp/ref_prefix_scan")
        assert rc == 0, "Reference prefix_scan failed to run"
        par_out, _, rc = run_exe("/tmp/par_prefix_scan", {"OMP_NUM_THREADS": "4"})
        assert rc == 0, "Parallel prefix_scan failed to run"
        ref_vals = parse_output(ref_out)
        par_vals = parse_output(par_out)
        assert_values_close(ref_vals, par_vals, rel_tol=1e-8, abs_tol=1e-6)

    def test_deterministic(self):
        """Parallel prefix scan yields identical output for the same thread count"""
        compile_c("/app/src/prefix_scan.c", "/tmp/par_prefix_scan",
                  ["-fopenmp", "-O2", "-lm"])
        # Check determinism within same thread count; cross-thread-count fp
        # ordering differences are expected for correct multi-phase scan
        # implementations and are validated by the correctness test instead.
        for tc in [2, 4]:
            outputs = collect_runs("/tmp/par_prefix_scan", [tc], runs_per_count=3)
            unique = set(outputs)
            assert len(unique) == 1, \
                f"Non-deterministic output with OMP_NUM_THREADS={tc} " \
                f"(data race suspected):\n" + "\n---\n".join(list(unique)[:3])

    def test_has_openmp(self):
        """prefix_scan.c still uses OpenMP directives"""
        with open("/app/src/prefix_scan.c") as f:
            code = f.read()
        assert "#pragma omp" in code, "OpenMP directives were removed"
