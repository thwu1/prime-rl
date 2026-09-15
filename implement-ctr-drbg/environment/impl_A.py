"""
CTR_DRBG (AES-256) Implementation - Vendor AlphaCrypt
NIST SP 800-90A Rev.1, Section 10.2

Uses PyCryptodome for AES-256-ECB block cipher primitives.
"""

import struct
from Crypto.Cipher import AES

KEYLEN = 32
OUTLEN = 16
SEEDLEN = KEYLEN + OUTLEN


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _increment(v: bytes) -> bytes:
    n = int.from_bytes(v, "big")
    n = (n + 1) % (1 << (len(v) * 8))
    return n.to_bytes(len(v), "big")


def _bcc(key: bytes, data: bytes) -> bytes:
    """BCC per Section 10.3.3."""
    chaining_value = b"\x00" * OUTLEN
    num_blocks = len(data) // OUTLEN
    for i in range(num_blocks):
        block = data[i * OUTLEN : (i + 1) * OUTLEN]
        chaining_value = _xor(chaining_value, block)
        cipher = AES.new(key, AES.MODE_ECB)
        chaining_value = cipher.encrypt(chaining_value)
    return chaining_value


def _block_cipher_df(input_string: bytes, no_of_bits_to_return: int) -> bytes:
    """Block_Cipher_df per Section 10.3.2."""
    num_bytes_to_return = no_of_bits_to_return // 8
    L = len(input_string)
    N = num_bytes_to_return

    S = struct.pack(">I", L) + struct.pack(">I", N) + input_string + b"\x80"
    pad_len = OUTLEN - (len(S) % OUTLEN)
    if pad_len < OUTLEN:
        S += b"\x00" * pad_len

    K = bytes(range(KEYLEN))

    temp = b""
    counter = 0
    while len(temp) < KEYLEN + OUTLEN:
        # Step 8: 32-bit counter padded to block size
        IV = b"\x00" * (OUTLEN - 4) + struct.pack(">I", counter)
        temp += _bcc(K, IV + S)
        counter += 1

    K_derived = temp[:KEYLEN]
    X = temp[KEYLEN : KEYLEN + OUTLEN]

    temp = b""
    while len(temp) < num_bytes_to_return:
        cipher = AES.new(K_derived, AES.MODE_ECB)
        X = cipher.encrypt(X)
        temp += X

    return temp[:num_bytes_to_return]


def _ctr_drbg_update(provided_data: bytes, key: bytes, v: bytes) -> tuple:
    """CTR_DRBG_Update per Section 10.2.1.2."""
    temp = b""
    while len(temp) < SEEDLEN:
        v = _increment(v)
        cipher = AES.new(key, AES.MODE_ECB)
        output_block = cipher.encrypt(v)
        temp += output_block
    temp = temp[:SEEDLEN]
    temp = _xor(temp, provided_data)
    new_key = temp[:KEYLEN]
    new_v = temp[KEYLEN:]
    return new_key, new_v


class CTR_DRBG:
    def __init__(self, use_df: bool = True):
        self.use_df = use_df
        self.key = None
        self.v = None

    def instantiate(self, entropy_input, nonce, personalization_string=b""):
        if self.use_df:
            seed_material = entropy_input + nonce + personalization_string
            seed_material = _block_cipher_df(seed_material, SEEDLEN * 8)
        else:
            ps = personalization_string + b"\x00" * max(
                0, SEEDLEN - len(personalization_string)
            )
            seed_material = _xor(entropy_input[:SEEDLEN], ps[:SEEDLEN])
        self.key = b"\x00" * KEYLEN
        self.v = b"\x00" * OUTLEN
        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)

    def reseed(self, entropy_input, additional_input=b""):
        if self.use_df:
            seed_material = entropy_input + additional_input
            seed_material = _block_cipher_df(seed_material, SEEDLEN * 8)
        else:
            ai = additional_input + b"\x00" * max(
                0, SEEDLEN - len(additional_input)
            )
            seed_material = _xor(entropy_input[:SEEDLEN], ai[:SEEDLEN])
        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)

    def generate(self, requested_bits, additional_input=b""):
        requested_bytes = requested_bits // 8
        if additional_input:
            if self.use_df:
                additional_input = _block_cipher_df(additional_input, SEEDLEN * 8)
            else:
                additional_input = (
                    additional_input
                    + b"\x00" * max(0, SEEDLEN - len(additional_input))
                )[:SEEDLEN]
            self.key, self.v = _ctr_drbg_update(
                additional_input, self.key, self.v
            )
        else:
            additional_input = b"\x00" * SEEDLEN
        temp = b""
        while len(temp) < requested_bytes:
            self.v = _increment(self.v)
            cipher = AES.new(self.key, AES.MODE_ECB)
            output_block = cipher.encrypt(self.v)
            temp += output_block
        returned_bits = temp[:requested_bytes]
        self.key, self.v = _ctr_drbg_update(
            additional_input, self.key, self.v
        )
        return returned_bits
