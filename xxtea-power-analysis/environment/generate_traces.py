#!/usr/bin/env python3
"""Generate simulated power traces for XXTEA CPA side-channel attack.

Outputs traces in custom binary format (SCTF), capture metadata in SQLite,
and an AES-128-CBC encrypted report. All generation scripts are deleted
after Docker build.

"""

import numpy as np
import struct
import os
import sqlite3
import subprocess
import hashlib

# ── Secret key (128-bit / 16 bytes) ──
KEY = bytes([0x3a, 0x7f, 0x12, 0xc8, 0x5d, 0x9e, 0x41, 0xb6,
             0xe3, 0x04, 0x8a, 0xf5, 0x67, 0x2b, 0xd0, 0x9c])

# ── XXTEA ──
DELTA = 0x9e3779b9
M32 = 0xFFFFFFFF


def _mx(z, y, s, k, p, e):
    return (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^
            ((s ^ y) + (k[(p & 3) ^ e] ^ z))) & M32


def xxtea_encrypt(data, key):
    n = len(data) // 4
    v = list(struct.unpack('<' + 'I' * n, data))
    k = list(struct.unpack('<4I', key))
    rounds = 6 + 52 // n
    s = 0
    z = v[n - 1]
    for _ in range(rounds):
        s = (s + DELTA) & M32
        e = (s >> 2) & 3
        for p in range(n - 1):
            y = v[p + 1]
            v[p] = (v[p] + _mx(z, y, s, k, p, e)) & M32
            z = v[p]
        y = v[0]
        v[n - 1] = (v[n - 1] + _mx(z, y, s, k, n - 1, e)) & M32
        z = v[n - 1]
    return struct.pack('<' + 'I' * n, *v)


def hw(x):
    return bin(x & 0xFF).count('1')


def make_base_pattern(length, seed=12345):
    rng = np.random.default_rng(seed)
    raw = rng.normal(0, 1.0, length + 20)
    kernel = np.ones(11) / 11.0
    smoothed = np.convolve(raw, kernel, mode='valid')[:length]
    t = np.arange(length, dtype=np.float64)
    clock = (0.6 * np.sin(2 * np.pi * t / 25) +
             0.3 * np.sin(2 * np.pi * t / 13) +
             0.4 * np.sin(2 * np.pi * t / 80))
    return (1.5 * smoothed + clock).astype(np.float32)


def shift_array(arr, shift):
    n = len(arr)
    out = np.empty_like(arr)
    if shift > 0:
        out[shift:] = arr[:-shift]
        out[:shift] = arr[0]
    elif shift < 0:
        s = -shift
        out[:n - s] = arr[s:]
        out[n - s:] = arr[-1]
    else:
        out[:] = arr
    return out


def generate(n_traces=5000, trace_length=800, seed=42):
    rng = np.random.default_rng(seed)
    key_arr = np.frombuffer(KEY, dtype=np.uint8)

    alpha = 0.3
    noise_std = 0.5
    max_jitter = 15

    base_offsets = [40 + i * 45 for i in range(16)]
    ghost_offsets = [52, 142, 232, 322, 412, 502, 592, 682]
    spread_d = np.array([-2, -1, 0, 1, 2])
    spread_w = np.array([0.3, 0.7, 1.0, 0.7, 0.3], dtype=np.float32)

    base_pattern = make_base_pattern(trace_length)

    plaintexts = rng.integers(0, 256, (n_traces, 16), dtype=np.uint8)
    traces = np.zeros((n_traces, trace_length), dtype=np.float32)
    ciphertexts = np.zeros((n_traces, 16), dtype=np.uint8)

    for t in range(n_traces):
        trace = base_pattern.copy()
        for i in range(16):
            xv = int(plaintexts[t, i]) ^ int(key_arr[i])
            h = hw(xv)
            sig = alpha * (h / 4.0 - 1.0)
            for j in range(5):
                idx = base_offsets[i] + int(spread_d[j])
                if 0 <= idx < trace_length:
                    trace[idx] += sig * spread_w[j]

        for go in ghost_offsets:
            gj = int(rng.integers(-3, 4))
            idx = go + gj
            if 0 <= idx < trace_length:
                trace[idx] += float(rng.normal(0, alpha * 0.5))

        jitter = int(rng.integers(-max_jitter, max_jitter + 1))
        trace = shift_array(trace, jitter)
        trace = trace + rng.normal(0, noise_std, trace_length).astype(np.float32)
        traces[t] = trace

        pt = bytes(plaintexts[t])
        ct = xxtea_encrypt(pt, KEY)
        ciphertexts[t] = np.frombuffer(ct, dtype=np.uint8)

    return traces, plaintexts, ciphertexts


