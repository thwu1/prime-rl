"""
Tests for PtrHash MPHF construction and query.

Verifies the core invariant: for n distinct input keys, the MPHF
produces a bijection to {0, 1, ..., n-1}.

"""

import os
import subprocess

import pytest

BINARY = "/app/ptrhash_test"


@pytest.fixture(scope="session", autouse=True)
def compile_binary():
    """Compile the implementation once for all tests."""
    src = "/app/ptrhash.c"
    if not os.path.isfile(src):
        pytest.fail(f"Implementation file {src} not found")
    result = subprocess.run(
        [
            "gcc", "-O2", "-std=c11", "-Wall", "-Wextra",
            "-o", BINARY, src, "/tests/test_main.c", "-I/app", "-lm",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Compilation failed:\n{result.stderr}")


def run_verify(n, seed=42, timeout=120):
    """Run the test binary in verify mode."""
    result = subprocess.run(
        [BINARY, "verify", str(n), str(seed)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def run_query(n, seed=42, timeout=120):
    """Run the test binary in query mode."""
    result = subprocess.run(
        [BINARY, "query", str(n), str(seed)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


# ---------------------------------------------------------------------------
# Bijectivity tests — core MPHF invariant
# ---------------------------------------------------------------------------


class TestBijectivitySmall:
    """Bijectivity on small inputs that stress edge cases."""

    def test_n1(self):
        r = run_verify(1)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n2(self):
        r = run_verify(2)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n3(self):
        r = run_verify(3)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n5(self):
        r = run_verify(5)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n10(self):
        r = run_verify(10)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n20(self):
        r = run_verify(20)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n44(self):
        r = run_verify(44)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n50(self):
        r = run_verify(50)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout


class TestBijectivityMedium:
    """Bijectivity on medium inputs."""

    def test_n100(self):
        r = run_verify(100)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n500(self):
        r = run_verify(500)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n1000(self):
        r = run_verify(1000)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n2500(self):
        r = run_verify(2500)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n5000(self):
        r = run_verify(5000)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n10000(self):
        r = run_verify(10000)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout


class TestBijectivityLarge:
    """Large inputs requiring robust construction."""

    def test_n25000(self):
        r = run_verify(25000, timeout=120)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n50000(self):
        r = run_verify(50000, timeout=120)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n100000(self):
        r = run_verify(100000, timeout=120)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout


class TestMultipleSeeds:
    """Construction must succeed across diverse key distributions."""

    @pytest.mark.parametrize(
        "seed", [1, 7, 42, 100, 999, 12345, 314159, 2718281]
    )
    def test_n1000_various_seeds(self, seed):
        r = run_verify(1000, seed=seed)
        assert r.returncode == 0, f"seed={seed} stderr: {r.stderr}"
        assert "PASS" in r.stdout

    @pytest.mark.parametrize("seed", [1, 42, 9999, 65537])
    def test_n10000_various_seeds(self, seed):
        r = run_verify(10000, seed=seed)
        assert r.returncode == 0, f"seed={seed} stderr: {r.stderr}"
        assert "PASS" in r.stdout

    @pytest.mark.parametrize("seed", [13, 8191, 131071])
    def test_n50000_various_seeds(self, seed):
        r = run_verify(50000, seed=seed, timeout=120)
        assert r.returncode == 0, f"seed={seed} stderr: {r.stderr}"
        assert "PASS" in r.stdout


# ---------------------------------------------------------------------------
# Query-level property tests
# ---------------------------------------------------------------------------


class TestQueryProperties:
    """Verify specific properties of query output."""

    def test_query_values_in_range(self):
        """All returned indices lie in [0, n)."""
        n = 500
        r = run_query(n)
        assert r.returncode == 0
        indices = [int(line) for line in r.stdout.strip().split("\n")]
        assert len(indices) == n
        for idx in indices:
            assert 0 <= idx < n, f"Index {idx} out of range [0, {n})"

    def test_query_all_unique(self):
        """All returned indices are distinct."""
        n = 500
        r = run_query(n)
        assert r.returncode == 0
        indices = [int(line) for line in r.stdout.strip().split("\n")]
        assert len(set(indices)) == n, "Query results contain duplicates"

    def test_query_forms_permutation(self):
        """Returned indices form an exact permutation of {0, ..., n-1}."""
        n = 2000
        r = run_query(n)
        assert r.returncode == 0
        indices = [int(line) for line in r.stdout.strip().split("\n")]
        assert sorted(indices) == list(range(n))

    def test_query_deterministic(self):
        """Same keys always produce the same query results."""
        n = 500
        r1 = run_query(n)
        r2 = run_query(n)
        assert r1.stdout == r2.stdout, "Query results are not deterministic"

    def test_large_permutation(self):
        """Permutation test on 20000 keys."""
        n = 20000
        r = run_query(n)
        assert r.returncode == 0
        indices = [int(line) for line in r.stdout.strip().split("\n")]
        assert sorted(indices) == list(range(n))


# ---------------------------------------------------------------------------
# Edge cases and boundary conditions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and special sizes."""

    def test_n0(self):
        """Empty input: construction should succeed, no queries needed."""
        r = run_verify(0)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_prime_997(self):
        r = run_verify(997)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_power_of_two_1024(self):
        r = run_verify(1024)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_power_of_two_minus_one_1023(self):
        r = run_verify(1023)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n4(self):
        """Very small input set."""
        r = run_verify(4)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n7(self):
        r = run_verify(7)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_large_prime_10007(self):
        r = run_verify(10007)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n256(self):
        r = run_verify(256)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout

    def test_n257(self):
        r = run_verify(257)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "PASS" in r.stdout
