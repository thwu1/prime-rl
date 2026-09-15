"""
Tests for fixing OpenMP data race bugs in five computational kernels.

Verifies: compilation, correctness vs sequential reference, deterministic
output under concurrent execution, and preservation of OpenMP parallelism.

"""
import subprocess
import os
import pytest

KERNELS = ["histogram", "jacobi2d", "nbody", "lu_factor", "wavefront"]


def _compile(source, output, flags, compiler="gcc"):
    cmd = [compiler] + flags + [source, "-o", output, "-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, r.stderr


def _run(binary, env_extra=None, timeout=120):
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "4"
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [binary], capture_output=True, text=True, timeout=timeout, env=env
    )
    return r.returncode, r.stdout, r.stderr


def _ref_output(kernel):
    src = f"/tests/reference/{kernel}_seq.c"
    binary = f"/tmp/{kernel}_seq"
    ok, err = _compile(src, binary, ["-O2"])
    assert ok, f"Reference {kernel}_seq.c failed to compile: {err}"
    rc, out, err = _run(binary, timeout=60)
    assert rc == 0, f"Reference {kernel}_seq failed: {err}"
    return out.strip()


def _par_output(kernel):
    src = f"/app/src/{kernel}.c"
    binary = f"/tmp/{kernel}_par"
    ok, err = _compile(src, binary, ["-O2", "-fopenmp"])
    assert ok, f"{kernel}.c failed to compile with -fopenmp: {err}"
    rc, out, err = _run(binary)
    assert rc == 0, f"{kernel} failed to run: {err}"
    return out.strip()


# ---------- Compilation tests ----------

@pytest.mark.parametrize("kernel", KERNELS)
def test_compiles(kernel):
    src = f"/app/src/{kernel}.c"
    binary = f"/tmp/{kernel}_compile_check"
    ok, err = _compile(src, binary, ["-O2", "-fopenmp"])
    assert ok, f"{kernel}.c failed to compile: {err}"


# ---------- Correctness tests ----------

def test_histogram_correct():
    ref = _ref_output("histogram")
    par = _par_output("histogram")
    assert ref == par, f"Histogram mismatch.\nExpected:\n{ref}\nGot:\n{par}"


def test_jacobi2d_correct():
    ref_val = float(_ref_output("jacobi2d"))
    par_val = float(_par_output("jacobi2d"))
    assert abs(ref_val - par_val) < 1e-6, (
        f"Jacobi2D mismatch: expected {ref_val}, got {par_val}"
    )


def test_nbody_correct():
    ref_val = float(_ref_output("nbody"))
    par_val = float(_par_output("nbody"))
    denom = max(abs(ref_val), 1e-15)
    rel_err = abs(ref_val - par_val) / denom
    assert rel_err < 1e-6, (
        f"Nbody mismatch: expected {ref_val}, got {par_val}, rel_err={rel_err}"
    )


def test_lu_factor_correct():
    ref_lines = _ref_output("lu_factor").split("\n")
    par_lines = _par_output("lu_factor").split("\n")
    assert len(ref_lines) == len(par_lines) == 2, "Expected 2 output lines"
    for i in range(2):
        ref_v = float(ref_lines[i])
        par_v = float(par_lines[i])
        denom = max(abs(ref_v), 1e-15)
        rel_err = abs(ref_v - par_v) / denom
        assert rel_err < 1e-6, (
            f"LU line {i} mismatch: expected {ref_v}, got {par_v}"
        )


def test_wavefront_correct():
    ref = _ref_output("wavefront")
    par = _par_output("wavefront")
    assert ref == par, f"Wavefront mismatch.\nExpected:\n{ref}\nGot:\n{par}"


# ---------- Determinism tests ----------
# Race-free parallel code produces identical output across multiple runs
# with the same input and thread configuration.  Racy code exhibits
# non-deterministic output due to unsynchronized concurrent memory access.

@pytest.mark.parametrize("kernel", KERNELS)
def test_deterministic(kernel):
    src = f"/app/src/{kernel}.c"
    binary = f"/tmp/{kernel}_det"
    ok, err = _compile(src, binary, ["-O2", "-fopenmp"])
    assert ok, f"{kernel}.c failed to compile: {err}"

    outputs = []
    for run in range(10):
        rc, out, stderr = _run(binary)
        assert rc == 0, f"{kernel} crashed on run {run}: {stderr}"
        outputs.append(out.strip())

    first = outputs[0]
    for i, out in enumerate(outputs[1:], 1):
        assert out == first, (
            f"{kernel} produced non-deterministic output (data race suspected).\n"
            f"Run 0:\n{first}\nRun {i}:\n{out}"
        )


# ---------- OpenMP preservation tests ----------

@pytest.mark.parametrize("kernel", KERNELS)
def test_omp_preserved(kernel):
    src = f"/app/src/{kernel}.c"
    with open(src) as f:
        content = f.read()
    assert "#pragma omp" in content, (
        f"{kernel}.c must still contain #pragma omp directives"
    )
    assert "omp.h" in content, f"{kernel}.c must still include omp.h"
