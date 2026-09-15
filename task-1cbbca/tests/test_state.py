
import os
import subprocess
import tempfile

import pytest


@pytest.fixture(scope="session")
def build_project():
    """Configure and build the C++ project."""
    os.chdir("/app")
    subprocess.run(["rm", "-rf", "build"], check=False)

    r = subprocess.run(
        ["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, f"CMake configure failed:\n{r.stderr}"

    r = subprocess.run(
        ["cmake", "--build", "build", "--", "-j2"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, f"Build failed:\n{r.stderr}"


@pytest.fixture(scope="session")
def test_output(build_project):
    """Run the C++ test binary and capture output."""
    binary = "/app/build/test_bipartite"
    if not os.path.isfile(binary):
        pytest.fail(
            f"Test binary not found at {binary}. "
            f"Build dir contents: {os.listdir('/app/build') if os.path.isdir('/app/build') else 'NO BUILD DIR'}"
        )
    r = subprocess.run(
        [binary],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r


# -- Build / run gate -------------------------------------------------------

def test_builds_successfully(build_project):
    """The project builds without errors."""
    pass  # build_project fixture asserts on failure


def test_exit_code(test_output):
    """The test binary exits with code 0."""
    assert test_output.returncode == 0, (
        f"test_bipartite exited {test_output.returncode}:\n{test_output.stdout}"
    )


def test_all_pass_banner(test_output):
    """Output must contain the ALL TESTS PASSED banner."""
    assert "ALL TESTS PASSED" in test_output.stdout, (
        f"Missing pass banner:\n{test_output.stdout}"
    )


# -- Per-category checks ----------------------------------------------------

def test_no_capacity_failures(test_output):
    """Capacity-sentinel enforcement tests pass."""
    assert "FAIL: capacity_" not in test_output.stdout, (
        f"Capacity test failure:\n{test_output.stdout}"
    )


def test_no_wrap_failures(test_output):
    """Wrap-around write tests pass."""
    assert "FAIL: wrap_" not in test_output.stdout, (
        f"Wrap test failure:\n{test_output.stdout}"
    )


def test_no_invalidation_failures(test_output):
    """Invalidation-boundary traversal tests pass."""
    assert "FAIL: inv_" not in test_output.stdout, (
        f"Invalidation test failure:\n{test_output.stdout}"
    )


def test_no_stress_failures(test_output):
    """Single-threaded stress test passes."""
    assert "FAIL: stress_" not in test_output.stdout, (
        f"Stress test failure:\n{test_output.stdout}"
    )


def test_no_concurrent_failures(test_output):
    """Multi-threaded concurrent test passes."""
    assert "FAIL: concurrent_" not in test_output.stdout, (
        f"Concurrent test failure:\n{test_output.stdout}"
    )


# -- Independent verification (anti-cheat) -----------------------------------

def test_direct_buffer_verification(build_project):
    """Compile and run a small independent test against bipartite_buf.hpp."""
    test_src = r'''
#include "bipartite_buf.hpp"
#include <cstdio>

int main() {
    // Sentinel: Cannot overfill from empty
    {
        BipartiteBuf<int, 8> b;
        if (b.WriteAcquire(8) != nullptr) {
            std::printf("FAIL:overfill\n"); return 1;
        }
        int* w = b.WriteAcquire(7);
        if (!w) { std::printf("FAIL:max\n"); return 1; }
        for (int i = 0; i < 7; i++) w[i] = i;
        b.WriteRelease(7);
        auto [rp, rn] = b.ReadAcquire();
        if (rn != 7) { std::printf("FAIL:maxrd\n"); return 1; }
        b.ReadRelease(7);
    }

    // Wrap write data integrity
    {
        BipartiteBuf<int, 16> b;
        int* w = b.WriteAcquire(12);
        for (int i = 0; i < 12; i++) w[i] = i;
        b.WriteRelease(12);
        auto r1 = b.ReadAcquire(); b.ReadRelease(12);
        w = b.WriteAcquire(10);
        if (!w) { std::printf("FAIL:wrapw\n"); return 1; }
        for (int i = 0; i < 10; i++) w[i] = 100 + i;
        b.WriteRelease(10);
        auto r2 = b.ReadAcquire();
        if (!r2.first || r2.second != 10) {
            std::printf("FAIL:wrapcnt %zu\n", r2.second); return 1;
        }
        if (r2.first[0] != 100) {
            std::printf("FAIL:wrapval %d\n", r2.first[0]); return 1;
        }
        b.ReadRelease(10);
    }

    // Invalidation boundary read
    {
        BipartiteBuf<int, 16> b;
        int* w = b.WriteAcquire(12);
        for (int i = 0; i < 12; i++) w[i] = i;
        b.WriteRelease(12);
        auto r1 = b.ReadAcquire(); b.ReadRelease(8);
        w = b.WriteAcquire(7);
        if (!w) { std::printf("FAIL:invw\n"); return 1; }
        for (int i = 0; i < 7; i++) w[i] = 200 + i;
        b.WriteRelease(7);
        auto r2 = b.ReadAcquire();
        if (!r2.first || r2.second != 4) {
            std::printf("FAIL:invpre %zu\n", r2.second); return 1;
        }
        b.ReadRelease(4);
        auto r3 = b.ReadAcquire();
        if (!r3.first || r3.second != 7) {
            std::printf("FAIL:invpost %zu\n", r3.second); return 1;
        }
        if (r3.first[0] != 200) {
            std::printf("FAIL:invval %d\n", r3.first[0]); return 1;
        }
        b.ReadRelease(7);
    }

    std::printf("PASS\n");
    return 0;
}
'''
    with tempfile.NamedTemporaryFile(
        suffix=".cpp", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(test_src)
        src_path = f.name

    r = subprocess.run(
        [
            "g++", "-std=c++17", "-O2", "-I/app/include",
            src_path, "-o", "/tmp/direct_test", "-pthread",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, f"Direct test compile failed:\n{r.stderr}"

    r = subprocess.run(
        ["/tmp/direct_test"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, f"Direct test failed:\n{r.stdout}"
    assert "PASS" in r.stdout, f"Direct test output:\n{r.stdout}"
