#!/usr/bin/env python3
"""
NIST SP 800-22 Rev. 1a Statistical Test Suite Implementation.
Implements 7 tests with two-level proportion/uniformity assessment.
"""

import json
import math
import os

import numpy as np
from scipy.fft import fft
from scipy.special import erfc, gammaincc
from scipy.stats import norm


def read_config():
    with open('/srv/nist/config.json') as f:
        return json.load(f)


def load_bitstreams(filepath, stream_length, num_streams):
    """Load binary file and split into bitstreams (MSB first, 8 bits/byte)."""
    with open(filepath, 'rb') as f:
        raw = f.read()

    all_bits = []
    for byte_val in raw:
        for bit_pos in range(7, -1, -1):
            all_bits.append((byte_val >> bit_pos) & 1)

    streams = []
    for i in range(num_streams):
        start = i * stream_length
        end = start + stream_length
        streams.append(all_bits[start:end])
    return streams


# ============================================================
# Test Implementations (Sections 2.x of NIST SP 800-22 Rev 1a)
# ============================================================

def frequency_test(bits):
    """Section 2.1: Frequency (Monobit) Test."""
    n = len(bits)
    s_n = sum(2 * b - 1 for b in bits)
    s_obs = abs(s_n) / math.sqrt(n)
    return float(erfc(s_obs / math.sqrt(2)))


def block_frequency_test(bits, block_size=128):
    """Section 2.2: Frequency Test within a Block."""
    n = len(bits)
    N = n // block_size
    chi_sq = 0.0
    for i in range(N):
        block = bits[i * block_size:(i + 1) * block_size]
        pi_i = sum(block) / block_size
        chi_sq += (pi_i - 0.5) ** 2
    chi_sq *= 4.0 * block_size
    return float(gammaincc(N / 2.0, chi_sq / 2.0))


def runs_test(bits):
    """Section 2.3: Runs Test."""
    n = len(bits)
    pi = sum(bits) / n
    tau = 2.0 / math.sqrt(n)

    # Prerequisite: frequency test must pass
    if abs(pi - 0.5) >= tau:
        return 0.0

    # Count runs
    v_obs = 1
    for i in range(1, n):
        if bits[i] != bits[i - 1]:
            v_obs += 1

    numerator = abs(v_obs - 2.0 * n * pi * (1.0 - pi))
    denominator = 2.0 * math.sqrt(2.0 * n) * pi * (1.0 - pi)
    return float(erfc(numerator / denominator))


def longest_run_test(bits):
    """Section 2.4: Longest Run of Ones in a Block."""
    n = len(bits)

    if n < 128:
        return 0.0

    if n < 6272:
        M = 8
        K = 3
        V = [1, 2, 3, 4]
        pi = [0.2148, 0.3672, 0.2305, 0.1875]
    elif n < 750000:
        M = 128
        K = 5
        V = [4, 5, 6, 7, 8, 9]
        pi = [0.1174035788, 0.242955959, 0.249363483,
              0.17517706, 0.102701071, 0.112398847]
    else:
        M = 10000
        K = 6
        V = [10, 11, 12, 13, 14, 15, 16]
        pi = [0.0882, 0.2092, 0.2483, 0.1933, 0.1208, 0.0675, 0.0727]

    N = n // M
    nu = [0] * (K + 1)

    for i in range(N):
        block = bits[i * M:(i + 1) * M]
        max_run = 0
        current_run = 0
        for b in block:
            if b == 1:
                current_run += 1
                if current_run > max_run:
                    max_run = current_run
            else:
                current_run = 0

        if max_run <= V[0]:
            nu[0] += 1
        elif max_run >= V[K]:
            nu[K] += 1
        else:
            for j in range(1, K):
                if max_run == V[j]:
                    nu[j] += 1
                    break

    chi_sq = sum((nu[i] - N * pi[i]) ** 2 / (N * pi[i]) for i in range(K + 1))
    return float(gammaincc(K / 2.0, chi_sq / 2.0))


