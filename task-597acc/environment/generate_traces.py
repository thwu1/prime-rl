#!/usr/bin/env python3
"""Generate AES-128 power traces in TRS-lite binary format for CPA challenge.

Simulates a side-channel-vulnerable AES-128 implementation with:
- SubBytes (S-box) output leakage (primary attack target)
- AddRoundKey output leakage (weaker, creates confounding ghost peaks)
- Strong clock harmonics with per-trace amplitude variation
- Large inter-trace clock jitter requiring cross-correlation alignment
- Per-operation timing jitter
- Gaussian measurement noise and low-frequency drift
"""

import numpy as np
import struct
import hashlib
import os

np.random.seed(20250612)

# AES S-box lookup table
SBOX = [
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
]

# Secret 16-byte AES key
KEY = bytes([0xE7, 0x3A, 0x9B, 0x14, 0xD5, 0x62, 0xF8, 0x07,
             0x4C, 0xB1, 0x6E, 0x23, 0xA9, 0x85, 0xD0, 0x3F])

# Trace parameters
N_TRACES = 5000
N_SAMPLES = 4000
CRYPTO_DATA_LEN = 16  # 16-byte plaintext per trace

# Noise and jitter
NOISE_SIGMA = 1.5
GLOBAL_JITTER = 40       # +/- samples (inter-trace clock jitter)
LOCAL_JITTER = 3          # +/- samples (per-operation timing jitter)

# Trigger pulse
TRIGGER_POS = 80          # canonical position
TRIGGER_AMP = 8.0
TRIGGER_SIGMA = 5.0       # broad trigger (hard to pinpoint precisely)

# SubBytes operation offsets (non-uniform spacing, realistic)
SBOX_OFFSETS = [250, 465, 660, 875, 1070, 1285, 1480, 1695,
                1910, 2105, 2320, 2515, 2730, 2925, 3140, 3350]

# AddRoundKey leakage occurs ~45 samples before SubBytes
ARK_DELTA = 45

# Leakage strength
SBOX_LEAK_SCALE = 0.30    # S-box output leakage (primary)
ARK_LEAK_SCALE = 0.10     # AddRoundKey leakage (confounding ghost peaks)
LEAK_PULSE_SIGMA = 1.8    # Gaussian pulse width for leakage

# Clock harmonics (high-frequency, period 5/3.3/2.5 samples)
CLOCK_FREQS = [800, 1200, 1600]   # cycles per trace
CLOCK_AMPS = [5.0, 3.0, 2.0]     # amplitudes (dominate the trace)


def hw(x):
    """Hamming weight of a byte."""
    return bin(x & 0xFF).count('1')


def main():
    os.makedirs('/app', exist_ok=True)

    # Pre-compute pulse shape
    pulse_deltas = np.arange(-6, 7)
    pulse_weights = np.exp(-0.5 * (pulse_deltas / LEAK_PULSE_SIGMA) ** 2)

    # Trigger pulse shape (broader)
    trig_deltas = np.arange(-15, 16)
    trig_weights = TRIGGER_AMP * np.exp(-0.5 * (trig_deltas / TRIGGER_SIGMA) ** 2)

    # Time axis (normalized 0..1)
    t = np.linspace(0, 1, N_SAMPLES)

    # Pre-compute clock basis functions
    clock_basis = []
    for freq in CLOCK_FREQS:
        clock_basis.append(np.sin(2 * np.pi * freq * t))

    # Generate random plaintexts
    plaintexts = np.random.randint(0, 256, size=(N_TRACES, CRYPTO_DATA_LEN), dtype=np.uint8)

    # Write TRS-lite file
    with open('/app/traces.trs', 'wb') as f:
        # Header (32 bytes)
        header = struct.pack('<4sIIHB',
                             b'TRS\x01',        # magic
                             N_TRACES,           # num traces
                             N_SAMPLES,          # samples per trace
                             CRYPTO_DATA_LEN,    # crypto data length
                             1)                  # sample encoding: 1=float32
        header += b'\x00' * (32 - len(header))   # pad to 32 bytes
        f.write(header)

        for i in range(N_TRACES):
            trace = np.zeros(N_SAMPLES, dtype=np.float64)

            # Clock harmonics with per-trace amplitude variation
            clock_amp_var = np.random.uniform(0.6, 1.4)
            for basis, amp in zip(clock_basis, CLOCK_AMPS):
                trace += clock_amp_var * amp * basis

            # Global jitter (shifts all operations in this trace)
            g_jitter = np.random.randint(-GLOBAL_JITTER, GLOBAL_JITTER + 1)

            # Trigger pulse
            trig_pos = TRIGGER_POS + g_jitter
            for d_idx, delta in enumerate(trig_deltas):
                p = trig_pos + delta
                if 0 <= p < N_SAMPLES:
                    trace[p] += trig_weights[d_idx]

            # Leakage from 16 first-round AES operations
            for op in range(16):
                pt_byte = int(plaintexts[i, op])
                key_byte = KEY[op]

                # AddRoundKey intermediate: pt XOR key
                ark_val = pt_byte ^ key_byte
                ark_hw = hw(ark_val)

                # SubBytes intermediate: Sbox(pt XOR key)
                sbox_val = SBOX[ark_val]
                sbox_hw = hw(sbox_val)

                # Per-operation local jitter
                l_jitter_ark = np.random.randint(-LOCAL_JITTER, LOCAL_JITTER + 1)
                l_jitter_sbox = np.random.randint(-LOCAL_JITTER, LOCAL_JITTER + 1)

                # AddRoundKey leakage (weaker, confounding)
                ark_pos = SBOX_OFFSETS[op] - ARK_DELTA + g_jitter + l_jitter_ark
                for d_idx, delta in enumerate(pulse_deltas):
                    p = ark_pos + delta
                    if 0 <= p < N_SAMPLES:
                        trace[p] += ark_hw * ARK_LEAK_SCALE * pulse_weights[d_idx]

                # SubBytes leakage (primary target)
                sbox_pos = SBOX_OFFSETS[op] + g_jitter + l_jitter_sbox
                for d_idx, delta in enumerate(pulse_deltas):
                    p = sbox_pos + delta
                    if 0 <= p < N_SAMPLES:
                        trace[p] += sbox_hw * SBOX_LEAK_SCALE * pulse_weights[d_idx]

            # Gaussian measurement noise
            trace += np.random.normal(0, NOISE_SIGMA, N_SAMPLES)

            # Low-frequency drift (per-trace random)
            drift_freq = np.random.uniform(0.3, 1.5)
            drift_phase = np.random.uniform(0, 2 * np.pi)
            trace += 0.4 * np.sin(2 * np.pi * drift_freq * t + drift_phase)

            # Write per-trace record: crypto_data + trace_data
            f.write(plaintexts[i].tobytes())
            f.write(trace.astype(np.float32).tobytes())

            if (i + 1) % 1000 == 0:
                print(f"Generated {i + 1}/{N_TRACES} traces")

    # Write key hash for verification
    key_hash = hashlib.sha256(KEY).hexdigest()
    with open('/tmp/key_hash.txt', 'w') as fh:
        fh.write(key_hash)

    print(f"Generated {N_TRACES} traces, {N_SAMPLES} samples each")
    print(f"TRS file: /app/traces.trs")
    print(f"Key SHA-256: {key_hash}")


if __name__ == '__main__':
    main()
