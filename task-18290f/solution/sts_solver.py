#!/usr/bin/env python3
"""
NIST SP 800-22 PRNG Forensic Analysis Solver.

Implements 10 statistical tests from NIST SP 800-22 Rev 1a,
stores results in SQLite, classifies 5 PRNG samples.

"""

import json
import math
import os
import sqlite3

import numpy as np
from scipy.special import erfc, gammaincc
from scipy.stats import norm

SAMPLE_DIR = "/app/samples"
DB_PATH = "/app/rng_analysis.db"
ALPHA = 0.01


# ============================================================
# Bit reading
# ============================================================

def read_bits(filepath):
    """Read binary file, return list of bits (MSB first per byte)."""
    with open(filepath, "rb") as f:
        data = f.read()
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


# ============================================================
# Test 1: Frequency (Monobit) — Section 2.1
# ============================================================

def frequency_monobit(bits):
    n = len(bits)
    S_n = 2 * sum(bits) - n
    s_obs = abs(S_n) / math.sqrt(n)
    return float(erfc(s_obs / math.sqrt(2)))


# ============================================================
# Test 2: Frequency within a Block — Section 2.2
# ============================================================

def frequency_block(bits, M=128):
    n = len(bits)
    N = n // M
    chi_sq = 0.0
    for i in range(N):
        pi_i = sum(bits[i * M:(i + 1) * M]) / M
        chi_sq += (pi_i - 0.5) ** 2
    chi_sq *= 4 * M
    return float(gammaincc(N / 2.0, chi_sq / 2.0))


# ============================================================
# Test 3: Runs Test — Section 2.3
# ============================================================

def runs_test(bits):
    n = len(bits)
    ones = sum(bits)
    pi = ones / n
    # Prerequisite: if proportion too far from 0.5, test is not applicable
    if abs(pi - 0.5) >= 2.0 / math.sqrt(n):
        return 0.0
    V_n = 1
    for i in range(1, n):
        if bits[i] != bits[i - 1]:
            V_n += 1
    num = abs(V_n - 2.0 * n * pi * (1.0 - pi))
    den = 2.0 * math.sqrt(2.0 * n) * pi * (1.0 - pi)
    return float(erfc(num / den))


# ============================================================
# Test 4: Longest Run of Ones in a Block — Section 2.4
# ============================================================

def longest_run_ones(bits):
    n = len(bits)
    if n < 128:
        return 0.0
    if n < 6272:
        M, K = 8, 3
        pi_vals = [0.2148, 0.3672, 0.2305, 0.1875]
        v_min = 1
    elif n < 750000:
        M, K = 128, 5
        pi_vals = [0.1174, 0.2430, 0.2493, 0.1752, 0.1027, 0.1124]
        v_min = 4
    else:
        M, K = 10000, 6
        pi_vals = [0.0882, 0.2092, 0.2483, 0.1933, 0.1208, 0.0675, 0.0727]
        v_min = 10
    N_blocks = n // M
    freq = [0] * (K + 1)
    for block_idx in range(N_blocks):
        block = bits[block_idx * M:(block_idx + 1) * M]
        max_run = cur = 0
        for bit in block:
            if bit == 1:
                cur += 1
                if cur > max_run:
                    max_run = cur
            else:
                cur = 0
        idx = max(0, min(K, max_run - v_min))
        freq[idx] += 1
    chi_sq = sum(
        (freq[i] - N_blocks * pi_vals[i]) ** 2 / (N_blocks * pi_vals[i])
        for i in range(K + 1)
    )
    return float(gammaincc(K / 2.0, chi_sq / 2.0))


# ============================================================
# Test 5: Binary Matrix Rank — Section 2.5
# ============================================================

def gf2_rank(rows, Q):
    """Compute rank of binary matrix over GF(2). Rows are integers."""
    r = list(rows)
    rank = 0
    for col in range(Q - 1, -1, -1):
        mask = 1 << col
        pivot = None
        for i in range(rank, len(r)):
            if r[i] & mask:
                pivot = i
                break
        if pivot is None:
            continue
        r[rank], r[pivot] = r[pivot], r[rank]
        for i in range(len(r)):
            if i != rank and r[i] & mask:
                r[i] ^= r[rank]
        rank += 1
    return rank