def dft_test(bits):
    """Section 2.6: Discrete Fourier Transform (Spectral) Test."""
    n = len(bits)
    x = np.array([2 * b - 1 for b in bits], dtype=np.float64)

    S = fft(x)
    M = np.abs(S[:n // 2])

    T = math.sqrt(math.log(1.0 / 0.05) * n)
    N_1 = int(np.sum(M < T))
    N_0 = 0.95 * n / 2.0

    d = (N_1 - N_0) / math.sqrt(n * 0.95 * 0.05 / 4.0)
    return float(erfc(abs(d) / math.sqrt(2)))


def cumulative_sums_test(bits, mode="forward"):
    """Section 2.13: Cumulative Sums Test."""
    n = len(bits)

    if mode == "reverse":
        x = [2 * b - 1 for b in reversed(bits)]
    else:
        x = [2 * b - 1 for b in bits]

    # Compute max absolute partial sum
    S = 0
    z = 0
    for val in x:
        S += val
        if abs(S) > z:
            z = abs(S)

    if z == 0:
        return 1.0

    sqrt_n = math.sqrt(n)

    # Compute p-value using the formula from Section 2.13.4
    k1_start = int((-n / z + 1) / 4)
    k1_end = int((n / z - 1) / 4)
    k1 = np.arange(k1_start, k1_end + 1, dtype=np.float64)
    sum1 = float(np.sum(
        norm.cdf((4 * k1 + 1) * z / sqrt_n) -
        norm.cdf((4 * k1 - 1) * z / sqrt_n)
    ))

    k2_start = int((-n / z - 3) / 4)
    k2_end = int((n / z - 1) / 4)
    k2 = np.arange(k2_start, k2_end + 1, dtype=np.float64)
    sum2 = float(np.sum(
        norm.cdf((4 * k2 + 3) * z / sqrt_n) -
        norm.cdf((4 * k2 + 1) * z / sqrt_n)
    ))

    p_value = 1.0 - sum1 + sum2
    return float(max(0.0, min(1.0, p_value)))


def approximate_entropy_test(bits, m=10):
    """Section 2.12: Approximate Entropy Test."""
    n = len(bits)

    def compute_phi(block_len):
        if block_len == 0:
            return 0.0
        # Augment the sequence by appending first (block_len - 1) bits
        augmented = bits + bits[:block_len - 1]
        # Build initial pattern as integer
        pattern = 0
        for j in range(block_len):
            pattern = (pattern << 1) | augmented[j]
        mask = (1 << block_len) - 1
        pattern_counts = {}
        pattern_counts[pattern] = 1
        for i in range(1, n):
            pattern = ((pattern << 1) | augmented[i + block_len - 1]) & mask
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        # Compute phi = sum(C_i * ln(C_i))
        phi = 0.0
        for count in pattern_counts.values():
            c = count / n
            if c > 0:
                phi += c * math.log(c)
        return phi

    phi_m = compute_phi(m)
    phi_m1 = compute_phi(m + 1)

    apen = phi_m - phi_m1
    chi_sq = 2.0 * n * (math.log(2) - apen)
    p_value = float(gammaincc(2 ** (m - 1), chi_sq / 2.0))
    return p_value


# ============================================================
# Two-Level Assessment (Section 4 of NIST SP 800-22)
# ============================================================

def proportion_assessment(p_values, alpha):
    """Check that the proportion of passing streams meets the minimum pass rate."""
    m = len(p_values)
    passing = sum(1 for p in p_values if p >= alpha)
    proportion = passing / m
    p_hat = 1.0 - alpha
    min_rate = p_hat - 3.0 * math.sqrt(p_hat * (1.0 - p_hat) / m)
    result = "pass" if proportion >= min_rate else "fail"
    return proportion, result


def uniformity_assessment(p_values):
    """Check uniformity of p-values via chi-squared over 10 bins."""
    m = len(p_values)
    bins = [0] * 10
    for p in p_values:
        idx = min(int(p * 10), 9)
        bins[idx] += 1

    expected = m / 10.0
    chi_sq = sum((f - expected) ** 2 / expected for f in bins)
    p_value = float(gammaincc(9.0 / 2.0, chi_sq / 2.0))
    result = "pass" if p_value >= 0.0001 else "fail"
    return p_value, result


# ============================================================
# Main
# ============================================================

def main():
    config = read_config()

    data_dir = config["data_dir"]
    stream_length = config["stream_length_bits"]
    num_streams = config["num_streams"]
    alpha = config["significance_level"]
    tests_config = config["tests"]
    sources = config["sources"]

    test_funcs = {
        "frequency": lambda bits: frequency_test(bits),
        "block_frequency": lambda bits: block_frequency_test(
            bits, tests_config["block_frequency"].get("block_size", 128)
        ),
        "runs": lambda bits: runs_test(bits),
        "longest_run": lambda bits: longest_run_test(bits),
        "dft": lambda bits: dft_test(bits),
        "cumulative_sums": lambda bits: cumulative_sums_test(
            bits, tests_config["cumulative_sums"].get("mode", "forward")
        ),
        "approximate_entropy": lambda bits: approximate_entropy_test(
            bits, tests_config["approximate_entropy"].get("m", 10)
        ),
    }

    results = {}
    summary = {}

    for source in sources:
        filepath = os.path.join(data_dir, source)
        print(f"Processing {source}...")
        streams = load_bitstreams(filepath, stream_length, num_streams)

        results[source] = {}
        failing_tests = []

        for test_name in tests_config:
            if test_name not in test_funcs:
                continue

            test_func = test_funcs[test_name]
            p_values = []
            for j, stream in enumerate(streams):
                pv = test_func(stream)
                p_values.append(pv)

            prop_val, prop_result = proportion_assessment(p_values, alpha)
            uni_pval, uni_result = uniformity_assessment(p_values)

            results[source][test_name] = {
                "p_values": p_values,
                "proportion_passing": prop_val,
                "proportion_result": prop_result,
                "uniformity_pvalue": uni_pval,
                "uniformity_result": uni_result,
            }

            if prop_result == "fail" or uni_result == "fail":
                failing_tests.append(test_name)

            print(f"  {test_name}: proportion={prop_val:.3f} ({prop_result}), "
                  f"uniformity={uni_pval:.6f} ({uni_result})")

        overall = "pass" if len(failing_tests) == 0 else "fail"
        summary[source] = {
            "overall": overall,
            "failing_tests": sorted(failing_tests),
        }
        print(f"  => {source}: {overall}")
        if failing_tests:
            print(f"     Failing: {', '.join(sorted(failing_tests))}")

    results["summary"] = summary

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == '__main__':
    main()
