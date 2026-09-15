#!/usr/bin/env python3
"""Generate simulated power trace data in HDF5 format during Docker build.

This script runs during Docker build to create deterministic trace data.
It is NOT included in the final image (multi-stage build).
"""

import numpy as np
import h5py
import os
DELTA = 0x9e3779b9
MASK32 = 0xFFFFFFFF

KEY_HEX = "4a7b2c9d1e5f8a3bc6d7e8f90a1b2c3d"
KEY = bytes.fromhex(KEY_HEX)
FLAG = "esc{cpa_trac3_al1gnm3nt}"

NUM_TRACES = 3000
NUM_SAMPLES = 4000
FIRST_OP_SAMPLE = 150
OP_SPACING = 237
NOISE_STD = 0.06
GLOBAL_JITTER_MAX = 15
LOCAL_JITTER_MAX = 10
PEAK_SIGMA = 4.0
PEAK_AMP = 0.05


def xxtea_encrypt(v, key):
    v = list(v)
    n = len(v)
    if n <= 1:
        return v
    rounds = 6 + 52 // n
    s = 0
    z = v[n - 1]
    for _ in range(rounds):
        s = (s + DELTA) & MASK32
        e = (s >> 2) & 3
        for p in range(n - 1):
            y = v[p + 1]
            v[p] = (v[p] + (
                (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
                ^ ((s ^ y) + (key[(p & 3) ^ e] ^ z))
            )) & MASK32
            z = v[p]
        y = v[0]
        v[n - 1] = (v[n - 1] + (
            (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
            ^ ((s ^ y) + (key[((n - 1) & 3) ^ e] ^ z))
        )) & MASK32
        z = v[n - 1]
    return v


def xxtea_decrypt(v, key):
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
            v[p] = (v[p] - (
                (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
                ^ ((s ^ y) + (key[(p & 3) ^ e] ^ z))
            )) & MASK32
            y = v[p]
        z = v[n - 1]
        v[0] = (v[0] - (
            (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
            ^ ((s ^ y) + (key[0 ^ e] ^ z))
        )) & MASK32
        y = v[0]
        s = (s - DELTA) & MASK32
    return v


def xor_preprocess(data, key):
    result = bytearray(data)
    for i in range(16):
        result[i % len(result)] ^= key[i]
    return bytes(result)


def reverse_xor_preprocess(data, key):
    result = bytearray(data)
    for i in range(15, -1, -1):
        result[i % len(result)] ^= key[i]
    return bytes(result)


def simulate_trace(plaintext, key, rng):
    data = bytearray(plaintext)
    trace = rng.normal(0, NOISE_STD, NUM_SAMPLES).astype(np.float32)
    global_jitter = int(rng.integers(-GLOBAL_JITTER_MAX, GLOBAL_JITTER_MAX + 1))

    for i in range(16):
        intermediate = data[i % 8] ^ key[i]
        hw = bin(intermediate).count('1')
        local_jitter = int(rng.integers(-LOCAL_JITTER_MAX, LOCAL_JITTER_MAX + 1))
        center = FIRST_OP_SAMPLE + i * OP_SPACING + global_jitter + local_jitter

        if 0 <= center < NUM_SAMPLES:
            lo = max(0, center - 25)
            hi = min(NUM_SAMPLES, center + 26)
            x = np.arange(lo, hi)
            peak = PEAK_AMP * hw * np.exp(-0.5 * ((x - center) / PEAK_SIGMA) ** 2)
            trace[lo:hi] += peak

        if i < 8:
            data[i] = intermediate & 0xFF

    return trace


def main():
    rng = np.random.default_rng(20250602)

    os.makedirs('/app/captures', exist_ok=True)

    # Generate traces
    traces = np.zeros((NUM_TRACES, NUM_SAMPLES), dtype=np.float32)
    plaintexts = rng.integers(0, 256, size=(NUM_TRACES, 8), dtype=np.uint8)

    for i in range(NUM_TRACES):
        traces[i] = simulate_trace(plaintexts[i].tobytes(), KEY, rng)

    # Save traces in HDF5 format with nested group structure
    with h5py.File('/app/captures/traces.h5', 'w') as f:
        session = f.create_group('session_info')
        session.attrs['device_model'] = 'XXTEA-XOR-v2'
        session.attrs['firmware_version'] = '2.1.0'
        session.attrs['capture_date'] = '2025-03-15'
        session.attrs['notes'] = 'Batch capture for security audit'

        acq = f.create_group('acquisition')
        acq.attrs['sample_rate_hz'] = 10000
        acq.attrs['samples_per_trace'] = NUM_SAMPLES
        acq.attrs['trigger_mode'] = 'rising_edge'
        acq.attrs['adc_resolution_bits'] = 12
        acq.attrs['analog_gain'] = 20.0

        data_grp = f.create_group('measurements')
        data_grp.create_dataset('power_traces', data=traces,
                                compression='gzip', compression_opts=4)

        stim = data_grp.create_group('stimulus')
        stim.create_dataset('plaintext_inputs', data=plaintexts)
        stim.attrs['encoding'] = 'raw_bytes'
        stim.attrs['block_size_bytes'] = 8

    # Encrypt the flag
    flag_bytes = FLAG.encode('ascii')
    if len(flag_bytes) % 8 != 0:
        flag_bytes += b'\x00' * (8 - len(flag_bytes) % 8)
    preprocessed = xor_preprocess(flag_bytes, KEY)
    words = [int.from_bytes(preprocessed[i:i+4], 'little')
             for i in range(0, len(preprocessed), 4)]
    key_words = [int.from_bytes(KEY[i:i+4], 'little') for i in range(0, 16, 4)]
    ct_words = xxtea_encrypt(words, key_words)

    # Save intercepted message in HDF5
    with h5py.File('/app/captures/intercept.h5', 'w') as f:
        meta = f.create_group('metadata')
        meta.attrs['source'] = 'intercepted_communication'
        meta.attrs['timestamp'] = '2025-03-16T14:22:00Z'
        meta.attrs['protocol'] = 'encrypted_block_transfer'

        payload = f.create_group('payload')
        payload.create_dataset('encrypted_blocks',
                               data=np.array(ct_words, dtype=np.uint32))
        payload.attrs['block_cipher'] = 'xxtea_variant'
        payload.attrs['word_size_bits'] = 32
        payload.attrs['byte_order'] = 'little_endian'

    # Verify round-trip
    dec_words = xxtea_decrypt(ct_words, key_words)
    dec_bytes = b''.join(int(w).to_bytes(4, 'little') for w in dec_words)
    dec_plain = reverse_xor_preprocess(dec_bytes, KEY)
    recovered = dec_plain.rstrip(b'\x00').decode('ascii')
    assert recovered == FLAG, f"Flag verification failed: {recovered}"

    print(f"Generated {NUM_TRACES} traces in HDF5 format")
    print(f"Flag verified: {recovered}")


if __name__ == '__main__':
    main()