def binary_matrix_rank(bits):
    n = len(bits)
    M = Q = 32
    N = n // (M * Q)
    if N < 38:
        return 0.0

    # Compute exact probability of full rank for M=Q=32
    p_M = 1.0
    for i in range(M):
        p_M *= (1.0 - 2.0 ** (i - Q))
    p_M1 = 2.0 * p_M  # P(rank=M-1) = 2 * P(rank=M) for square matrices
    p_rem = 1.0 - p_M - p_M1

    F = [0, 0, 0]  # [full rank, rank-1, rest]
    for i in range(N):
        start = i * M * Q
        rows = []
        for row in range(M):
            val = 0
            for c in range(Q):
                val = (val << 1) | bits[start + row * Q + c]
            rows.append(val)
        rank = gf2_rank(rows, Q)
        if rank == M:
            F[0] += 1
        elif rank == M - 1:
            F[1] += 1
        else:
            F[2] += 1

    chi_sq = ((F[0] - N * p_M) ** 2 / (N * p_M) +
              (F[1] - N * p_M1) ** 2 / (N * p_M1) +
              (F[2] - N * p_rem) ** 2 / (N * p_rem))
    return float(math.exp(-chi_sq / 2.0))


# ============================================================
# Test 6: Discrete Fourier Transform (Spectral) — Section 2.6
# ============================================================

