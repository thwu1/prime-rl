#!/usr/bin/env python3
"""XXTEA-XOR Device Simulator - Power Analysis Capture Tool.

Simulates an embedded encryption device and captures power consumption
traces during encryption operations. Output is in HDF5 format.
"""

import argparse
import sys
import struct
import numpy as np
import h5py

NUM_SAMPLES = 4000
FIRST_OP_SAMPLE = 150
OP_SPACING = 237
NOISE_STD = 0.06
GLOBAL_JITTER_MAX = 15
LOCAL_JITTER_MAX = 10
PEAK_WIDTH = 15
DELTA = 0x9e3779b9
MASK32 = 0xFFFFFFFF


def _load_key():
    with open('/app/.device_state', 'rb') as f:
        data = f.read()
    if data[:4] != b'DVSM':
        raise RuntimeError("Invalid device state file")
    xor_mask = bytes([0x55] * 16)
    encoded = data[4:20]
    return bytes(a ^ b for a, b in zip(encoded, xor_mask))


def _xxtea_encrypt(v, key):
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
                (((z >> 5) ^ ((y << 2) & MASK32)) +
                 ((y >> 3) ^ ((z << 4) & MASK32)))
                ^ ((s ^ y) + (key[(p & 3) ^ e] ^ z))
            )) & MASK32
            z = v[p]
        y = v[0]
        v[n - 1] = (v[n - 1] + (
            (((z >> 5) ^ ((y << 2) & MASK32)) +
             ((y >> 3) ^ ((z << 4) & MASK32)))
            ^ ((s ^ y) + (key[((n - 1) & 3) ^ e] ^ z))
        )) & MASK32
        z = v[n - 1]
    return v


def _simulate_trace(plaintext, key):
    data = bytearray(plaintext)
    trace = np.random.normal(0, NOISE_STD, NUM_SAMPLES)
    global_jitter = np.random.randint(-GLOBAL_JITTER_MAX, GLOBAL_JITTER_MAX + 1)
    for i in range(16):
        intermediate = data[i % 8] ^ key[i]
        hw = bin(intermediate).count('1')
        local_jitter = np.random.randint(-LOCAL_JITTER_MAX, LOCAL_JITTER_MAX + 1)
        center = FIRST_OP_SAMPLE + i * OP_SPACING + global_jitter + local_jitter
        if 0 <= center < NUM_SAMPLES:
            x = np.arange(NUM_SAMPLES) - center
            trace += (hw / 8.0) * 0.5 * np.exp(-x**2 / (2 * PEAK_WIDTH**2))
        if i < 8:
            data[i] = intermediate & 0xFF
    return trace


def _xor_preprocess(data, key):
    result = bytearray(data)
    for i in range(16):
        result[i % len(result)] ^= key[i]
    return bytes(result)


def cmd_info(args):
    print("=== Device Information ===")
    print("Model:     XXTEA-XOR Encryption Module")
    print("Firmware:  v2.1.0")
    print("Input:     8-byte plaintext block")
    print("Output:    8-byte ciphertext block")
    print("Key size:  16 bytes (128-bit)")
    print()
    print("=== Trace Capture Parameters ===")
    print("Samples per trace: %d" % NUM_SAMPLES)
    print("Sample rate:       10000 Hz")
    print("ADC resolution:    12 bits")
    print("Analog gain:       20x")
    print()
    print("=== Available Commands ===")
    print("  info     - Display device and capture parameters")
    print("  capture  - Capture single trace with specified plaintext")
    print("  batch    - Capture multiple traces with random plaintexts")
    print()
    print("All output is in HDF5 format (.h5)")


def cmd_capture(args):
    key = _load_key()
    try:
        pt = bytes.fromhex(args.plaintext)
    except ValueError:
        print("Error: plaintext must be a valid hex string", file=sys.stderr)
        sys.exit(1)
    if len(pt) != 8:
        print("Error: plaintext must be exactly 8 bytes (16 hex chars)",
              file=sys.stderr)
        sys.exit(1)

    trace = _simulate_trace(pt, key)
    preprocessed = _xor_preprocess(pt, key)
    words = [int.from_bytes(preprocessed[i:i+4], 'little')
             for i in range(0, 8, 4)]
    key_words = [int.from_bytes(key[i:i+4], 'little') for i in range(0, 16, 4)]
    ct_words = _xxtea_encrypt(words, key_words)

    with h5py.File(args.output, 'w') as f:
        f.create_dataset('power_trace', data=trace)
        f.create_dataset('plaintext',
                         data=np.frombuffer(pt, dtype=np.uint8))
        ct_bytes = b''.join(int(w).to_bytes(4, 'little') for w in ct_words)
        f.create_dataset('ciphertext',
                         data=np.frombuffer(ct_bytes, dtype=np.uint8))
        f.attrs['samples'] = NUM_SAMPLES
        f.attrs['sample_rate_hz'] = 10000

    print("Trace captured to %s (%d samples)" % (args.output, NUM_SAMPLES))


def cmd_batch(args):
    key = _load_key()
    count = args.count
    if count < 1 or count > 10000:
        print("Error: count must be between 1 and 10000", file=sys.stderr)
        sys.exit(1)

    traces = np.zeros((count, NUM_SAMPLES))
    plaintexts = np.zeros((count, 8), dtype=np.uint8)

    for i in range(count):
        pt = np.random.randint(0, 256, 8, dtype=np.uint8)
        plaintexts[i] = pt
        traces[i] = _simulate_trace(pt.tobytes(), key)
        if (i + 1) % 500 == 0:
            print("  Captured %d/%d traces..." % (i + 1, count))

    with h5py.File(args.output, 'w') as f:
        session = f.create_group('session_info')
        session.attrs['device_model'] = 'XXTEA-XOR-v2'
        session.attrs['firmware_version'] = '2.1.0'

        acq = f.create_group('acquisition')
        acq.attrs['sample_rate_hz'] = 10000
        acq.attrs['samples_per_trace'] = NUM_SAMPLES

        data_grp = f.create_group('measurements')
        data_grp.create_dataset('power_traces', data=traces,
                                compression='gzip')
        stim = data_grp.create_group('stimulus')
        stim.create_dataset('plaintext_inputs', data=plaintexts)
        stim.attrs['encoding'] = 'raw_bytes'
        stim.attrs['block_size_bytes'] = 8

    print("Batch capture complete: %d traces saved to %s" %
          (count, args.output))


def main():
    parser = argparse.ArgumentParser(
        description='XXTEA-XOR Device Simulator - Power Analysis Capture Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest='command', help='Available commands')

    sub.add_parser('info', help='Display device and capture parameters')

    cap = sub.add_parser('capture',
                         help='Capture single encryption power trace')
    cap.add_argument('--plaintext', required=True,
                     help='8-byte plaintext as hex (e.g. 0102030405060708)')
    cap.add_argument('--output', required=True,
                     help='Output HDF5 file path')

    bat = sub.add_parser('batch',
                         help='Batch capture with random plaintexts')
    bat.add_argument('--count', type=int, required=True,
                     help='Number of traces to capture')
    bat.add_argument('--output', required=True,
                     help='Output HDF5 file path')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'info':
        cmd_info(args)
    elif args.command == 'capture':
        cmd_capture(args)
    elif args.command == 'batch':
        cmd_batch(args)


if __name__ == '__main__':
    main()
