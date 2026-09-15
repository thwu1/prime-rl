#!/usr/bin/env python3
"""
TCP-AO (RFC 5925) Key Derivation and MAC Implementation.
Supports KDF_HMAC_SHA1 and KDF_AES_128_CMAC per RFC 5926,
plus MAC computation with HMAC-SHA-1-96 and AES-128-CMAC-96.
"""

import hmac
import hashlib
import struct
import socket


# ===========================================================
# AES-CMAC implementation per RFC 4493
# ===========================================================

def _aes_encrypt(key, data):
    """AES-128 ECB encrypt a single 16-byte block."""
    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(data)


def _xor_bytes(a, b):
    """XOR two byte strings of equal length."""
    return bytes(x ^ y for x, y in zip(a, b))


def _left_shift_one(data):
    """Left-shift a 16-byte string by 1 bit."""
    shifted = bytearray(16)
    overflow = 0
    for i in range(15, -1, -1):
        shifted[i] = ((data[i] << 1) & 0xFF) | overflow
        overflow = 1 if (data[i] & 0x80) else 0
    return bytes(shifted)


_CONST_ZERO = b'\x00' * 16
_CONST_RB = b'\x00' * 15 + b'\x87'


def _generate_cmac_subkeys(key):
    """Generate CMAC subkeys K1 and K2 per RFC 4493 Section 2.3."""
    L = _aes_encrypt(key, _CONST_ZERO)
    if (L[0] & 0x80) == 0:
        K1 = _left_shift_one(L)
    else:
        K1 = _xor_bytes(_left_shift_one(L), _CONST_RB)
    if (K1[0] & 0x80) == 0:
        K2 = _left_shift_one(K1)
    else:
        K2 = _xor_bytes(_left_shift_one(K1), _CONST_RB)
    return K1, K2


def aes_128_cmac(key, message):
    """Compute AES-128-CMAC per RFC 4493."""
    assert len(key) == 16, f"AES-CMAC key must be 16 bytes, got {len(key)}"
    K1, K2 = _generate_cmac_subkeys(key)
    n = max(1, (len(message) + 15) // 16)
    if len(message) > 0 and len(message) % 16 == 0:
        complete = True
    else:
        complete = False
    if complete:
        M_last = _xor_bytes(message[(n - 1) * 16 : n * 16], K1)
    else:
        remaining = message[(n - 1) * 16 :]
        padded = remaining + b'\x80' + b'\x00' * (15 - len(remaining))
        M_last = _xor_bytes(padded, K2)
    X = _CONST_ZERO
    for i in range(n - 1):
        Y = _xor_bytes(X, message[i * 16 : (i + 1) * 16])
        X = _aes_encrypt(key, Y)
    Y = _xor_bytes(X, M_last)
    return _aes_encrypt(key, Y)


# ===========================================================
# KDF per RFC 5926 Section 3.1.1 (NIST SP 800-108 counter mode)
# ===========================================================

KDF_LABEL = b"TCP-AO\x00"


def _encode_output_length(length_bits):
    """Encode output length in bits as 2-byte value for KDF input."""
    return struct.pack('<H', length_bits)


def kdf_hmac_sha1(master_key, context, output_length_bits=160):
    """KDF_HMAC_SHA1 per RFC 5926 Section 3.1.1.1."""
    output_len_encoded = _encode_output_length(output_length_bits)
    result = b""
    prf_output_bits = 160
    iterations = (output_length_bits + prf_output_bits - 1) // prf_output_bits
    for i in range(iterations):
        input_block = bytes([i]) + KDF_LABEL + context + output_len_encoded
        prf_output = hmac.new(master_key, input_block, hashlib.sha1).digest()
        result += prf_output
    return result[:output_length_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_length_bits=128):
    """KDF_AES_128_CMAC per RFC 5926 Section 3.1.1.2."""
    if len(master_key) == 16:
        K = master_key
    else:
        K = master_key.ljust(16, b'\x00')
    output_len_encoded = _encode_output_length(output_length_bits)
    result = b""
    prf_output_bits = 128
    iterations = (output_length_bits + prf_output_bits - 1) // prf_output_bits
    for i in range(iterations):
        input_block = bytes([i]) + KDF_LABEL + context + output_len_encoded
        prf_output = aes_128_cmac(K, input_block)
        result += prf_output
    return result[:output_length_bits // 8]


# ===========================================================
# Traffic Key Derivation per RFC 5925 Section 5.2
# ===========================================================

def ip_to_bytes(ip_str):
    """Convert an IP address string to bytes."""
    if ':' in ip_str:
        return socket.inet_pton(socket.AF_INET6, ip_str)
    return socket.inet_pton(socket.AF_INET, ip_str)


def derive_traffic_key(kdf_alg, master_key, src_ip, dst_ip,
                       src_port, dst_port, src_isn, dst_isn):
    """Derive a TCP-AO traffic key from connection parameters."""
    context = (ip_to_bytes(src_ip) + ip_to_bytes(dst_ip) +
               struct.pack('!HH', src_port, dst_port) +
               struct.pack('!II', src_isn, dst_isn))
    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, context)
    elif kdf_alg == "AES-128-CMAC":
        return kdf_aes_128_cmac(master_key, context)
    raise ValueError(f"Unknown KDF algorithm: {kdf_alg}")


# ===========================================================
# MAC Computation per RFC 5925 Section 5.1
# ===========================================================

def compute_mac(mac_alg, traffic_key, message):
    """Compute a 96-bit truncated TCP-AO MAC."""
    if mac_alg == "HMAC-SHA-1-96":
        return hmac.new(traffic_key, message, hashlib.sha1).digest()[:12]
    elif mac_alg == "AES-128-CMAC-96":
        return aes_128_cmac(traffic_key, message)[:12]
    raise ValueError(f"Unknown MAC algorithm: {mac_alg}")
