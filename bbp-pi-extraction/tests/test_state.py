
import os
import subprocess
import time

import mpmath
import pytest


def pi_hex_digits_reference(start, count):
    """Compute hex digits of pi independently using mpmath."""
    prec = 4 * (start + count + 50)
    mpmath.mp.prec = max(prec, 256)

    val = mpmath.power(mpmath.mpf(16), start) * mpmath.pi
    val = val - int(val)

    result = ""
    for _ in range(count):
        val *= 16
        d = int(val)
        d = max(0, min(15, d))
        result += "0123456789ABCDEF"[d]
        val -= d
    return result


def run_pi_extract(position, count, timeout=120):
    """Run the pi_extract binary and return its stdout."""
    r = subprocess.run(
        ["/app/pi_extract", str(position), str(count)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert r.returncode == 0, (
        f"pi_extract failed at pos={position}: {r.stderr}"
    )
    return r.stdout.strip()


class TestPiHexExtraction:
    def test_binary_exists(self):
        assert os.path.isfile("/app/pi_extract"), "/app/pi_extract not found"

    def test_position_0(self):
        """First 20 hex digits of pi after decimal point."""
        actual = run_pi_extract(0, 20)
        expected = pi_hex_digits_reference(0, 20)
        assert actual == expected, f"pos=0: expected {expected}, got {actual}"

    def test_position_10(self):
        actual = run_pi_extract(10, 8)
        expected = pi_hex_digits_reference(10, 8)
        assert actual == expected, f"pos=10: expected {expected}, got {actual}"

    def test_position_100(self):
        actual = run_pi_extract(100, 8)
        expected = pi_hex_digits_reference(100, 8)
        assert actual == expected, f"pos=100: expected {expected}, got {actual}"

    def test_position_1000(self):
        actual = run_pi_extract(1000, 8)
        expected = pi_hex_digits_reference(1000, 8)
        assert actual == expected, f"pos=1000: expected {expected}, got {actual}"

    def test_position_10000(self):
        actual = run_pi_extract(10000, 4)
        expected = pi_hex_digits_reference(10000, 4)
        assert actual == expected, f"pos=10000: expected {expected}, got {actual}"

    def test_position_100000(self):
        actual = run_pi_extract(100000, 2)
        expected = pi_hex_digits_reference(100000, 2)
        assert actual == expected, f"pos=100000: expected {expected}, got {actual}"

    def test_performance(self):
        """Ensure computation at large positions completes quickly."""
        t0 = time.time()
        run_pi_extract(100000, 1, timeout=60)
        elapsed = time.time() - t0
        assert elapsed < 30, f"Too slow at pos=100000: {elapsed:.1f}s"