def write_binary_batch(filepath, traces, plaintexts, ciphertexts):
    """Write traces in SCTF custom binary format."""
    n_traces, n_samples = traces.shape
    with open(filepath, 'wb') as f:
        # 32-byte header
        f.write(b'SCTF')                            # magic (4)
        f.write(struct.pack('<H', 1))                # version (2)
        f.write(struct.pack('<I', n_traces))          # num_traces (4)
        f.write(struct.pack('<I', n_samples))         # samples_per_trace (4)
        f.write(struct.pack('<H', 1))                # data_type: 1=float32 (2)
        f.write(b'\x00' * 16)                       # reserved (16)

        for i in range(n_traces):
            f.write(bytes(plaintexts[i]))             # plaintext (16)
            f.write(bytes(ciphertexts[i]))            # ciphertext (16)
            f.write(traces[i].tobytes())              # float32 samples


def main():
    os.makedirs('/app/captures', exist_ok=True)

    print("Generating 5000 simulated power traces ...")
    traces, pts, cts = generate()

    # Write 5 binary batch files (1000 traces each)
    batch_size = 1000
    for batch_id in range(5):
        start = batch_id * batch_size
        end = start + batch_size
        filepath = f'/app/captures/batch_{batch_id}.bin'
        write_binary_batch(filepath, traces[start:end],
                           pts[start:end], cts[start:end])
        print(f"  Written {filepath} ({batch_size} traces)")

    # ── Create SQLite database ──
    db_path = '/app/capture.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    c.execute('''CREATE TABLE batches (
        batch_id INTEGER PRIMARY KEY,
        file_path TEXT,
        num_traces INTEGER,
        start_index INTEGER
    )''')

    c.execute('''CREATE TABLE binary_format (
        field_name TEXT PRIMARY KEY,
        offset_bytes INTEGER,
        size_bytes INTEGER,
        data_type TEXT,
        description TEXT
    )''')

    # Deterministic IV for the encrypted report
    iv = hashlib.sha256(b"XXTEA_CPA_IV_SEED_2025").digest()[:16]

    config_entries = [
        ('sample_rate_hz', '100000000'),
        ('voltage_range_v', '3.3'),
        ('trigger_type', 'rising_edge'),
        ('num_channels', '1'),
        ('total_traces', '5000'),
        ('samples_per_trace', '800'),
        ('capture_device', 'ChipWhisperer-Nano'),
        ('target_algorithm', 'XXTEA'),
        ('key_size_bits', '128'),
        ('aes_report_iv', iv.hex()),
        ('notes', 'Pre-encryption byte-mixing phase leaks HW. Temporal jitter present. Ghost ops at irregular intervals.'),
    ]
    c.executemany('INSERT INTO config VALUES (?, ?)', config_entries)

    for batch_id in range(5):
        c.execute('INSERT INTO batches VALUES (?, ?, ?, ?)',
                  (batch_id, f'/app/captures/batch_{batch_id}.bin',
                   1000, batch_id * 1000))

    # Binary format documentation (header offsets are absolute;
    # record offsets are relative to start of each trace record)
    format_entries = [
        ('header.magic', 0, 4, 'ascii', 'File magic bytes: "SCTF"'),
        ('header.version', 4, 2, 'uint16_le', 'Format version (currently 1)'),
        ('header.num_traces', 6, 4, 'uint32_le', 'Number of trace records in file'),
        ('header.samples_per_trace', 10, 4, 'uint32_le', 'Power samples per trace'),
        ('header.data_type', 14, 2, 'uint16_le', 'Sample type: 1=float32_le'),
        ('header.reserved', 16, 16, 'zeros', 'Reserved (zero-filled)'),
        ('record.plaintext', 0, 16, 'uint8[16]', 'Input plaintext bytes (relative to record start)'),
        ('record.ciphertext', 16, 16, 'uint8[16]', 'Output ciphertext bytes (relative to record start)'),
        ('record.samples', 32, -1, 'float32_le[]', 'Power samples array; length = samples_per_trace (relative to record start)'),
    ]
    c.executemany('INSERT INTO binary_format VALUES (?, ?, ?, ?, ?)',
                  format_entries)

    conn.commit()
    conn.close()
    print(f"  Created {db_path}")

    # ── Encrypt analysis report with AES-128-CBC ──
    report_text = (
        "SIDE-CHANNEL ANALYSIS REPORT\n"
        "============================\n"
        "Target: XXTEA Implementation on STM32F0\n"
        "Device: ChipWhisperer-Nano Capture Board\n"
        "Date: 2025-04-15\n"
        "\n"
        "VULNERABILITY CONFIRMED: Pre-encryption byte-mixing phase leaks\n"
        "Hamming weight of plaintext XOR key through power consumption.\n"
        "\n"
        "Classification: CRITICAL\n"
        "Recommendation: Implement constant-power masking countermeasures.\n"
        "\n"
        "Report ID: SCR-2025-0417-XXTEA\n"
        "Verification Token: XXTEA_CPA_VERIFIED_OK\n"
    )

    with open('/tmp/report.txt', 'w') as f:
        f.write(report_text)

    key_hex = KEY.hex()
    iv_hex = iv.hex()
    subprocess.run([
        'openssl', 'enc', '-aes-128-cbc',
        '-K', key_hex, '-iv', iv_hex,
        '-in', '/tmp/report.txt',
        '-out', '/app/encrypted_report.enc'
    ], check=True)
    os.remove('/tmp/report.txt')
    print("  Created /app/encrypted_report.enc (AES-128-CBC)")

    # ── Oracle info ──
    with open('/app/oracle_info.txt', 'w') as f:
        f.write("XXTEA Side-Channel Capture Workspace\n")
        f.write("=" * 40 + "\n\n")
        f.write("Target: XXTEA cipher (128-bit key, 16-byte blocks, little-endian uint32)\n")
        f.write("Capture device: ChipWhisperer-Nano\n\n")
        f.write("Files:\n")
        f.write("  /app/capture.db             — SQLite database (capture config + format docs)\n")
        f.write("  /app/captures/batch_*.bin   — Raw binary power trace batch files\n")
        f.write("  /app/encrypted_report.enc   — AES-128-CBC encrypted analysis report\n")
        f.write("  /app/verify <hex_key>       — Key verification binary\n\n")
        f.write("Database tables (query with sqlite3):\n")
        f.write("  config          — Capture configuration key-value pairs\n")
        f.write("  batches         — Trace batch file index (paths, counts, offsets)\n")
        f.write("  binary_format   — Schema of the .bin file structure\n\n")
        f.write("Leakage model:\n")
        f.write("  During a pre-encryption byte-mixing phase, the device processes\n")
        f.write("  each plaintext byte with the corresponding key byte. Power\n")
        f.write("  consumption at each operation correlates with the Hamming weight\n")
        f.write("  of the intermediate value.\n\n")
        f.write("Noise:\n")
        f.write("  - Additive Gaussian measurement noise\n")
        f.write("  - Temporal jitter (traces are NOT time-aligned)\n")
        f.write("  - Spurious power spikes from ghost operations\n")

    # Target ciphertext (kept for reference)
    target_pt = b"XXTEA_CPA_WIN!!!"
    target_ct = xxtea_encrypt(target_pt, KEY)
    with open('/app/target_ciphertext.hex', 'w') as f:
        f.write(target_ct.hex() + '\n')

    print("Done.")


if __name__ == '__main__':
    main()
