"""CTR_DRBG_Update per SP 800-90A Section 10.2.1.2.

Fixed: Counter V is incremented BEFORE encryption per spec.
"""

from drbg.primitives import bytes_xor, increment_counter, block_encrypt


def ctr_drbg_update(provided_data, key, V, keylen, outlen=16):
    """CTR_DRBG_Update per SP 800-90A Section 10.2.1.2"""
    seedlen = keylen + outlen
    temp = b""
    while len(temp) < seedlen:
        # FIXED: increment THEN encrypt (spec: V = (V+1) mod 2^outlen, then Block_Encrypt)
        V = increment_counter(V)
        output_block = block_encrypt(key, V)
        temp += output_block
    temp = temp[:seedlen]
    temp = bytes_xor(temp, provided_data)
    key = temp[:keylen]
    V = temp[keylen : keylen + outlen]
    return key, V
