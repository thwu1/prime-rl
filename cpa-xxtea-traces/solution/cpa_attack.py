#!/usr/bin/env python3

"""
CPA attack with SAD-based trace alignment to recover XXTEA key.

Two-phase divide-and-conquer:
  Phase 1: Recover key bytes 0-7 via CPA on HW(plaintext[i] ^ key_guess)
  Phase 2: Recover key bytes 8-15 via CPA on HW((pt[i%8] ^ key[i%8]) ^ key_guess)
           using Phase 1 results to compute modified intermediates
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import h5py
import sys

# ===== Load Data from HDF5 =====
print("Loading trace data from HDF5...")
with h5py.File('/app/captures/traces.h5', 'r') as f:
    traces = f['measurements/power_traces'][:]
    plaintexts = f['measurements/stimulus/plaintext_inputs'][:]

with h5py.File('/app/captures/intercept.h5', 'r') as f:
    ciphertext = f['payload/encrypted_blocks'][:]

N_TRACES, N_SAMPLES = traces.shape
print(f"Loaded {N_TRACES} traces of {N_SAMPLES} samples")

# ===== Device Parameters (discovered from device_sim info and traces) =====
FIRST_OP = 150
DELAY = 237
MAX_SHIFT = 28  # alignment search range (covers global + per-op jitter)

# ===== XXTEA Constants =====
DELTA = 0x9e3779b9
MASK32 = 0xFFFFFFFF


def hw(x):
    """Hamming weight of byte value."""
    return bin(x & 0xFF).count('1')

v_hw = np.vectorize(hw)


def get_op_center(i):
    """Nominal center sample for operation i."""
    return FIRST_OP + i * DELAY


def align_traces(traces, op_idx, ref_hw=15, max_shift=MAX_SHIFT):
    """Align traces using Sum of Absolute Differences around operation point.

    Uses the first trace as reference. For each subsequent trace, finds
    the shift (within +/-max_shift) that minimizes SAD with the reference
    window, then shifts the entire trace to compensate.

    Args:
        traces: [N, S] float array of power traces
        op_idx: operation index (0-15) to align around
        ref_hw: half-width of reference window for SAD
        max_shift: maximum shift to search
    Returns:
        [N, S] float array of aligned traces
    """
    center = get_op_center(op_idx)
    ref_start = center - ref_hw
    ref_len = 2 * ref_hw

    if ref_start < 0 or ref_start + ref_len >= N_SAMPLES:
        return traces.copy()

    ref = traces[0, ref_start:ref_start + ref_len].copy()

    search_lo = max(0, ref_start - max_shift)
    search_hi = min(N_SAMPLES - ref_len, ref_start + max_shift) + 1

    aligned = np.copy(traces)

    for t in range(1, N_TRACES):
        segment = traces[t, search_lo:search_hi + ref_len - 1]
        if len(segment) < ref_len:
            continue
        windows = sliding_window_view(segment, ref_len)
        sads = np.sum(np.abs(windows - ref), axis=1)
        best_pos = search_lo + np.argmin(sads)
        shift = best_pos - ref_start

        if shift > 0:
            aligned[t, :-shift] = traces[t, shift:]
            aligned[t, -shift:] = 0
        elif shift < 0:
            aligned[t, -shift:] = traces[t, :shift]
            aligned[t, :-shift] = 0

    return aligned


def cpa_byte(aligned_traces, hyp_hw, op_idx, search_margin=35):
    """Perform CPA for a single key byte position.

    Correlates Hamming weight hypotheses with aligned trace power values
    in a window around the operation point.

    Args:
        aligned_traces: [N, S] aligned power traces
        hyp_hw: [N, 256] float64 hypothetical HW for each key guess
        op_idx: operation index (0-15)
        search_margin: half-width of CPA search window
    Returns:
        best key byte guess (0-255)
    """
    center = get_op_center(op_idx)
    win_start = max(0, center - search_margin)
    win_end = min(N_SAMPLES, center + search_margin)

    t_slice = aligned_traces[:, win_start:win_end].astype(np.float64)
    n = t_slice.shape[0]

    t_mean = np.mean(t_slice, axis=0)
    t_std = np.std(t_slice, axis=0, ddof=1)
    t_std[t_std == 0] = 1.0

    h_mean = np.mean(hyp_hw, axis=0)
    h_std = np.std(hyp_hw, axis=0, ddof=1)
    h_std[h_std == 0] = 1.0

    # Pearson correlation matrix: [time_points, 256]
    corr = (t_slice.T @ hyp_hw - n * t_mean[:, None] * h_mean[None, :]) / \
           ((n - 1) * t_std[:, None] * h_std[None, :])

    max_corr = np.max(corr, axis=0)
    best_guess = int(np.argmax(max_corr))

    return best_guess


# ===== Phase 1: Recover Key Bytes 0-7 =====
print("\n=== Phase 1: Key bytes 0-7 (direct CPA) ===")
key_bytes = [0] * 16

for i in range(8):
    print(f"  Byte {i}: aligning traces...", end=" ", flush=True)
    aligned = align_traces(traces, i)

    pt = plaintexts[:, i]
    hyp = np.zeros((N_TRACES, 256), dtype=np.float64)
    for g in range(256):
        hyp[:, g] = v_hw(pt ^ g)

    key_bytes[i] = cpa_byte(aligned, hyp, i)
    print(f"recovered 0x{key_bytes[i]:02x}")

    del aligned  # free memory


# ===== Phase 2: Recover Key Bytes 8-15 =====
print("\n=== Phase 2: Key bytes 8-15 (chain-dependent CPA) ===")

for i in range(8, 16):
    print(f"  Byte {i}: aligning traces...", end=" ", flush=True)
    aligned = align_traces(traces, i)

    pt = plaintexts[:, i % 8]
    # After phase 1 XOR, data[i%8] = plaintext[i%8] ^ key[i%8]
    modified_pt = pt ^ key_bytes[i % 8]

    hyp = np.zeros((N_TRACES, 256), dtype=np.float64)
    for g in range(256):
        hyp[:, g] = v_hw(modified_pt ^ g)

    key_bytes[i] = cpa_byte(aligned, hyp, i)
    print(f"recovered 0x{key_bytes[i]:02x}")

    del aligned


key = bytes(key_bytes)
print(f"\nRecovered key: {key.hex()}")

# Save key
with open('/app/recovered_key.hex', 'w') as f:
    f.write(key.hex())


# ===== Decrypt Flag =====
print("\nDecrypting flag...")


def _mx(z, y, s, k):
    return (
        (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
        ^ ((s ^ y) + (k ^ z))
    ) & MASK32


def xxtea_decrypt(v, xkey):
    v = list(v)
    n = len(v)
    if n <= 1:
        return v
    rounds = 6 + 52 // n
    s = (rounds * DELTA) & MASK32
    y = v[0]
    for _ in range(rounds):
        e = (s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            v[p] = (v[p] - _mx(z, y, s, xkey[(p & 3) ^ e])) & MASK32
            y = v[p]
        z = v[n - 1]
        v[0] = (v[0] - _mx(z, y, s, xkey[0 ^ e])) & MASK32
        y = v[0]
        s = (s - DELTA) & MASK32
    return v


key_u32 = [int.from_bytes(key[i:i+4], 'little') for i in range(0, 16, 4)]
dec_words = xxtea_decrypt([int(x) for x in ciphertext], key_u32)
dec_data = bytearray(b''.join(int(w).to_bytes(4, 'little') for w in dec_words))

# Reverse XOR preprocessing (in reverse order)
for i in range(15, -1, -1):
    dec_data[i % len(dec_data)] ^= key[i]

flag = bytes(dec_data).rstrip(b'\x00').decode('ascii', errors='replace')
print(f"Flag: {flag}")

with open('/app/flag.txt', 'w') as f:
    f.write(flag)

print("\nDone.")
