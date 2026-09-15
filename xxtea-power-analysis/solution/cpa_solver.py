#!/usr/bin/env python3
"""Correlation Power Analysis solver for XXTEA side-channel traces.

Reads capture metadata from SQLite, parses custom SCTF binary trace format,
performs CPA with SAD-based trace alignment, recovers the 128-bit key,
and decrypts the encrypted report using openssl.

"""

import numpy as np
import struct
import subprocess
import sqlite3
import sys

# ── Hamming-weight lookup table ──
HW_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.float64)


# ── SQLite metadata queries ──
def query_db(db_path):
    """Read capture configuration and batch index from SQLite."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    config = dict(c.execute('SELECT key, value FROM config').fetchall())
    batches = c.execute(
        'SELECT batch_id, file_path, num_traces, start_index '
        'FROM batches ORDER BY batch_id'
    ).fetchall()
    conn.close()
    return config, batches


# ── Custom binary format parser ──
def parse_batch(filepath, n_samples):
    """Parse an SCTF binary batch file.

    Format (from binary_format table):
      Header (32 bytes): magic(4) + version(2) + num_traces(4)
                        + samples_per_trace(4) + data_type(2) + reserved(16)
      Per-trace record:  plaintext(16) + ciphertext(16) + float32[N] samples
    """
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        assert magic == b'SCTF', f"Bad magic: {magic}"
        version = struct.unpack('<H', f.read(2))[0]
        n_traces = struct.unpack('<I', f.read(4))[0]
        spt = struct.unpack('<I', f.read(4))[0]
        dtype_code = struct.unpack('<H', f.read(2))[0]
        _reserved = f.read(16)  # 16 bytes reserved

        assert spt == n_samples, f"Mismatch: header says {spt}, expected {n_samples}"
        assert dtype_code == 1, f"Unknown data type: {dtype_code}"

        pts = np.zeros((n_traces, 16), dtype=np.uint8)
        cts = np.zeros((n_traces, 16), dtype=np.uint8)
        traces = np.zeros((n_traces, n_samples), dtype=np.float32)

        for i in range(n_traces):
            pts[i] = np.frombuffer(f.read(16), dtype=np.uint8)
            cts[i] = np.frombuffer(f.read(16), dtype=np.uint8)
            traces[i] = np.frombuffer(f.read(n_samples * 4), dtype=np.float32)

    return traces, pts, cts


# ── Trace alignment (Sum-of-Absolute-Differences) ──
def _apply_shift(trace, shift):
    n = len(trace)
    out = np.empty_like(trace)
    if shift > 0:
        out[:-shift] = trace[shift:]
        out[-shift:] = trace[-1]
    elif shift < 0:
        s = -shift
        out[s:] = trace[:-s]
        out[:s] = trace[0]
    else:
        out[:] = trace
    return out


def align_traces(traces, max_shift=20, n_iters=2):
    """Align traces using iterative SAD minimisation."""
    n_traces, n_samples = traces.shape
    aligned = np.copy(traces)
    shifts = np.zeros(n_traces, dtype=np.int32)
    a_start = max_shift + 10
    a_end = n_samples - max_shift - 10

    for it in range(n_iters):
        ref = traces[0].copy() if it == 0 else np.mean(aligned, axis=0)
        ref_seg = ref[a_start:a_end].copy()

        for t in range(n_traces):
            best_shift = 0
            best_sad = np.inf
            for s in range(-max_shift, max_shift + 1):
                seg = traces[t, a_start + s:a_end + s]
                sad = np.sum(np.abs(seg - ref_seg))
                if sad < best_sad:
                    best_sad = sad
                    best_shift = s
            shifts[t] = best_shift
            aligned[t] = _apply_shift(traces[t], best_shift)

    return aligned, shifts


# ── CPA for one key byte ──
def cpa_byte(traces, plaintexts, byte_idx):
    """Return (best_guess, max_correlation, peak_sample)."""
    n_traces, n_samples = traces.shape
    t_mean = np.mean(traces, axis=0)
    t_centered = traces - t_mean
    t_norm = np.sqrt(np.sum(t_centered ** 2, axis=0))

    best_guess = 0
    best_corr = -np.inf
    best_sample = 0

    for guess in range(256):
        h = HW_TABLE[plaintexts[:, byte_idx] ^ guess]
        h_c = h - np.mean(h)
        h_n = np.sqrt(np.sum(h_c ** 2))
        if h_n < 1e-10:
            continue
        corr = (h_c @ t_centered) / (h_n * t_norm + 1e-10)
        mc = np.max(corr)
        if mc > best_corr:
            best_corr = mc
            best_guess = guess
            best_sample = int(np.argmax(corr))

    return best_guess, best_corr, best_sample


# ── Main ──
def main():
    print("=" * 60)
    print("CPA Attack — XXTEA Power Traces (SCTF Binary Format)")
    print("=" * 60)

    # 1. Query SQLite for capture metadata
    print("\n[1] Querying capture database ...")
    config, batches = query_db('/app/capture.db')
    n_samples = int(config['samples_per_trace'])
    print(f"    samples_per_trace : {n_samples}")
    print(f"    total_traces      : {config['total_traces']}")
    print(f"    target_algorithm  : {config['target_algorithm']}")
    print(f"    key_size_bits     : {config['key_size_bits']}")
    print(f"    batch count       : {len(batches)}")

    # 2. Parse binary trace files
    print("\n[2] Parsing SCTF binary batch files ...")
    all_traces, all_pts = [], []
    for batch_id, fpath, n_tr, start_idx in batches:
        t, p, c = parse_batch(fpath, n_samples)
        all_traces.append(t)
        all_pts.append(p)
        print(f"    batch_{batch_id}: {t.shape[0]} traces from {fpath}")

    traces = np.concatenate(all_traces, axis=0).astype(np.float64)
    plaintexts = np.concatenate(all_pts, axis=0)
    print(f"    Total loaded: {traces.shape}")

    # 3. Align traces
    print("\n[3] Aligning traces (SAD, max_shift=35, 2 iters) ...")
    aligned, shifts = align_traces(traces, max_shift=35)
    print(f"    Shift range : [{shifts.min()}, {shifts.max()}]")
    print(f"    Mean |shift|: {np.mean(np.abs(shifts)):.1f}")

    # 4. CPA per key byte
    print("\n[4] Running CPA for each key byte ...")
    key_bytes = []
    for i in range(16):
        guess, corr, sample = cpa_byte(aligned, plaintexts, i)
        key_bytes.append(guess)
        print(f"    Byte {i:2d}: 0x{guess:02x}  corr={corr:.4f}  @sample={sample}")

    key_hex = ''.join(f'{b:02x}' for b in key_bytes)
    print(f"\n    Recovered key: {key_hex}")

    # 5. Write key
    with open('/app/recovered_key.hex', 'w') as f:
        f.write(key_hex + '\n')
    print("    Written to /app/recovered_key.hex")

    # 6. Verify with binary
    print("\n[5] Verifying key ...")
    result = subprocess.run(['/app/verify', key_hex],
                            capture_output=True, text=True)
    verdict = result.stdout.strip()
    print(f"    Result: {verdict}")
    if verdict != "CORRECT":
        print("FAILED — recovered key is incorrect")
        sys.exit(1)

    # 7. Decrypt encrypted report using openssl
    print("\n[6] Decrypting encrypted report with openssl ...")
    iv_hex = config['aes_report_iv']
    print(f"    AES IV from DB: {iv_hex}")
    subprocess.run([
        'openssl', 'enc', '-d', '-aes-128-cbc',
        '-K', key_hex, '-iv', iv_hex,
        '-in', '/app/encrypted_report.enc',
        '-out', '/app/decrypted_report.txt'
    ], check=True)
    print("    Written to /app/decrypted_report.txt")

    with open('/app/decrypted_report.txt', 'r') as f:
        content = f.read()
    assert 'XXTEA_CPA_VERIFIED_OK' in content, "Token not in decrypted report!"
    print("    Verification token confirmed in decrypted report")

    print("\nSUCCESS")


if __name__ == '__main__':
    main()
