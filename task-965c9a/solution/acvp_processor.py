#!/usr/bin/env python3
"""
ACVP Multi-Algorithm Test Vector Processor

Processes NIST ACVP prompt JSON files for:
  - SHA2-256 (AFT + MCT alternate/standard)
  - ctrDRBG (AES-256 with derivation function, prediction resistance and reseed variants)
  - ACVP-AES-GCM (encrypt + decrypt with variable tag/IV lengths)
"""

import json
import hashlib
import os
import glob
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.exceptions import InvalidTag


VECTORS_DIR = "/app/vectors"
RESPONSES_DIR = "/app/responses"


# ============================================================
# SHA2-256 processor (AFT + MCT)
# ============================================================

def process_sha2_256(prompt):
    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "testGroups": [],
    }

    for group in prompt["testGroups"]:
        test_type = group.get("testType", "AFT")

        if test_type == "AFT":
            resp_group = {"tgId": group["tgId"], "tests": []}
            for test in group["tests"]:
                msg_bytes = bytes.fromhex(test["msg"])
                # Handle len=0 case: hash empty bytes
                if test.get("len", len(msg_bytes) * 8) == 0:
                    msg_bytes = b""
                digest = hashlib.sha256(msg_bytes).hexdigest().upper()
                resp_group["tests"].append({"tcId": test["tcId"], "md": digest})
            response["testGroups"].append(resp_group)

        elif test_type == "MCT":
            mct_version = group.get("mctVersion", "standard")
            resp_group = {"tgId": group["tgId"], "tests": []}

            for test in group["tests"]:
                seed = bytes.fromhex(test["msg"])
                initial_seed_length = test["len"] // 8  # bits to bytes

                results_array = []

                if mct_version == "standard":
                    # Standard MCT: MSG = A || B || C, always 3*digestSize
                    for j in range(100):
                        A = B = C = seed
                        for i in range(1000):
                            msg = A + B + C
                            md = hashlib.sha256(msg).digest()
                            A = B
                            B = C
                            C = md
                        results_array.append({"md": md.hex().upper()})
                        seed = md

                elif mct_version == "alternate":
                    # Alternate MCT: MSG truncated/padded to initial seed length
                    for j in range(100):
                        A = B = C = seed
                        for i in range(1000):
                            msg = A + B + C
                            if len(msg) >= initial_seed_length:
                                msg = msg[:initial_seed_length]
                            else:
                                msg = msg + b'\x00' * (initial_seed_length - len(msg))
                            md = hashlib.sha256(msg).digest()
                            A = B
                            B = C
                            C = md
                        results_array.append({"md": md.hex().upper()})
                        seed = md

                resp_group["tests"].append({
                    "tcId": test["tcId"],
                    "resultsArray": results_array,
                })

            response["testGroups"].append(resp_group)

    return response


# ============================================================
# CTR-DRBG processor (SP 800-90A)
# ============================================================

