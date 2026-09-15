#!/usr/bin/env python3
"""
ACVP CTR-DRBG Test Vector Processor
Implements SP 800-90A CTR_DRBG with Block_Cipher_df derivation function.
Processes ACVP prompt JSON and produces conformant response JSON.
"""

import json
import struct
import sys
from Crypto.Cipher import AES


def bytes_xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def increment_counter(V):
    val = int.from_bytes(V, "big")
    val = (val + 1) % (1 << (len(V) * 8))
    return val.to_bytes(len(V), "big")


def block_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)


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

    # S = L || N || input_string || 0x80 || zero-padding to outlen boundary
    S = struct.pack(">I", N) + struct.pack(">I", L) + input_string + b"\x80"
    while len(S) % outlen != 0:
        S += b"\x00"

    # Initial key K = 0x00010203...
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


def ctr_drbg_update(provided_data, key, V, keylen, outlen=16):
    """CTR_DRBG_Update per SP 800-90A Section 10.2.1.2"""
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


def ctr_drbg_instantiate(entropy_input, nonce, personalization_string, keylen, use_df=True, outlen=16):
    """CTR_DRBG_Instantiate per SP 800-90A Section 10.2.1.3.2 (with df)"""
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + nonce + personalization_string
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
        seed_material = entropy_input
        if personalization_string:
            ps = personalization_string.ljust(seedlen, b"\x00")
            seed_material = bytes_xor(seed_material, ps[:seedlen])

    key = b"\x00" * keylen
    V = b"\x00" * outlen
    key, V = ctr_drbg_update(seed_material, key, V, keylen, outlen)
    reseed_counter = 1
    return key, V, reseed_counter


def ctr_drbg_reseed(key, V, reseed_counter, entropy_input, additional_input, keylen, use_df=True, outlen=16):
    """CTR_DRBG_Reseed per SP 800-90A Section 10.2.1.4.2 (with df)"""
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + additional_input
        seed_material = block_cipher_df(seed_material, seedlen * 8, keylen, outlen)
    else:
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
    """CTR_DRBG_Generate per SP 800-90A Section 10.2.1.5.2 (with df)"""
    seedlen = keylen + outlen

    if prediction_resistance and entropy_input_pr is not None:
        key, V, reseed_counter = ctr_drbg_reseed(
            key, V, reseed_counter, entropy_input_pr, additional_input,
            keylen, use_df, outlen
        )
        additional_input = b""

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


MODE_TO_KEYLEN = {
    "AES-128": 16,
    "AES-192": 24,
    "AES-256": 32,
}


def process_test_group(group):
    mode = group["mode"]
    keylen = MODE_TO_KEYLEN[mode]
    use_df = group["derFunc"]
    pred_resistance = group["predResistance"]
    reseed_enabled = group["reSeed"]
    returned_bits_len = group["returnedBitsLen"]

    results = []
    for test in group["tests"]:
        tc_id = test["tcId"]
        entropy_input = bytes.fromhex(test["entropyInput"])
        nonce = bytes.fromhex(test["nonce"]) if test["nonce"] else b""
        perso_string = bytes.fromhex(test["persoString"]) if test["persoString"] else b""

        key, V, rc = ctr_drbg_instantiate(entropy_input, nonce, perso_string, keylen, use_df)

        other_inputs = test["otherInput"]

        if pred_resistance:
            # Scenario: predResistance=true
            # Two generate calls with prediction resistance
            # First generate: don't output
            oi0 = other_inputs[0]
            ai0 = bytes.fromhex(oi0["additionalInput"]) if oi0["additionalInput"] else b""
            ei0 = bytes.fromhex(oi0["entropyInput"]) if oi0["entropyInput"] else None
            _, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai0, keylen, use_df,
                prediction_resistance=True, entropy_input_pr=ei0
            )

            # Second generate: output
            oi1 = other_inputs[1]
            ai1 = bytes.fromhex(oi1["additionalInput"]) if oi1["additionalInput"] else b""
            ei1 = bytes.fromhex(oi1["entropyInput"]) if oi1["entropyInput"] else None
            returned, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai1, keylen, use_df,
                prediction_resistance=True, entropy_input_pr=ei1
            )

        elif reseed_enabled:
            # Scenario: predResistance=false, reSeed=true
            # Process otherInput entries by intendedUse
            generate_count = 0
            returned = None
            for oi in other_inputs:
                ai = bytes.fromhex(oi["additionalInput"]) if oi["additionalInput"] else b""
                ei = bytes.fromhex(oi["entropyInput"]) if oi["entropyInput"] else b""

                if oi["intendedUse"] == "reSeed":
                    key, V, rc = ctr_drbg_reseed(key, V, rc, ei, ai, keylen, use_df)
                elif oi["intendedUse"] == "generate":
                    generate_count += 1
                    bits, key, V, rc = ctr_drbg_generate(
                        key, V, rc, returned_bits_len, ai, keylen, use_df,
                        prediction_resistance=False
                    )
                    if generate_count >= 2:
                        returned = bits

        else:
            # Scenario: predResistance=false, reSeed=false
            # Two generate calls without prediction resistance
            oi0 = other_inputs[0]
            ai0 = bytes.fromhex(oi0["additionalInput"]) if oi0["additionalInput"] else b""
            _, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai0, keylen, use_df,
                prediction_resistance=False
            )

            oi1 = other_inputs[1]
            ai1 = bytes.fromhex(oi1["additionalInput"]) if oi1["additionalInput"] else b""
            returned, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai1, keylen, use_df,
                prediction_resistance=False
            )

        results.append({
            "tcId": tc_id,
            "returnedBits": returned.hex().upper()
        })

    return {"tgId": group["tgId"], "tests": results}


def main():
    prompt_path = "/app/prompts/ctrdrbg_prompt.json"
    response_path = "/app/responses/ctrdrbg_response.json"

    with open(prompt_path, "r") as f:
        prompt = json.load(f)

    response_groups = []
    for group in prompt["testGroups"]:
        response_groups.append(process_test_group(group))

    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "testGroups": response_groups
    }

    with open(response_path, "w") as f:
        json.dump(response, f, indent=2)


if __name__ == "__main__":
    main()
