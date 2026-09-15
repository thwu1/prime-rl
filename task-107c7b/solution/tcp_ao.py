#!/usr/bin/env python3
"""
TCP-AO (RFC 5925/5926) Key Derivation and MAC Implementation — corrected.

"""

import hmac
import hashlib
import struct
import socket


# ==================================================================
# AES-128-CMAC per RFC 4493
# ==================================================================

def _aes_encrypt(key, data):
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(data)


def _xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _left_shift_one(data):
    out = bytearray(16)
    carry = 0
    for i in range(15, -1, -1):
        out[i] = ((data[i] << 1) & 0xFF) | carry
        carry = 1 if (data[i] & 0x80) else 0
    return bytes(out)


_ZERO_16 = b'\x00' * 16
_CONST_RB = b'\x00' * 15 + b'\x87'


def _cmac_subkeys(key):
    L = _aes_encrypt(key, _ZERO_16)
    K1 = _left_shift_one(L)
    if L[0] & 0x80:
        K1 = _xor_bytes(K1, _CONST_RB)
    K2 = _left_shift_one(K1)
    if K1[0] & 0x80:
        K2 = _xor_bytes(K2, _CONST_RB)
    return K1, K2


def aes_128_cmac(key, message):
    assert len(key) == 16
    K1, K2 = _cmac_subkeys(key)
    n = max(1, (len(message) + 15) // 16)
    complete = len(message) > 0 and len(message) % 16 == 0
    if complete:
        M_last = _xor_bytes(message[(n - 1) * 16:n * 16], K1)
    else:
        rem = message[(n - 1) * 16:]
        padded = rem + b'\x80' + b'\x00' * (15 - len(rem))
        M_last = _xor_bytes(padded, K2)
    X = _ZERO_16
    for i in range(n - 1):
        X = _aes_encrypt(key, _xor_bytes(X, message[i * 16:(i + 1) * 16]))
    return _aes_encrypt(key, _xor_bytes(X, M_last))


# ==================================================================
# KDF per RFC 5926 Section 3.1.1 (NIST SP 800-108 counter mode)
# ==================================================================

_KDF_LABEL = b"TCP-AO"


def _output_length_bytes(bits):
    return struct.pack('>H', bits)


def kdf_hmac_sha1(master_key, context, output_bits=160):
    enc_len = _output_length_bytes(output_bits)
    result = b""
    iters = (output_bits + 159) // 160
    for i in range(1, iters + 1):
        block = bytes([i]) + _KDF_LABEL + context + enc_len
        result += hmac.new(master_key, block, hashlib.sha1).digest()
    return result[:output_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_bits=128):
    if len(master_key) == 16:
        K = master_key
    else:
        K = aes_128_cmac(_ZERO_16, master_key)
    enc_len = _output_length_bytes(output_bits)
    result = b""
    iters = (output_bits + 127) // 128
    for i in range(1, iters + 1):
        block = bytes([i]) + _KDF_LABEL + context + enc_len
        result += aes_128_cmac(K, block)
    return result[:output_bits // 8]


# ==================================================================
# Traffic key derivation per RFC 5925 Section 5.2
# ==================================================================

def ip_to_bytes(ip_str):
    if ':' in ip_str:
        return socket.inet_pton(socket.AF_INET6, ip_str)
    return socket.inet_pton(socket.AF_INET, ip_str)


def derive_traffic_key(kdf_alg, master_key, src_ip, dst_ip,
                       src_port, dst_port, src_isn, dst_isn):
    context = (ip_to_bytes(src_ip) + ip_to_bytes(dst_ip) +
               struct.pack('!HH', src_port, dst_port) +
               struct.pack('!II', src_isn, dst_isn))
    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, context)
    elif kdf_alg == "AES-128-CMAC":
        return kdf_aes_128_cmac(master_key, context)
    raise ValueError(f"Unknown KDF: {kdf_alg}")


# ==================================================================
# MAC computation per RFC 5925 Section 5.1
# ==================================================================

def compute_mac(mac_alg, traffic_key, message):
    if mac_alg == "HMAC-SHA-1-96":
        return hmac.new(traffic_key, message, hashlib.sha1).digest()[:12]
    elif mac_alg == "AES-128-CMAC-96":
        return aes_128_cmac(traffic_key, message)[:12]
    raise ValueError(f"Unknown MAC: {mac_alg}")