def aes_ecb_encrypt(key, block):
    """Single AES ECB block encryption."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(block) + enc.finalize()


def bcc(key, data):
    """Block Cipher Chaining (BCC) function per SP 800-90A Section 10.3.3."""
    outlen = 16  # AES block size
    chaining_value = b'\x00' * outlen
    n = len(data) // outlen
    for i in range(n):
        block = bytes(a ^ b for a, b in zip(chaining_value, data[i*outlen:(i+1)*outlen]))
        chaining_value = aes_ecb_encrypt(key, block)
    return chaining_value


def block_cipher_df(input_string, no_of_bits_to_return):
    """Block_Cipher_df per SP 800-90A Section 10.3.2."""
    outlen = 16  # AES block size

    # Step 1: L = len(input_string) in bytes
    L = len(input_string)
    # Step 2: N = no_of_bits_to_return / 8
    N = no_of_bits_to_return // 8

    # Step 3: S = L || N || input_string || 0x80
    S = struct.pack('>I', L) + struct.pack('>I', N) + input_string + b'\x80'

    # Pad S to multiple of outlen
    while len(S) % outlen != 0:
        S += b'\x00'

    # Step 4: temp = empty
    temp = b''

    # Step 6: K = 0x00010203...1D1E1F (leftmost keylen bytes)
    # For AES-256 keylen=32: K = 00010203...1E1F
    keylen_bytes = 32  # AES-256
    K = bytes(range(keylen_bytes))

    # Step 7: while len(temp) < keylen + outlen
    i = 0
    while len(temp) < keylen_bytes + outlen:
        # Step 7.1: IV = i || 0^(outlen - len(i))
        IV = struct.pack('>I', i) + b'\x00' * (outlen - 4)
        # Step 7.2: temp = temp || BCC(K, IV || S)
        temp += bcc(K, IV + S)
        i += 1

    # Step 8: K = leftmost keylen bits of temp
    K = temp[:keylen_bytes]
    # Step 9: X = next outlen bits of temp
    X = temp[keylen_bytes:keylen_bytes + outlen]

    # Step 10: temp = empty
    temp = b''

    # Step 11: while len(temp) < no_of_bits_to_return / 8
    while len(temp) < N:
        X = aes_ecb_encrypt(K, X)
        temp += X

    return temp[:N]


def ctr_drbg_update(provided_data, key, V):
    """CTR_DRBG_Update per SP 800-90A Section 10.2.1.2."""
    outlen = 16  # AES block size
    keylen = len(key)
    seedlen = keylen + outlen

    temp = b''
    while len(temp) < seedlen:
        # Increment V
        V_int = int.from_bytes(V, 'big')
        V_int = (V_int + 1) % (2 ** (outlen * 8))
        V = V_int.to_bytes(outlen, 'big')
        output_block = aes_ecb_encrypt(key, V)
        temp += output_block

    temp = temp[:seedlen]

    # XOR with provided_data
    temp = bytes(a ^ b for a, b in zip(temp, provided_data))

    key = temp[:keylen]
    V = temp[keylen:]

    return key, V


def ctr_drbg_instantiate(entropy_input, nonce, personalization_string, use_df=True):
    """CTR_DRBG Instantiate per SP 800-90A Section 10.2.1.3.2 (with df)."""
    keylen = 32  # AES-256
    outlen = 16
    seedlen = keylen + outlen  # 48 bytes

    if use_df:
        seed_material = entropy_input + nonce + personalization_string
        seed_material = block_cipher_df(seed_material, seedlen * 8)
    else:
        seed_material = bytes(a ^ b for a, b in zip(
            entropy_input + nonce,
            personalization_string.ljust(seedlen, b'\x00')
        ))[:seedlen]

    key = b'\x00' * keylen
    V = b'\x00' * outlen

    key, V = ctr_drbg_update(seed_material, key, V)

    return key, V


def ctr_drbg_reseed(entropy_input, additional_input, key, V, use_df=True):
    """CTR_DRBG Reseed per SP 800-90A Section 10.2.1.4.2 (with df)."""
    keylen = 32
    outlen = 16
    seedlen = keylen + outlen

    if use_df:
        seed_material = entropy_input + additional_input
        seed_material = block_cipher_df(seed_material, seedlen * 8)
    else:
        seed_material = bytes(a ^ b for a, b in zip(
            entropy_input,
            additional_input.ljust(seedlen, b'\x00')
        ))[:seedlen]

    key, V = ctr_drbg_update(seed_material, key, V)

    return key, V


def ctr_drbg_generate(requested_bits, additional_input, key, V, use_df=True):
    """CTR_DRBG Generate per SP 800-90A Section 10.2.1.5.2 (with df)."""
    keylen = 32
    outlen = 16
    seedlen = keylen + outlen

    if additional_input:
        if use_df:
            additional_input = block_cipher_df(additional_input, seedlen * 8)
        key, V = ctr_drbg_update(additional_input, key, V)
    else:
        additional_input = b'\x00' * seedlen

    temp = b''
    requested_bytes = requested_bits // 8

    while len(temp) < requested_bytes:
        V_int = int.from_bytes(V, 'big')
        V_int = (V_int + 1) % (2 ** (outlen * 8))
        V = V_int.to_bytes(outlen, 'big')
        output_block = aes_ecb_encrypt(key, V)
        temp += output_block

    returned_bits = temp[:requested_bytes]

    key, V = ctr_drbg_update(additional_input, key, V)

    return returned_bits, key, V


def process_ctrdrbg(prompt):
    """Process ctrDRBG AFT test vectors."""
    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "testGroups": [],
    }

    for group in prompt["testGroups"]:
        resp_group = {"tgId": group["tgId"], "tests": []}
        der_func = group.get("derFunc", True)
        pred_resistance = group.get("predResistance", False)
        returned_bits_len = group["returnedBitsLen"]

        for test in group["tests"]:
            entropy = bytes.fromhex(test["entropyInput"])
            nonce = bytes.fromhex(test["nonce"])
            perso = bytes.fromhex(test["persoString"]) if test.get("persoString") else b""

            # Instantiate
            key, V = ctr_drbg_instantiate(entropy, nonce, perso, use_df=der_func)

            other_input = test["otherInput"]

            if pred_resistance:
                # Prediction resistance: each generate call includes entropy
                # Process: generate (don't output), generate (output)
                for oi in other_input[:-1]:
                    addl = bytes.fromhex(oi["additionalInput"]) if oi.get("additionalInput") else b""
                    ent = bytes.fromhex(oi["entropyInput"]) if oi.get("entropyInput") else b""
                    if ent:
                        key, V = ctr_drbg_reseed(ent, addl, key, V, use_df=der_func)
                        _, key, V = ctr_drbg_generate(returned_bits_len, b"", key, V, use_df=der_func)
                    else:
                        _, key, V = ctr_drbg_generate(returned_bits_len, addl, key, V, use_df=der_func)

                # Last generate: output
                last_oi = other_input[-1]
                addl = bytes.fromhex(last_oi["additionalInput"]) if last_oi.get("additionalInput") else b""
                ent = bytes.fromhex(last_oi["entropyInput"]) if last_oi.get("entropyInput") else b""
                if ent:
                    key, V = ctr_drbg_reseed(ent, addl, key, V, use_df=der_func)
                    output, key, V = ctr_drbg_generate(returned_bits_len, b"", key, V, use_df=der_func)
                else:
                    output, key, V = ctr_drbg_generate(returned_bits_len, addl, key, V, use_df=der_func)
            else:
                # No prediction resistance
                output = b""
                for oi in other_input:
                    intended_use = oi["intendedUse"]
                    addl = bytes.fromhex(oi["additionalInput"]) if oi.get("additionalInput") else b""
                    ent = bytes.fromhex(oi["entropyInput"]) if oi.get("entropyInput") else b""

                    if intended_use == "reSeed":
                        key, V = ctr_drbg_reseed(ent, addl, key, V, use_df=der_func)
                    elif intended_use == "generate":
                        output, key, V = ctr_drbg_generate(returned_bits_len, addl, key, V, use_df=der_func)

            resp_group["tests"].append({
                "tcId": test["tcId"],
                "returnedBits": output.hex().upper(),
            })

        response["testGroups"].append(resp_group)

    return response


# ============================================================
# AES-GCM processor
# ============================================================

def process_aes_gcm(prompt):
    """Process ACVP-AES-GCM AFT test vectors for encrypt and decrypt."""
    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "testGroups": [],
    }

    for group in prompt["testGroups"]:
        resp_group = {"tgId": group["tgId"], "tests": []}
        direction = group["direction"]
        tag_len_bytes = group["tagLen"] // 8

        for test in group["tests"]:
            key_bytes = bytes.fromhex(test["key"])
            iv_bytes = bytes.fromhex(test["iv"])
            aad_bytes = bytes.fromhex(test["aad"]) if test.get("aad") else b""

            if direction == "encrypt":
                pt_bytes = bytes.fromhex(test["pt"]) if test.get("pt") else b""

                cipher = Cipher(algorithms.AES(key_bytes), modes.GCM(iv_bytes))
                encryptor = cipher.encryptor()
                encryptor.authenticate_additional_data(aad_bytes)
                ct = encryptor.update(pt_bytes) + encryptor.finalize()
                full_tag = encryptor.tag
                truncated_tag = full_tag[:tag_len_bytes]

                resp_group["tests"].append({
                    "tcId": test["tcId"],
                    "ct": ct.hex().upper(),
                    "tag": truncated_tag.hex().upper(),
                })

            elif direction == "decrypt":
                ct_bytes = bytes.fromhex(test["ct"]) if test.get("ct") else b""
                tag_bytes = bytes.fromhex(test["tag"])

                try:
                    cipher = Cipher(
                        algorithms.AES(key_bytes),
                        modes.GCM(iv_bytes, tag=tag_bytes, min_tag_length=len(tag_bytes)),
                    )
                    decryptor = cipher.decryptor()
                    decryptor.authenticate_additional_data(aad_bytes)
                    pt = decryptor.update(ct_bytes) + decryptor.finalize()

                    resp_group["tests"].append(
                        {"tcId": test["tcId"], "pt": pt.hex().upper()}
                    )
                except InvalidTag:
                    resp_group["tests"].append(
                        {"tcId": test["tcId"], "testPassed": False}
                    )

        response["testGroups"].append(resp_group)

    return response


# ============================================================
# Dispatch
# ============================================================

ALGORITHM_HANDLERS = {
    "SHA2-256": process_sha2_256,
    "ctrDRBG": process_ctrdrbg,
    "ACVP-AES-GCM": process_aes_gcm,
}


def main():
    os.makedirs(RESPONSES_DIR, exist_ok=True)

    vector_files = glob.glob(os.path.join(VECTORS_DIR, "*_prompt.json"))

    for vector_file in sorted(vector_files):
        with open(vector_file) as f:
            prompt = json.load(f)

        algorithm = prompt.get("algorithm", "")
        handler = ALGORITHM_HANDLERS.get(algorithm)

        if handler is None:
            print(f"WARNING: Unknown algorithm '{algorithm}' in {vector_file}")
            continue

        print(f"Processing {algorithm} from {os.path.basename(vector_file)}...")
        response = handler(prompt)

        basename = os.path.basename(vector_file).replace("_prompt", "_response")
        output_path = os.path.join(RESPONSES_DIR, basename)

        with open(output_path, "w") as f:
            json.dump(response, f, indent=2)

        print(f"  -> Wrote {output_path}")

    print("Done.")


if __name__ == "__main__":
    main()
