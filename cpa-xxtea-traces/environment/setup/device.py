"""
Simulated Embedded Device: XXTEA cipher with XOR pre-mixing.

This module documents the simulated embedded device that performs XXTEA
encryption with a preliminary XOR mixing stage. Power traces were captured
during the XOR mixing stage and exhibit data-dependent leakage.

== Device Protocol ==

The device processes 8-byte plaintext blocks through two stages:
  1. XOR Pre-mixing: 16 sequential byte-level XOR operations using the
     16-byte key. For each operation i (0..15), the device computes:
       data[i % 8] ^= key_byte[i]
     This means each plaintext byte position is XORed TWICE: once at
     operation i, and again at operation i+8 (with a different key byte).
  2. XXTEA Encryption: The pre-mixed data is encrypted using the XXTEA
     block cipher with the same key (interpreted as 4 little-endian uint32).

== Power Leakage Model ==

During the XOR pre-mixing stage, each XOR operation produces power
consumption proportional to the Hamming weight of the intermediate result:
  Power(operation i) ~ HW(data[i % 8] ^ key_byte[i])

Note that operations 0-7 compute:
  intermediate = plaintext[i] ^ key[i]
while operations 8-15 compute:
  intermediate = (plaintext[i-8] ^ key[i-8]) ^ key[i]
because plaintext bytes have been modified by the first 8 operations.

== Trace Structure ==

  - Samples per trace: 4000
  - Number of captured traces: 3000
  - 16 operation points, approximately evenly spaced
  - First operation at approximately sample 150
  - Inter-operation delay of approximately 237 samples
  - Traces exhibit timing jitter (both global and per-operation)
  - Gaussian peak shape at each operation point

== Data Files (in /app/data/) ==

  traces.npy:     float32[3000, 4000] - captured power traces
  plaintexts.npy: uint8[3000, 8]      - corresponding 8-byte plaintexts
  ciphertext.npy: uint32[6]           - encrypted flag (24 bytes = 6 words)

== Flag Encryption ==

The flag was encrypted using the full device pipeline:
  1. XOR pre-mixing with the 16-byte key (16 sequential XOR operations)
  2. XXTEA encryption with the same key (4 little-endian uint32 words)

To recover the flag, you must:
  1. Recover the 16-byte key from trace analysis
  2. XXTEA-decrypt the ciphertext using the recovered key
  3. Reverse the XOR pre-mixing to obtain the original flag plaintext
"""

DELTA = 0x9e3779b9
MASK32 = 0xFFFFFFFF


def _mx(z, y, s, k):
    """XXTEA mixing function (MX macro)."""
    return (
        (((z >> 5) ^ ((y << 2) & MASK32)) + ((y >> 3) ^ ((z << 4) & MASK32)))
        ^ ((s ^ y) + (k ^ z))
    ) & MASK32


def xxtea_encrypt(v, key):
    """XXTEA block cipher encryption.

    Args:
        v: list of uint32 plaintext words (n >= 2)
        key: list of 4 uint32 key words
    Returns:
        list of uint32 ciphertext words
    """
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
            v[p] = (v[p] + _mx(z, y, s, key[(p & 3) ^ e])) & MASK32
            z = v[p]
        p = n - 1
        y = v[0]
        v[p] = (v[p] + _mx(z, y, s, key[(p & 3) ^ e])) & MASK32
        z = v[p]
    return v


def xxtea_decrypt(v, key):
    """XXTEA block cipher decryption.

    Args:
        v: list of uint32 ciphertext words (n >= 2)
        key: list of 4 uint32 key words
    Returns:
        list of uint32 plaintext words
    """
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


def xor_preprocess(data, key_bytes):
    """XOR pre-mixing stage (forward direction).

    Sequentially XORs data bytes with key bytes. For 8-byte data and
    16-byte key, each data byte position is XORed twice (wrapping).

    Args:
        data: bytearray of plaintext (modified in-place)
        key_bytes: bytes of length 16
    """
    for i in range(16):
        data[i % len(data)] ^= key_bytes[i]


def reverse_xor_preprocess(data, key_bytes):
    """Reverse the XOR pre-mixing stage.

    Must be applied in reverse order to undo the sequential modifications.

    Args:
        data: bytearray of pre-mixed data (modified in-place)
        key_bytes: bytes of length 16
    """
    for i in range(15, -1, -1):
        data[i % len(data)] ^= key_bytes[i]
