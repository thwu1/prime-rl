"""CTR-DRBG core functions: instantiate, reseed, generate.

Fixed:
  - additional_input is cleared after prediction resistance reseed
  - Without-derivation-function mode is fully implemented per SP 800-90A
    Sections 10.2.1.3.1, 10.2.1.4.1, and 10.2.1.5.1
"""

from drbg.derivation import block_cipher_df
from drbg.update import ctr_drbg_update
from drbg.primitives import bytes_xor, increment_counter, block_encrypt


def ctr_drbg_instantiate(entropy_input, nonce, personalization_string,
                         keylen, use_df=True, outlen=16):
    """CTR_DRBG_Instantiate per SP 800-90A Section 10.2.1.3."""
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + nonce + personalization_string
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
        # Section 10.2.1.3.1: Without derivation function
        seed_material = entropy_input
        if personalization_string:
            ps = personalization_string.ljust(seedlen, b"\x00")
            seed_material = bytes_xor(seed_material, ps[:seedlen])

    key = b"\x00" * keylen
    V = b"\x00" * outlen
    key, V = ctr_drbg_update(seed_material, key, V, keylen, outlen)
    reseed_counter = 1
    return key, V, reseed_counter


def ctr_drbg_reseed(key, V, reseed_counter, entropy_input, additional_input,
                    keylen, use_df=True, outlen=16):
    """CTR_DRBG_Reseed per SP 800-90A Section 10.2.1.4."""
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + additional_input
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
        # Section 10.2.1.4.1: Without derivation function
        seed_material = entropy_input
        if additional_input:
            ai = additional_input.ljust(seedlen, b"\x00")
            seed_material = bytes_xor(seed_material, ai[:seedlen])

    key, V = ctr_drbg_update(seed_material, key, V, keylen, outlen)
    reseed_counter = 1
    return key, V, reseed_counter


def ctr_drbg_generate(key, V, reseed_counter, requested_bits, additional_input,
                      keylen, use_df=True, outlen=16,
                      prediction_resistance=False, entropy_input_pr=None):
    """CTR_DRBG_Generate per SP 800-90A Section 10.2.1.5."""
    seedlen = keylen + outlen

    if prediction_resistance and entropy_input_pr is not None:
        key, V, reseed_counter = ctr_drbg_reseed(
            key, V, reseed_counter, entropy_input_pr, additional_input,
            keylen, use_df, outlen
        )
        # FIXED: Clear additional_input after it has been consumed by reseed
        additional_input = b""

    if additional_input:
        if use_df:
            additional_input = block_cipher_df(additional_input, seedlen * 8, keylen, outlen)
        else:
            # Section 10.2.1.5.1: pad to seedlen without df
            additional_input = additional_input.ljust(seedlen, b"\x00")[:seedlen]
        key, V = ctr_drbg_update(additional_input, key, V, keylen, outlen)
    else:
        additional_input = b"\x00" * seedlen

    temp = b""
    while len(temp) * 8 < requested_bits:
        V = increment_counter(V)
        output_block = block_encrypt(key, V)
        temp += output_block

    returned_bits = temp[: requested_bits // 8]
    key, V = ctr_drbg_update(additional_input, key, V, keylen, outlen)
    reseed_counter += 1

    return returned_bits, key, V, reseed_counter
