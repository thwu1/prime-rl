"""
NIST SP 800-90A Rev.1 CTR_DRBG Implementation using AES-256.

Implements the Counter-mode Deterministic Random Bit Generator
as specified in NIST Special Publication 800-90A Revision 1,
Section 10.2 (CTR_DRBG).

Supports both derivation-function (df) and non-derivation-function modes.
Uses PyCryptodome for raw AES-256-ECB block cipher operations only.
"""

import struct
from Crypto.Cipher import AES

# AES-256 CTR_DRBG parameters (NIST SP 800-90A Table 3)
KEYLEN = 32      # 256 bits
OUTLEN = 16      # AES block size = 128 bits
SEEDLEN = KEYLEN + OUTLEN  # 48 bytes = 384 bits


def _xor(a: bytes, b: bytes) -> bytes:
    """XOR two equal-length byte strings."""
    return bytes(x ^ y for x, y in zip(a, b))


def _increment(v: bytes) -> bytes:
    """Increment a big-endian counter by 1, modulo 2^(len*8)."""
    n = int.from_bytes(v, "big")
    n = (n + 1) % (1 << (len(v) * 8))
    return n.to_bytes(len(v), "big")


def _bcc(key: bytes, data: bytes) -> bytes:
    """BCC function per NIST SP 800-90A Section 10.3.3.

    Computes a CBC-MAC-like chaining over data using the given key.
    data length must be a multiple of OUTLEN (16 bytes).
    """
    chaining_value = b"\x00" * OUTLEN
    num_blocks = len(data) // OUTLEN
    for i in range(num_blocks):
        block = data[i * OUTLEN : (i + 1) * OUTLEN]
        chaining_value = _xor(chaining_value, block)
        cipher = AES.new(key, AES.MODE_ECB)
        chaining_value = cipher.encrypt(chaining_value)
    return chaining_value


def _block_cipher_df(input_string: bytes, no_of_bits_to_return: int) -> bytes:
    """Block_Cipher_df per NIST SP 800-90A Section 10.3.2.

    Derivation function that conditions arbitrary-length input into
    a fixed-length seed using BCC with AES-256.
    """
    num_bytes_to_return = no_of_bits_to_return // 8

    # Step 2-3: L = byte length of input, N = bytes to return (both as 32-bit BE)
    L = len(input_string)
    N = num_bytes_to_return

    # Step 4: S = L || N || input_string || 0x80 || zero-pad to block boundary
    S = struct.pack(">I", L) + struct.pack(">I", N) + input_string + b"\x80"
    pad_len = OUTLEN - (len(S) % OUTLEN)
    if pad_len < OUTLEN:
        S += b"\x00" * pad_len

    # Step 7: K = 0x00010203...1E1F (first keylen bytes of incrementing sequence)
    K = bytes(range(KEYLEN))

    # Steps 8-9: Iterate BCC with incrementing IV to produce keylen+outlen bytes
    temp = b""
    counter = 0
    while len(temp) < KEYLEN + OUTLEN:
        # Construct IV: 32-bit counter value padded to block size
        IV = b"\x00" * (OUTLEN - 4) + struct.pack(">I", counter)
        temp += _bcc(K, IV + S)
        counter += 1

    # Steps 10-11: Split temp into new key and initial X
    K_derived = temp[:KEYLEN]
    X = temp[KEYLEN : KEYLEN + OUTLEN]

    # Steps 12-14: Generate output by encrypting X repeatedly with K_derived
    temp = b""
    while len(temp) < num_bytes_to_return:
        cipher = AES.new(K_derived, AES.MODE_ECB)
        X = cipher.encrypt(X)
        temp += X

    return temp[:num_bytes_to_return]


