
"""
Verification tests for side-channel key recovery task.

Tests verify the recovered key by independently decrypting the ciphertext
and checking the result. No hardcoded keys or flags.
"""

import os
import numpy as np
import h5py

DELTA = 0x9e3779b9
MASK32 = 0xFFFFFFFF


def _mx(z, y, s, k):
    return (
        (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
        ^ ((s ^ y) + (k ^ z))
    ) & MASK32


def _xxtea_decrypt(v, key):
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
            v[p] = (v[p] - _mx(z, y, s, key[(p & 3) ^ e])) & MASK32
            y = v[p]
        z = v[n - 1]
        v[0] = (v[0] - _mx(z, y, s, key[0 ^ e])) & MASK32
        y = v[0]
        s = (s - DELTA) & MASK32
    return v


def _decrypt_flag(key_bytes, ciphertext):
    """Full decryption: XXTEA decrypt then reverse XOR preprocessing."""
    key_u32 = [
        int.from_bytes(key_bytes[i:i+4], 'little')
        for i in range(0, 16, 4)
    ]
    dec_words = _xxtea_decrypt([int(x) for x in ciphertext], key_u32)
    dec_data = bytearray(
        b''.join(int(w).to_bytes(4, 'little') for w in dec_words)
    )
    # Reverse XOR preprocessing in reverse order
    for i in range(15, -1, -1):
        dec_data[i % len(dec_data)] ^= key_bytes[i]
    return bytes(dec_data)


def test_recovered_key_file_exists():
    assert os.path.exists('/app/recovered_key.hex'), \
        "recovered_key.hex not found at /app/recovered_key.hex"


def test_flag_file_exists():
    assert os.path.exists('/app/flag.txt'), \
        "flag.txt not found at /app/flag.txt"


def test_recovered_key_format():
    with open('/app/recovered_key.hex', 'r') as f:
        key_hex = f.read().strip()
    assert len(key_hex) == 32, \
        f"Key hex string must be 32 characters, got {len(key_hex)}"
    # Verify it's valid hex
    bytes.fromhex(key_hex)


def test_key_decrypts_to_valid_flag():
    """Verify the recovered key produces a valid flag when used to decrypt."""
    with open('/app/recovered_key.hex', 'r') as f:
        key = bytes.fromhex(f.read().strip())
    assert len(key) == 16, f"Key must be 16 bytes, got {len(key)}"

    with h5py.File('/app/captures/intercept.h5', 'r') as f:
        ciphertext = f['payload/encrypted_blocks'][:]

    flag_bytes = _decrypt_flag(key, ciphertext)
    flag = flag_bytes.rstrip(b'\x00').decode('ascii', errors='replace')

    assert flag.startswith('esc{'), \
        f"Decrypted flag must start with 'esc{{', got: {flag[:20]}"
    assert flag.endswith('}'), \
        f"Decrypted flag must end with '}}', got: {flag[-20:]}"
    assert len(flag) == 24, \
        f"Decrypted flag must be 24 characters, got {len(flag)}"
    assert all(32 <= ord(c) <= 126 for c in flag), \
        "Decrypted flag contains non-printable characters"


def test_flag_file_matches_decryption():
    """Verify flag.txt is consistent with key-based decryption."""
    with open('/app/recovered_key.hex', 'r') as f:
        key = bytes.fromhex(f.read().strip())

    with h5py.File('/app/captures/intercept.h5', 'r') as f:
        ciphertext = f['payload/encrypted_blocks'][:]

    dec_bytes = _decrypt_flag(key, ciphertext).rstrip(b'\x00')
    try:
        expected_flag = dec_bytes.decode('ascii')
    except UnicodeDecodeError:
        assert False, "Decryption with recovered key produced non-ASCII output"

    with open('/app/flag.txt', 'r') as f:
        written_flag = f.read().strip()

    assert written_flag == expected_flag, \
        "flag.txt content does not match decrypted flag"


def test_key_correlates_with_traces():
    """Verify the recovered key produces meaningful correlation with traces."""
    with open('/app/recovered_key.hex', 'r') as f:
        key = bytes.fromhex(f.read().strip())

    with h5py.File('/app/captures/traces.h5', 'r') as f:
        traces = f['measurements/power_traces'][:]
        plaintexts = f['measurements/stimulus/plaintext_inputs'][:]

    # Check correlation for first key byte at approximate operation region
    pt_byte0 = plaintexts[:, 0].astype(np.int32)
    hw_values = np.array([bin(int(p) ^ key[0]).count('1') for p in pt_byte0],
                         dtype=np.float64)

    # Average power in approximate region of first operation
    center = 150
    region = traces[:, max(0, center-10):center+10]
    avg_power = np.mean(region, axis=1).astype(np.float64)

    # Pearson correlation
    hw_centered = hw_values - np.mean(hw_values)
    pow_centered = avg_power - np.mean(avg_power)
    denom = np.sqrt(np.sum(hw_centered**2) * np.sum(pow_centered**2))
    if denom > 0:
        corr = np.sum(hw_centered * pow_centered) / denom
    else:
        corr = 0.0

    assert abs(corr) > 0.05, \
        f"Key byte 0 shows no significant correlation with traces (r={corr:.4f})"
