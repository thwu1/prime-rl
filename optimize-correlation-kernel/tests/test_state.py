
import numpy as np
import struct
import json
import os
import pytest


def read_binary(path):
    """Read binary file: int32 a, int32 b, then float64 array."""
    with open(path, 'rb') as f:
        a, b = struct.unpack('ii', f.read(8))
        data = np.frombuffer(f.read(), dtype=np.float64)
    return a, b, data


def compute_reference_correlations(input_path):
    """Compute ground-truth correlations using numpy in float64."""
    n, m, flat = read_binary(input_path)
    data = flat.reshape(n, m)
    means = data.mean(axis=1, keepdims=True)
    centered = data - means
    norms = np.sqrt((centered ** 2).sum(axis=1, keepdims=True))
    norms[norms == 0] = 1.0
    normalized = centered / norms
    corr = normalized @ normalized.T
    return n, corr[np.triu_indices(n, k=1)]


class TestOutputFormat:
    def test_output_exists(self):
        assert os.path.exists('/app/output.bin'), \
            "Output file /app/output.bin does not exist"

    def test_output_readable(self):
        n, num_pairs, data = read_binary('/app/output.bin')
        assert n > 0, "Output n must be positive"
        assert num_pairs == n * (n - 1) // 2, \
            f"num_pairs={num_pairs} doesn't match n*(n-1)/2={n*(n-1)//2}"
        assert len(data) == num_pairs, \
            f"Data length {len(data)} doesn't match num_pairs {num_pairs}"


class TestCorrectness:
    def test_correlation_values(self):
        ref_n, ref_corr = compute_reference_correlations('/app/input.bin')
        out_n, num_pairs, out_data = read_binary('/app/output.bin')

        assert out_n == ref_n, \
            f"Output n={out_n} doesn't match expected n={ref_n}"
        assert len(out_data) == len(ref_corr), \
            f"Output length {len(out_data)} doesn't match reference {len(ref_corr)}"

        max_diff = float(np.max(np.abs(out_data - ref_corr)))
        mean_diff = float(np.mean(np.abs(out_data - ref_corr)))
        print(f"\nCorrectness: max_diff={max_diff:.6f}, mean_diff={mean_diff:.8f}")

        assert max_diff < 5e-3, \
            f"Max absolute error {max_diff:.6f} exceeds tolerance 5e-3"

    def test_correlations_in_valid_range(self):
        _, _, out_data = read_binary('/app/output.bin')
        assert np.all(out_data >= -1.01) and np.all(out_data <= 1.01), \
            "Some correlation values are outside [-1, 1] range"


class TestPerformance:
    def test_speedup(self):
        timing_path = '/app/timing.json'
        assert os.path.exists(timing_path), "Timing file not found"

        with open(timing_path) as f:
            timing = json.load(f)

        baseline = timing['baseline_time']
        optimized = timing['optimized_time']

        assert baseline > 0, "Baseline did not run successfully"
        assert optimized < 9999, "Optimized version did not run successfully"

        speedup = baseline / optimized
        print(f"\nBaseline: {baseline:.2f}s, Optimized: {optimized:.2f}s, "
              f"Speedup: {speedup:.2f}x")

        assert speedup >= 5.0, \
            (f"Speedup {speedup:.2f}x is below required 5.0x "
             f"(baseline={baseline:.2f}s, optimized={optimized:.2f}s)")
