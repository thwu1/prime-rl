"""
CTR_DRBG implementation with AES block cipher.
Supports use-df and no-df operational modes.
"""

import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _aes_ecb_encrypt(key, block):
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(block) + enc.finalize()


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _inc(v):
    val = int.from_bytes(v, "big")
    val = (val + 1) % (1 << (len(v) * 8))
    return val.to_bytes(len(v), "big")


class CTR_DRBG:
    OUTLEN = 16

    def __init__(self, keylen=32, use_df=True):
        if keylen not in (16, 24, 32):
            raise ValueError("keylen must be 16, 24, or 32")
        self.keylen = keylen
        self.seedlen = keylen + self.OUTLEN
        self.use_df = use_df
        self.key = None
        self.V = None

    def _bcc(self, bcc_key, data):
        chaining_value = b"\x00" * self.OUTLEN
        n = len(data) // self.OUTLEN
        for i in range(n):
            block = data[i * self.OUTLEN:(i + 1) * self.OUTLEN]
            chaining_value = _aes_ecb_encrypt(
                bcc_key, _xor(chaining_value, block)
            )
        return chaining_value

    def _block_cipher_df(self, input_string, no_of_bits):
        no_of_bytes = no_of_bits // 8
        L = len(input_string)
        N = no_of_bytes

        S = struct.pack(">I", L) + struct.pack(">I", N) + input_string + b"\x80"
        pad_len = self.OUTLEN - (len(S) % self.OUTLEN)
        if pad_len < self.OUTLEN:
            S += b"\x00" * pad_len

        K = bytes(range(self.keylen))

        temp = b""
        counter = 0
        while len(temp) < self.keylen + self.OUTLEN:
            IV = struct.pack(">I", counter) + b"\x00" * (self.OUTLEN - 4)
            temp += self._bcc(K, IV + S)
            counter += 1
        temp = temp[:self.keylen + self.OUTLEN]

        # Extract derived key and initial value for output generation
        derived_key = temp[:self.keylen]
        X = temp[self.keylen:self.keylen + self.OUTLEN]

        # Generate output using encryption iterations
        temp = b""
        while len(temp) < no_of_bytes:
            X = _aes_ecb_encrypt(K, X)
            temp += X

        return temp[:no_of_bytes]

    def _update(self, provided_data, key, V):
        temp = b""
        while len(temp) < self.seedlen:
            V = _inc(V)
            output_block = _aes_ecb_encrypt(key, V)
            temp += output_block
        temp = temp[:self.seedlen]
        temp = _xor(temp, provided_data)
        new_key = temp[:self.keylen]
        new_V = temp[self.keylen:self.seedlen]
        return new_key, new_V

    def instantiate(self, entropy_input, nonce, personalization_string=b""):
        if self.use_df:
            seed_material = entropy_input + nonce + personalization_string
            seed_material = self._block_cipher_df(
                seed_material, self.seedlen * 8
            )
        else:
            seed_material = bytearray(entropy_input)
            if personalization_string:
                ps = personalization_string + b"\x00" * (
                    self.seedlen - len(personalization_string)
                )
                ps = ps[:self.seedlen]
                seed_material = bytes(
                    _xor(
                        bytes(seed_material[:self.keylen]),
                        ps[:self.keylen]
                    )
                ) + bytes(seed_material[self.keylen:self.seedlen])
            else:
                seed_material = bytes(seed_material[:self.seedlen])

        key = b"\x00" * self.keylen
        V = b"\x00" * self.OUTLEN
        key, V = self._update(seed_material, key, V)
        self.key = key
        self.V = V
        return key, V

    def generate(self, additional_input=b"", requested_bits=512):
        requested_bytes = requested_bits // 8

        if additional_input and len(additional_input) > 0:
            if self.use_df:
                additional_input = self._block_cipher_df(
                    additional_input, self.seedlen * 8
                )
            else:
                additional_input = additional_input + b"\x00" * (
                    self.seedlen - len(additional_input)
                )
                additional_input = additional_input[:self.seedlen]
            self.key, self.V = self._update(
                additional_input, self.key, self.V
            )

        # Generate output blocks
        temp = b""
        while len(temp) < requested_bytes:
            self.V = _inc(self.V)
            output_block = _aes_ecb_encrypt(self.key, self.V)
            temp += output_block

        returned_bits = temp[:requested_bytes]

        # Finalize state for next request
        self.key, self.V = self._update(
            b"\x00" * self.seedlen, self.key, self.V
        )

        return returned_bits, self.key, self.V
