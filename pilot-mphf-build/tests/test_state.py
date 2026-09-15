
import ctypes
import os
import subprocess
import time

import pytest

TOOL = "/app/mphf_tool.py"
DATA = "/app/data"


def _run(args, timeout=300):
    """Run mphf_tool.py with the given arguments."""
    return subprocess.run(
        ["python3", TOOL] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_keys(path):
    with open(path) as fh:
        return [int(line) for line in fh if line.strip()]


def _check_bijective(stdout, n):
    """Parse query output and verify bijectivity over {0..n-1}."""
    lines = stdout.strip().split("\n")
    assert len(lines) == n, f"Expected {n} output lines, got {len(lines)}"
    values = [int(v) for v in lines]
    assert all(0 <= v < n for v in values), "Value(s) outside [0, n)"
    assert len(set(values)) == n, (
        f"Not bijective: {n} keys produced only {len(set(values))} distinct values"
    )


def _parse_info(stdout):
    """Parse the decomposed info output into a dict of floats."""
    result = {}
    for line in stdout.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = float(v.strip())
    return result


class TestMPHFLibrary:
    """Verify the C shared library and Python CLI tool."""

    # ------------------------------------------------------------------ #
    # Shared library symbol check                                         #
    # ------------------------------------------------------------------ #
    def test_shared_lib_symbols(self):
        """libmphf.so exists and exports every function in mphf.h."""
        lib = ctypes.CDLL("/app/libmphf.so")
        for sym in (
            "mphf_build",
            "mphf_query",
            "mphf_bits_per_key",
            "mphf_save",
            "mphf_load",
            "mphf_free",
            "mphf_key_count",
            "mphf_pilots_bytes",
            "mphf_remap_bytes",
            "mphf_remap_count",
        ):
            assert getattr(lib, sym, None) is not None, f"Missing symbol: {sym}"

    # ------------------------------------------------------------------ #
    # Bijectivity — random 1 000 keys                                     #
    # ------------------------------------------------------------------ #
    def test_bijectivity_random_1k(self):
        """Build + query on 1 000 random keys -> bijective mapping."""
        kf = f"{DATA}/random_1k.txt"
        mph = "/tmp/tb_1k.mph"
        n = len(_read_keys(kf))

        r = _run(["build", kf, mph])
        assert r.returncode == 0, f"build failed:\n{r.stderr}"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Bijectivity + time — random 200 000 keys                            #
    # ------------------------------------------------------------------ #
    def test_bijectivity_random_200k(self):
        """Build 200 000 random keys within 90 s, then verify bijectivity."""
        kf = f"{DATA}/random_200k.txt"
        mph = "/tmp/tb_200k.mph"
        n = len(_read_keys(kf))

        t0 = time.time()
        try:
            r = _run(["build", kf, mph], timeout=100)
        except subprocess.TimeoutExpired:
            pytest.fail("Construction exceeded 90-second limit")
        elapsed = time.time() - t0
        assert r.returncode == 0, f"build failed:\n{r.stderr}"
        assert elapsed < 90, f"Construction took {elapsed:.1f}s (limit 90 s)"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Bijectivity + time — random 1 000 000 keys                          #
    # ------------------------------------------------------------------ #
    def test_bijectivity_random_1m(self):
        """Build 1 000 000 random keys within 120 s, then verify bijectivity."""
        kf = f"{DATA}/random_1m.txt"
        mph = "/tmp/tb_1m.mph"
        n = len(_read_keys(kf))

        t0 = time.time()
        try:
            r = _run(["build", kf, mph], timeout=130)
        except subprocess.TimeoutExpired:
            pytest.fail("Construction exceeded 120-second limit")
        elapsed = time.time() - t0
        assert r.returncode == 0, f"build failed:\n{r.stderr}"
        assert elapsed < 120, f"Construction took {elapsed:.1f}s (limit 120 s)"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Bijectivity — sequential 10 000 keys                                #
    # ------------------------------------------------------------------ #
    def test_bijectivity_sequential(self):
        """Build + query on sequential integer keys (0 .. 9999)."""
        kf = f"{DATA}/sequential_10k.txt"
        mph = "/tmp/tb_seq.mph"
        n = len(_read_keys(kf))

        r = _run(["build", kf, mph])
        assert r.returncode == 0, f"build failed:\n{r.stderr}"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Bijectivity — adversarial keys (structured bit patterns)            #
    # ------------------------------------------------------------------ #
    def test_bijectivity_adversarial(self):
        """Build + query on adversarial keys with zero low-32-bit halves."""
        kf = f"{DATA}/adversarial_20k.txt"
        mph = "/tmp/tb_adv.mph"
        n = len(_read_keys(kf))

        r = _run(["build", kf, mph])
        assert r.returncode == 0, f"build failed:\n{r.stderr}"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Space efficiency — tight bound                                      #
    # ------------------------------------------------------------------ #
    def test_space_efficiency(self):
        """total_bits_per_key must be in [1.5, 4.0] on the 200k dataset."""
        kf = f"{DATA}/random_200k.txt"
        mph = "/tmp/tb_space.mph"

        r = _run(["build", kf, mph])
        assert r.returncode == 0, f"build failed:\n{r.stderr}"

        r = _run(["info", mph])
        assert r.returncode == 0, f"info failed:\n{r.stderr}"
        info = _parse_info(r.stdout)
        assert "total_bits_per_key" in info, (
            f"Expected 'total_bits_per_key=...' in output, got: {r.stdout!r}"
        )
        bpk = info["total_bits_per_key"]
        assert 1.5 <= bpk <= 4.0, f"total_bits_per_key={bpk:.4f}, want [1.5, 4.0]"

    # ------------------------------------------------------------------ #
    # Decomposed info output                                              #
    # ------------------------------------------------------------------ #
    def test_decomposed_info(self):
        """info command must produce decomposed space report with all four fields."""
        kf = f"{DATA}/random_200k.txt"
        mph = "/tmp/tb_decomp.mph"

        r = _run(["build", kf, mph])
        assert r.returncode == 0, f"build failed:\n{r.stderr}"

        r = _run(["info", mph])
        assert r.returncode == 0, f"info failed:\n{r.stderr}"
        info = _parse_info(r.stdout)

        for field in ("total_bits_per_key", "pilots_bits_per_key",
                       "remap_bits_per_key", "remap_fraction"):
            assert field in info, f"Missing field '{field}' in info output"

        # pilots + remap should approximately equal total (within 1 bpk for metadata)
        pilots_bpk = info["pilots_bits_per_key"]
        remap_bpk = info["remap_bits_per_key"]
        total_bpk = info["total_bits_per_key"]
        assert pilots_bpk > 0, f"pilots_bits_per_key must be positive, got {pilots_bpk}"
        assert remap_bpk >= 0, f"remap_bits_per_key must be non-negative, got {remap_bpk}"
        assert abs(total_bpk - (pilots_bpk + remap_bpk)) < 1.0, (
            f"Decomposition mismatch: total={total_bpk:.4f} vs "
            f"pilots+remap={pilots_bpk + remap_bpk:.4f}"
        )

        # remap_fraction should be in a sensible range for alpha=0.98
        rf = info["remap_fraction"]
        assert 0 < rf < 0.15, f"remap_fraction={rf:.6f}, expected (0, 0.15) for alpha=0.98"

    # ------------------------------------------------------------------ #
    # Alpha parameter affects remap fraction                              #
    # ------------------------------------------------------------------ #
    def test_alpha_remap_behavior(self):
        """Lower alpha must produce higher remap_fraction (more overflow)."""
        kf = f"{DATA}/random_1k.txt"
        n = len(_read_keys(kf))

        # Build with alpha=0.95 (lower load factor -> more overflow)
        mph_lo = "/tmp/tb_alpha_lo.mph"
        r = _run(["build", kf, mph_lo, "--alpha", "0.95"])
        assert r.returncode == 0, f"build alpha=0.95 failed:\n{r.stderr}"
        r = _run(["info", mph_lo])
        assert r.returncode == 0
        info_lo = _parse_info(r.stdout)

        # Build with alpha=0.99 (higher load factor -> less overflow)
        mph_hi = "/tmp/tb_alpha_hi.mph"
        r = _run(["build", kf, mph_hi, "--alpha", "0.99"])
        assert r.returncode == 0, f"build alpha=0.99 failed:\n{r.stderr}"
        r = _run(["info", mph_hi])
        assert r.returncode == 0
        info_hi = _parse_info(r.stdout)

        rf_lo = info_lo["remap_fraction"]
        rf_hi = info_hi["remap_fraction"]
        assert rf_lo > rf_hi, (
            f"remap_fraction(alpha=0.95)={rf_lo:.6f} should exceed "
            f"remap_fraction(alpha=0.99)={rf_hi:.6f}"
        )

        # Both must still be bijective
        r = _run(["query", mph_lo, kf])
        assert r.returncode == 0
        _check_bijective(r.stdout, n)

        r = _run(["query", mph_hi, kf])
        assert r.returncode == 0
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Determinism                                                          #
    # ------------------------------------------------------------------ #
    def test_query_determinism(self):
        """Two query runs on the same MPHF must produce identical output."""
        kf = f"{DATA}/random_1k.txt"
        mph = "/tmp/tb_det.mph"

        r = _run(["build", kf, mph])
        assert r.returncode == 0

        r1 = _run(["query", mph, kf])
        r2 = _run(["query", mph, kf])
        assert r1.returncode == 0 and r2.returncode == 0
        assert r1.stdout == r2.stdout, "Queries are not deterministic"

    # ------------------------------------------------------------------ #
    # Custom parameters                                                    #
    # ------------------------------------------------------------------ #
    def test_custom_parameters(self):
        """Build with --alpha 0.95 --lambda 4.0 and verify bijectivity."""
        kf = f"{DATA}/random_1k.txt"
        mph = "/tmp/tb_custom.mph"
        n = len(_read_keys(kf))

        r = _run(["build", kf, mph, "--alpha", "0.95", "--lambda", "4.0"])
        assert r.returncode == 0, f"build with custom params failed:\n{r.stderr}"

        r = _run(["query", mph, kf])
        assert r.returncode == 0, f"query failed:\n{r.stderr}"
        _check_bijective(r.stdout, n)

    # ------------------------------------------------------------------ #
    # Serialization round-trip                                             #
    # ------------------------------------------------------------------ #
    def test_serialization_roundtrip(self):
        """build -> save -> load -> query must match across sessions."""
        kf = f"{DATA}/random_1k.txt"
        mph_a = "/tmp/tb_rt_a.mph"
        mph_b = "/tmp/tb_rt_b.mph"
        n = len(_read_keys(kf))

        # Build and query
        r = _run(["build", kf, mph_a])
        assert r.returncode == 0
        r1 = _run(["query", mph_a, kf])
        assert r1.returncode == 0
        _check_bijective(r1.stdout, n)

        # Query same file again from a separate invocation
        r2 = _run(["query", mph_a, kf])
        assert r2.returncode == 0
        assert r1.stdout == r2.stdout, "Round-trip query mismatch"
