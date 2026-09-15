"""Block_Cipher_df derivation function per SP 800-90A Section 10.3.2.

Fixed: S-string construction uses correct L || N ordering per spec.
"""

import struct
from drbg.primitives import bytes_xor, block_encrypt


def bcc(key, data, outlen=16):
    """BCC function per SP 800-90A Section 10.3.3"""
    chaining_value = b"\x00" * outlen
    n = len(data) // outlen
    for i in range(n):
        block = data[i * outlen : (i + 1) * outlen]
        input_block = bytes_xor(chaining_value, block)
        chaining_value = block_encrypt(key, input_block)
    return chaining_value


def block_cipher_df(input_string, no_of_bits_to_return, keylen, outlen=16):
    """Block_Cipher_df per SP 800-90A Section 10.3.2"""
    L = len(input_string)
    N = no_of_bits_to_return // 8

    # FIXED: Correct order is L || N (not N || L)
    S = struct.pack(">I", L) + struct.pack(">I", N) + input_string + b"\x80"
    while len(S) % outlen != 0:
        S += b"\x00"

    K = bytes(range(keylen))

    temp = b""
    i = 0
    while len(temp) < keylen + outlen:
        IV = struct.pack(">I", i) + b"\x00" * (outlen - 4)
        temp += bcc(K, IV + S, outlen)
        i += 1

    K = temp[:keylen]
    X = temp[keylen : keylen + outlen]

    temp = b""
    while len(temp) < no_of_bits_to_return // 8:
        X = block_encrypt(K, X)
        temp += X

    return temp[: no_of_bits_to_return // 8]