def _ctr_drbg_update(provided_data: bytes, key: bytes, v: bytes) -> tuple:
    """CTR_DRBG_Update per NIST SP 800-90A Section 10.2.1.2.

    Updates the internal state using provided_data (must be seedlen bytes).
    Returns (new_key, new_v).
    """
    temp = b""
    while len(temp) < SEEDLEN:
        v = _increment(v)
        cipher = AES.new(key, AES.MODE_ECB)
        output_block = cipher.encrypt(v)
        temp += output_block
    temp = temp[:SEEDLEN]

    # XOR with provided_data
    temp = _xor(temp, provided_data)

    new_key = temp[:KEYLEN]
    new_v = temp[KEYLEN:]
    return new_key, new_v


class CTR_DRBG:
    """NIST SP 800-90A CTR_DRBG with AES-256."""

    def __init__(self, use_df: bool = True):
        self.use_df = use_df
        self.key = None
        self.v = None

    def instantiate(
        self,
        entropy_input: bytes,
        nonce: bytes,
        personalization_string: bytes = b"",
    ) -> None:
        """CTR_DRBG_Instantiate per Sections 10.2.1.3.1 / 10.2.1.3.2."""
        if self.use_df:
            # Section 10.2.1.3.2 (with derivation function)
            seed_material = entropy_input + nonce + personalization_string
            seed_material = _block_cipher_df(seed_material, SEEDLEN * 8)
        else:
            # Section 10.2.1.3.1 (without derivation function)
            # entropy_input is already seedlen bytes; XOR with padded pers string
            ps = personalization_string + b"\x00" * max(
                0, SEEDLEN - len(personalization_string)
            )
            seed_material = _xor(entropy_input[:SEEDLEN], ps[:SEEDLEN])

        self.key = b"\x00" * KEYLEN
        self.v = b"\x00" * OUTLEN
        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)

    def reseed(
        self,
        entropy_input: bytes,
        additional_input: bytes = b"",
    ) -> None:
        """CTR_DRBG_Reseed per Sections 10.2.1.4.1 / 10.2.1.4.2."""
        if self.use_df:
            # Section 10.2.1.4.2
            seed_material = entropy_input + additional_input
            seed_material = _block_cipher_df(seed_material, SEEDLEN * 8)
        else:
            # Section 10.2.1.4.1
            ai = additional_input + b"\x00" * max(
                0, SEEDLEN - len(additional_input)
            )
            seed_material = _xor(entropy_input[:SEEDLEN], ai[:SEEDLEN])

        # Re-initialize state before updating (per Section 10.2.1.4.2 step 3)
        self.key = b"\x00" * KEYLEN
        self.v = b"\x00" * OUTLEN
        self.key, self.v = _ctr_drbg_update(seed_material, self.key, self.v)

    def generate(
        self,
        requested_bits: int,
        additional_input: bytes = b"",
    ) -> bytes:
        """CTR_DRBG_Generate per Sections 10.2.1.5.1 / 10.2.1.5.2."""
        requested_bytes = requested_bits // 8

        if additional_input:
            if self.use_df:
                # Section 10.2.1.5.2 step 1.1
                additional_input = _block_cipher_df(additional_input, SEEDLEN * 8)
            else:
                # Section 10.2.1.5.1 step 1.1
                additional_input = (
                    additional_input
                    + b"\x00" * max(0, SEEDLEN - len(additional_input))
                )[:SEEDLEN]
            # Step 1.2
            self.key, self.v = _ctr_drbg_update(
                additional_input, self.key, self.v
            )
        else:
            additional_input = b"\x00" * SEEDLEN

        # Steps 3-5: Generate output blocks
        temp = b""
        while len(temp) < requested_bytes:
            self.v = _increment(self.v)
            cipher = AES.new(self.key, AES.MODE_ECB)
            output_block = cipher.encrypt(self.v)
            temp += output_block

        returned_bits = temp[:requested_bytes]

        # Step 6: Update state
        self.key, self.v = _ctr_drbg_update(
            additional_input, self.key, self.v
        )

        return returned_bits
