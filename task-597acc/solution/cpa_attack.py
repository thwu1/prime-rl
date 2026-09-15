#!/usr/bin/env python3
"""
AES-128 First-Round CPA Key Recovery from TRS-lite Power Traces.

Pipeline:
  1. Parse custom TRS-lite binary format (struct module)
  2. Low-pass filter to remove clock harmonics (scipy.signal)
  3. Two-phase trace alignment: rough trigger detection + cross-correlation refinement
  4. CPA with AES S-box Hamming weight leakage model (numpy)
  5. Key verification and output
"""

import struct
import numpy as np
from scipy.signal import butter, sosfiltfilt, correlate


# ── AES S-box ──────────────────────────────────────────────────────────────

SBOX = np.array([
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16
], dtype=np.uint8)

# Hamming weight lookup table
HW_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.float64)


# ── Step 1: Parse TRS-lite binary format ───────────────────────────────────

def parse_trs(filepath):
    """Parse TRS-lite binary format using struct for header decoding."""
    with open(filepath, 'rb') as f:
        raw_header = f.read(32)
        magic = raw_header[0:4]
        if magic != b'TRS\x01':
            raise ValueError(f"Invalid TRS magic: {magic!r}")

        n_traces = struct.unpack_from('<I', raw_header, 4)[0]
        n_samples = struct.unpack_from('<I', raw_header, 8)[0]
        crypto_len = struct.unpack_from('<H', raw_header, 12)[0]
        sample_enc = struct.unpack_from('<B', raw_header, 14)[0]

        if sample_enc != 1:
            raise ValueError(f"Unsupported sample encoding: {sample_enc}")

        print(f"TRS header: {n_traces} traces, {n_samples} samples, "
              f"{crypto_len} bytes crypto data, float32 encoding")

        plaintexts = np.zeros((n_traces, crypto_len), dtype=np.uint8)
        traces = np.zeros((n_traces, n_samples), dtype=np.float32)

        sample_bytes = n_samples * 4
        for i in range(n_traces):
            crypto_data = f.read(crypto_len)
            plaintexts[i] = np.frombuffer(crypto_data, dtype=np.uint8)
            trace_data = f.read(sample_bytes)
            traces[i] = np.frombuffer(trace_data, dtype='<f4')

    return traces, plaintexts


# ── Step 2: Low-pass filter to remove clock harmonics ──────────────────────

def filter_traces(traces, cutoff_wn=0.25, order=5):
    """
    Apply a low-pass Butterworth filter to remove high-frequency clock
    harmonics. The cutoff is specified as a fraction of Nyquist frequency.

    The device clock creates harmonics at ~0.4, 0.6, 0.8 Nyquist.
    A cutoff at 0.25 Nyquist preserves the leakage bandwidth while
    suppressing all clock components.
    """
    sos = butter(order, cutoff_wn, btype='low', output='sos')
    filtered = sosfiltfilt(sos, traces, axis=1).astype(np.float32)
    return filtered


# ── Step 3: Two-phase trace alignment ──────────────────────────────────────

def align_traces(traces, trigger_search_start=10, trigger_search_end=180,
                 trigger_canonical=80):
    """
    Two-phase alignment:
      Phase 1: Rough alignment via trigger pulse detection (argmax).
               The trigger is the dominant peak in the early part of the
               filtered trace. After this, residual jitter is small.
      Phase 2: Fine alignment via cross-correlation on a body region
               containing consistent leakage features. Uses scipy.signal
               correlate to find sub-sample-precise shifts.
    """
    n_traces, n_samples = traces.shape

    # Phase 1: Rough alignment via trigger pulse argmax
    print("  Phase 1: Trigger-based rough alignment...")
    rough = np.zeros_like(traces)
    for i in range(n_traces):
        search_region = traces[i, trigger_search_start:trigger_search_end]
        trigger_pos = int(np.argmax(search_region)) + trigger_search_start
        shift = trigger_pos - trigger_canonical

        if shift > 0:
            rough[i, :n_samples - shift] = traces[i, shift:]
        elif shift < 0:
            s = -shift
            rough[i, s:] = traces[i, :n_samples - s]
        else:
            rough[i] = traces[i]

    # Phase 2: Cross-correlation refinement on a body region
    # After rough alignment, residual jitter is small (~±5 samples)
    # Use a region containing the first few operations for a stable reference
    print("  Phase 2: Cross-correlation refinement...")
    refine_start = 200
    refine_end = 550
    max_fine_shift = 15

    ref_pattern = np.mean(rough[:500], axis=0)[refine_start:refine_end]
    ref_len = refine_end - refine_start

    aligned = np.zeros_like(rough)
    lo = max(0, refine_start - max_fine_shift)
    hi = min(n_samples, refine_end + max_fine_shift)

    for i in range(n_traces):
        segment = rough[i, lo:hi]
        corr = correlate(segment, ref_pattern, mode='valid')
        best_pos = int(np.argmax(corr))
        actual_start = lo + best_pos
        shift = actual_start - refine_start

        if shift > 0:
            aligned[i, :n_samples - shift] = rough[i, shift:]
        elif shift < 0:
            s = -shift
            aligned[i, s:] = rough[i, :n_samples - s]
        else:
            aligned[i] = rough[i]

    return aligned


