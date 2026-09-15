"""CTR-DRBG core functions: instantiate, reseed, generate.

Implements the SP 800-90A CTR_DRBG mechanism with support for the
Block_Cipher_df derivation function. The without-derivation-function
mode is not yet implemented.
"""

from drbg.derivation import block_cipher_df
from drbg.update import ctr_drbg_update
from drbg.primitives import bytes_xor, increment_counter, block_encrypt


def ctr_drbg_instantiate(entropy_input, nonce, personalization_string,
                         keylen, use_df=True, outlen=16):
    """CTR_DRBG_Instantiate per SP 800-90A Section 10.2.1.3.

    Args:
        entropy_input: Entropy bytes from the source.
        nonce: Nonce bytes (used only with derivation function).
        personalization_string: Optional personalization bytes.
        keylen: AES key length in bytes (16, 24, or 32).
        use_df: If True, use Block_Cipher_df derivation function.
        outlen: Block cipher output length (always 16 for AES).

    Returns:
        Tuple of (key, V, reseed_counter).
    """
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + nonce + personalization_string
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
        raise NotImplementedError(
            "CTR-DRBG instantiation without derivation function is not implemented. "
            "Refer to SP 800-90A Section 10.2.1.3.1 for the algorithm specification."
        )

    key = b"\x00" * keylen
    V = b"\x00" * outlen
    key, V = ctr_drbg_update(seed_material, key, V, keylen, outlen)
    reseed_counter = 1
    return key, V, reseed_counter


def ctr_drbg_reseed(key, V, reseed_counter, entropy_input, additional_input,
                    keylen, use_df=True, outlen=16):
    """CTR_DRBG_Reseed per SP 800-90A Section 10.2.1.4.

    Args:
        key: Current DRBG key.
        V: Current DRBG counter block.
        reseed_counter: Current reseed counter.
        entropy_input: New entropy bytes.
        additional_input: Optional additional input bytes.
        keylen: AES key length in bytes.
        use_df: If True, use Block_Cipher_df derivation function.
        outlen: Block cipher output length.

    Returns:
        Tuple of (key, V, reseed_counter).
    """
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + additional_input
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
        raise NotImplementedError(
            "CTR-DRBG reseed without derivation function is not implemented. "
            "Refer to SP 800-90A Section 10.2.1.4.1 for the algorithm specification."
        )

    key, V = ctr_drbg_update(seed_material, key, V, keylen, outlen)
    reseed_counter = 1
    return key, V, reseed_counter


def ctr_drbg_generate(key, V, reseed_counter, requested_bits, additional_input,
                      keylen, use_df=True, outlen=16,
                      prediction_resistance=False, entropy_input_pr=None):
    """CTR_DRBG_Generate per SP 800-90A Section 10.2.1.5.

    Args:
        key: Current DRBG key.
        V: Current DRBG counter block.
        reseed_counter: Current reseed counter.
        requested_bits: Number of bits to generate.
        additional_input: Optional additional input bytes (b"" if none).
        keylen: AES key length in bytes.
        use_df: If True, use Block_Cipher_df derivation function.
        outlen: Block cipher output length.
        prediction_resistance: If True, reseed before generating.
        entropy_input_pr: Entropy for prediction resistance reseed.

    Returns:
        Tuple of (returned_bits, key, V, reseed_counter).
    """
    seedlen = keylen + outlen

    if prediction_resistance and entropy_input_pr is not None:
        key, V, reseed_counter = ctr_drbg_reseed(
            key, V, reseed_counter, entropy_input_pr, additional_input,
            keylen, use_df, outlen
        )

    if additional_input:
        if use_df:
            additional_input = block_cipher_df(additional_input, seedlen * 8, keylen, outlen)
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
