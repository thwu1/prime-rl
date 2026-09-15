"""CTR_DRBG_Update per SP 800-90A Section 10.2.1.2."""

from drbg.primitives import bytes_xor, increment_counter, block_encrypt


def ctr_drbg_update(provided_data, key, V, keylen, outlen=16):
    """CTR_DRBG_Update function.

    Updates the DRBG internal state (Key, V) using provided_data.
    provided_data must be exactly seedlen = keylen + outlen bytes.
    """
    seedlen = keylen + outlen
    temp = b""
    while len(temp) < seedlen:
        output_block = block_encrypt(key, V)
        V = increment_counter(V)
        temp += output_block
    temp = temp[:seedlen]
    temp = bytes_xor(temp, provided_data)
    key = temp[:keylen]
    V = temp[keylen : keylen + outlen]
    return key, V