# ── Step 4: CPA with AES S-box Hamming weight model ───────────────────────

def cpa_byte(traces_region, pt_col):
    """
    Run Correlation Power Analysis for one key byte.

    Leakage model: HW(Sbox(plaintext[i] XOR key_guess))

    The AES S-box is non-linear, making the SubBytes output the strongest
    distinguisher for CPA (compared to targeting the linear AddRoundKey).

    Returns (best_guess, max_correlation).
    """
    n = traces_region.shape[0]
    guesses = np.arange(256, dtype=np.int32)

    # Compute hypothetical intermediates for all (trace, guess) pairs
    xor_vals = pt_col[:, None].astype(np.int32) ^ guesses[None, :]
    sbox_out = SBOX[xor_vals.astype(np.uint8)]
    H = HW_TABLE[sbox_out]

    # Pearson correlation
    t_mean = np.mean(traces_region, axis=0)
    h_mean = np.mean(H, axis=0)
    t_std = np.std(traces_region, axis=0, ddof=1)
    h_std = np.std(H, axis=0, ddof=1)

    t_std[t_std == 0] = 1.0
    h_std[h_std == 0] = 1.0

    corr = ((traces_region.T @ H) - n * t_mean[:, None] * h_mean[None, :]) / \
           ((n - 1) * t_std[:, None] * h_std[None, :])

    # Use positive correlation: power consumption is proportional to HW
    max_corr_per_guess = np.max(corr, axis=0)
    best_guess = int(np.argmax(max_corr_per_guess))
    return best_guess, float(max_corr_per_guess[best_guess])


# ── Main attack ────────────────────────────────────────────────────────────

def main():
    print("=== AES-128 CPA Key Recovery ===\n")

    # Step 1: Parse TRS-lite format
    print("[1] Parsing TRS-lite trace file...")
    traces, plaintexts = parse_trs('/app/traces.trs')
    n_traces, n_samples = traces.shape
    print(f"    Loaded {n_traces} traces, {n_samples} samples each\n")

    # Step 2: Low-pass filter to remove clock harmonics
    print("[2] Filtering clock harmonics (low-pass Butterworth, Wn=0.25)...")
    traces = filter_traces(traces, cutoff_wn=0.25, order=5)
    print("    Filtering complete\n")

    # Step 3: Two-phase alignment
    print("[3] Aligning traces...")
    traces = align_traces(traces)
    print("    Alignment complete\n")

    # Step 4: CPA for all 16 key bytes
    print("[4] Running CPA (AES S-box HW model)...")
    key = [0] * 16

    # Operation regions (after alignment, offsets are near canonical positions)
    # Windows are 120 samples wide, centered on expected SubBytes leakage points
    op_regions = [
        (200, 320), (415, 535), (610, 730), (825, 945),
        (1020, 1140), (1235, 1355), (1430, 1550), (1645, 1765),
        (1860, 1980), (2055, 2175), (2270, 2390), (2465, 2585),
        (2680, 2800), (2875, 2995), (3090, 3210), (3300, 3420)
    ]

    for byte_idx in range(16):
        lo, hi = op_regions[byte_idx]
        lo = max(0, lo)
        hi = min(n_samples, hi)
        region = traces[:, lo:hi]
        guess, corr = cpa_byte(region, plaintexts[:, byte_idx])
        key[byte_idx] = guess
        print(f"    K[{byte_idx:2d}] = 0x{guess:02x}  (r = {corr:.4f})")

    # Step 5: Output
    key_hex = ''.join(f'{b:02x}' for b in key)
    print(f"\nRecovered key: {key_hex}")

    with open('/app/recovered_key.hex', 'w') as f:
        f.write(key_hex)

    print("Written to /app/recovered_key.hex")


if __name__ == '__main__':
    main()