def dft_spectral(bits):
    n = len(bits)
    x = np.array([2 * b - 1 for b in bits], dtype=np.float64)
    S = np.fft.fft(x)
    modulus = np.abs(S[:n // 2])
    T = math.sqrt(math.log(1.0 / 0.05) * n)
    N_0 = 0.95 * n / 2.0
    N_1 = float(np.sum(modulus < T))
    d = (N_1 - N_0) / math.sqrt(n * 0.95 * 0.05 / 4.0)
    return float(erfc(abs(d) / math.sqrt(2)))


# ============================================================
# Test 7: Non-overlapping Template Matching — Section 2.7
# ============================================================

def non_overlapping_template(bits, template_str="000000001"):
    n = len(bits)
    m = len(template_str)
    template = [int(c) for c in template_str]
    N_blocks = 8
    M = n // N_blocks

    mu = (M - m + 1) / (2.0 ** m)
    sigma_sq = M * (1.0 / (2.0 ** m) - (2 * m - 1) / (2.0 ** (2 * m)))

    chi_sq = 0.0
    for block_idx in range(N_blocks):
        block = bits[block_idx * M:(block_idx + 1) * M]
        count = 0
        j = 0
        while j <= M - m:
            if block[j:j + m] == template:
                count += 1
                j += m  # skip ahead (non-overlapping)
            else:
                j += 1
        chi_sq += (count - mu) ** 2 / sigma_sq

    return float(gammaincc(N_blocks / 2.0, chi_sq / 2.0))


# ============================================================
# Test 8: Serial Test — Section 2.11
# ============================================================

def count_patterns(bits, m):
    """Count overlapping m-bit patterns with wraparound."""
    n = len(bits)
    if m == 0:
        return {0: n}
    counts = {}
    mask = (1 << m) - 1
    pattern = 0
    for j in range(m):
        pattern = (pattern << 1) | bits[j]
    for i in range(n):
        counts[pattern] = counts.get(pattern, 0) + 1
        next_bit = bits[(i + m) % n]
        pattern = ((pattern << 1) | next_bit) & mask
    return counts


def psi_sq(bits, m):
    n = len(bits)
    if m == 0:
        return 0.0
    counts = count_patterns(bits, m)
    total = sum(v * v for v in counts.values())
    return (2 ** m / n) * total - n


def serial_test(bits, m=16):
    psim = psi_sq(bits, m)
    psim1 = psi_sq(bits, m - 1)
    psim2 = psi_sq(bits, m - 2)
    delta1 = psim - psim1
    delta2 = psim - 2 * psim1 + psim2
    p1 = float(gammaincc(2 ** (m - 2), delta1 / 2.0))
    p2 = float(gammaincc(2 ** (m - 3), delta2 / 2.0))
    return min(p1, p2)


# ============================================================
# Test 9: Approximate Entropy — Section 2.12
# ============================================================

def phi_m(bits, m):
    n = len(bits)
    if m == 0:
        return 0.0
    counts = count_patterns(bits, m)
    total = 0.0
    for c in counts.values():
        if c > 0:
            total += c * math.log(c / n)
    return total / n


def approximate_entropy(bits, m=10):
    pm = phi_m(bits, m)
    pm1 = phi_m(bits, m + 1)
    apen = pm - pm1
    n = len(bits)
    chi_sq = 2.0 * n * (math.log(2) - apen)
    return float(gammaincc(2 ** (m - 1), chi_sq / 2.0))


# ============================================================
# Test 10: Cumulative Sums (Forward) — Section 2.13
# ============================================================

def cumulative_sums(bits):
    n = len(bits)
    S = 0
    z = 0
    for b in bits:
        S += 2 * b - 1
        if abs(S) > z:
            z = abs(S)
    if z == 0:
        return 1.0

    sqrt_n = math.sqrt(n)
    sum1 = 0.0
    k_start = int(math.floor((-n / z + 1) / 4))
    k_end = int(math.floor((n / z - 1) / 4))
    for k in range(k_start, k_end + 1):
        sum1 += (norm.cdf((4 * k + 1) * z / sqrt_n) -
                 norm.cdf((4 * k - 1) * z / sqrt_n))

    sum2 = 0.0
    k_start2 = int(math.floor((-n / z - 3) / 4))
    k_end2 = int(math.floor((n / z - 1) / 4))
    for k in range(k_start2, k_end2 + 1):
        sum2 += (norm.cdf((4 * k + 3) * z / sqrt_n) -
                 norm.cdf((4 * k + 1) * z / sqrt_n))

    p = 1.0 - sum1 + sum2
    return float(max(0.0, min(1.0, p)))


# ============================================================
# Classification
# ============================================================

def classify(results):
    """Classify generator type using a priority-ordered decision tree.

    Priority order ensures correct separation:
    1. Monobit failure -> bias (only biased generators fail this)
    2. Rank failure -> LFSR (GF(2) linear structure)
    3. Runs failure -> serial correlation (Markov-type dependence)
    4. Spectral failure -> short-period LCG (periodicity)
    5. Otherwise -> high quality PRNG
    """
    def failed(name):
        return not results.get(name, {}).get("pass", True)

    if failed("frequency_monobit"):
        return "biased"
    if failed("binary_matrix_rank"):
        return "short_period_lfsr"
    if failed("runs"):
        return "serial_correlated"
    if failed("dft_spectral"):
        return "short_period_lcg"
    return "high_quality_prng"


# ============================================================
# Database
# ============================================================

def setup_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE test_results ("
        "sample_name TEXT NOT NULL, "
        "test_name TEXT NOT NULL, "
        "p_value REAL NOT NULL, "
        "pass INTEGER NOT NULL, "
        "PRIMARY KEY (sample_name, test_name))"
    )
    conn.execute(
        "CREATE TABLE classifications ("
        "sample_name TEXT PRIMARY KEY, "
        "generator_type TEXT NOT NULL)"
    )
    conn.commit()
    return conn


# ============================================================
# Main
# ============================================================

TEST_FUNCS = {
    "frequency_monobit": frequency_monobit,
    "frequency_block": frequency_block,
    "runs": runs_test,
    "longest_run_ones": longest_run_ones,
    "binary_matrix_rank": binary_matrix_rank,
    "dft_spectral": dft_spectral,
    "non_overlapping_template": non_overlapping_template,
    "serial": serial_test,
    "approximate_entropy": approximate_entropy,
    "cumulative_sums": cumulative_sums,
}


def main():
    conn = setup_database()
    print(f"Created database: {DB_PATH}")

    samples = sorted(f for f in os.listdir(SAMPLE_DIR) if f.endswith(".bin"))
    all_results = {}
    classifications = {}

    for sample in samples:
        path = os.path.join(SAMPLE_DIR, sample)
        print(f"\n{'=' * 60}")
        print(f"  {sample}")
        print(f"{'=' * 60}")

        bits = read_bits(path)
        results = {}

        for test_name, func in TEST_FUNCS.items():
            print(f"  {test_name}...", end=" ", flush=True)
            try:
                p = func(bits)
                p = max(0.0, min(1.0, float(p)))
            except Exception as e:
                print(f"ERROR: {e}")
                p = 0.0
            passed = p >= ALPHA
            results[test_name] = {"p_value": round(p, 10), "pass": passed}
            status = "PASS" if passed else "FAIL"
            print(f"p={p:.6e} {status}")
            conn.execute(
                "INSERT INTO test_results (sample_name, test_name, p_value, pass) "
                "VALUES (?,?,?,?)",
                (sample, test_name, round(p, 10), 1 if passed else 0),
            )

        gen_type = classify(results)
        classifications[sample] = gen_type
        print(f"  -> Classification: {gen_type}")
        conn.execute(
            "INSERT INTO classifications (sample_name, generator_type) VALUES (?,?)",
            (sample, gen_type),
        )

        all_results[sample] = results
        conn.commit()

    # Write output files
    with open("/app/results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote /app/results.json")

    with open("/app/analysis.json", "w") as f:
        json.dump(classifications, f, indent=2)
    print(f"Wrote /app/analysis.json")

    conn.close()
    print(f"Database saved: {DB_PATH}")


if __name__ == "__main__":
    main()
