#!/usr/bin/env python3
"""
ACVP AES-CBC Test Vector Processor with Salted Key Evolution

Reads /data/prompt.json, processes all AFT and MCT test groups,
and writes the response to /app/response.json.
"""

import json
import hashlib
import os
from Crypto.Cipher import AES


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def aes_ecb_encrypt(key: bytes, block: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(block)


def aes_ecb_decrypt(key: bytes, block: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(block)


def aes_cbc_encrypt(key: bytes, iv: bytes, pt: bytes) -> bytes:
    """AES-CBC encrypt (handles multi-block)."""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pt)


def aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    """AES-CBC decrypt (handles multi-block)."""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.decrypt(ct)


def key_shuffle(key: bytes, last: bytes, second_last: bytes, key_bits: int) -> bytes:
    """
    AES Key Shuffle.
    'last' = CT[999] for encrypt or PT[999] for decrypt.
    'second_last' = CT[998] for encrypt or PT[998] for decrypt.
    """
    if key_bits == 128:
        return xor_bytes(key, last)
    elif key_bits == 192:
        # Key XOR (LSB(second_last, 64) || last)
        # LSB 64 bits = last 8 bytes of second_last
        combined = second_last[8:16] + last
        return xor_bytes(key, combined)
    elif key_bits == 256:
        # Key XOR (second_last || last)
        combined = second_last + last
        return xor_bytes(key, combined)
    else:
        raise ValueError(f"Unsupported key length: {key_bits}")


def salted_key_evolution(key: bytes, round_num: int, domain_sep: bytes, key_bits: int) -> bytes:
    """
    After standard key shuffle, XOR key with SHA-256(domainSeparator || round_counter)[:keyLen].
    """
    salt_input = domain_sep + round_num.to_bytes(4, 'big')
    salt_hash = hashlib.sha256(salt_input).digest()
    key_len = key_bits // 8
    salt = salt_hash[:key_len]
    return xor_bytes(key, salt)


def process_mct_encrypt(key: bytes, iv: bytes, pt: bytes, key_bits: int, domain_sep: bytes) -> list:
    """Process MCT encrypt: 100 outer rounds x 1000 inner iterations with salted key evolution."""
    results = []

    for i in range(100):
        round_result = {
            "key": key.hex().upper(),
            "iv": iv.hex().upper(),
            "pt": pt.hex().upper(),
        }

        prev_ct = iv
        prev_prev_ct = None

        for j in range(1000):
            # CBC encrypt single block: CT = AES_ECB(Key, PT XOR prev_CT)
            ct = aes_ecb_encrypt(key, xor_bytes(pt, prev_ct))

            if j == 0:
                next_pt = iv
            else:
                next_pt = prev_ct  # CT[j-1]

            prev_prev_ct = prev_ct
            prev_ct = ct
            pt = next_pt

        round_result["ct"] = ct.hex().upper()
        results.append(round_result)

        # Key shuffle using CT values
        key = key_shuffle(key, ct, prev_prev_ct, key_bits)
        # Salted key evolution
        key = salted_key_evolution(key, i, domain_sep, key_bits)
        iv = ct             # IV[i+1] = CT[999]
        pt = prev_prev_ct   # PT[0] = CT[998]

    return results


def process_mct_decrypt(key: bytes, iv: bytes, ct: bytes, key_bits: int, domain_sep: bytes) -> list:
    """Process MCT decrypt: 100 outer rounds x 1000 inner iterations with salted key evolution.
    Derived from encrypt MCT by swapping PT/CT references."""
    results = []

    for i in range(100):
        round_result = {
            "key": key.hex().upper(),
            "iv": iv.hex().upper(),
            "ct": ct.hex().upper(),
        }

        prev_ct_for_xor = iv  # CBC XOR source (previous ciphertext block)
        prev_pt = None
        prev_prev_pt = None

        for j in range(1000):
            # CBC decrypt single block: PT = AES_ECB_DECRYPT(Key, CT) XOR prev_CT
            pt = xor_bytes(aes_ecb_decrypt(key, ct), prev_ct_for_xor)
            prev_ct_for_xor = ct  # Current CT becomes XOR source for next

            if j == 0:
                next_ct = iv
            else:
                next_ct = prev_pt  # PT[j-1]

            prev_prev_pt = prev_pt
            prev_pt = pt
            ct = next_ct

        round_result["pt"] = pt.hex().upper()
        results.append(round_result)

        # Key shuffle using PT values (swapped from encrypt)
        key = key_shuffle(key, pt, prev_prev_pt, key_bits)
        # Salted key evolution
        key = salted_key_evolution(key, i, domain_sep, key_bits)
        iv = pt              # IV[i+1] = PT[999]
        ct = prev_prev_pt    # CT[0] = PT[998]

    return results


def process_test_group(tg: dict, domain_sep: bytes) -> dict:
    """Process a single test group and return the response group."""
    tg_id = tg["tgId"]
    test_type = tg["testType"]
    direction = tg["direction"]
    key_len = tg["keyLen"]

    response_tests = []

    for tc in tg["tests"]:
        tc_id = tc["tcId"]
        key = bytes.fromhex(tc["key"])
        iv = bytes.fromhex(tc["iv"])

        if test_type == "AFT":
            if direction == "encrypt":
                pt = bytes.fromhex(tc["pt"])
                ct = aes_cbc_encrypt(key, iv, pt)
                response_tests.append({
                    "tcId": tc_id,
                    "ct": ct.hex().upper(),
                })
            else:
                ct = bytes.fromhex(tc["ct"])
                pt = aes_cbc_decrypt(key, iv, ct)
                response_tests.append({
                    "tcId": tc_id,
                    "pt": pt.hex().upper(),
                })
        elif test_type == "MCT":
            if direction == "encrypt":
                pt = bytes.fromhex(tc["pt"])
                results_array = process_mct_encrypt(key, iv, pt, key_len, domain_sep)
            else:
                ct = bytes.fromhex(tc["ct"])
                results_array = process_mct_decrypt(key, iv, ct, key_len, domain_sep)

            response_tests.append({
                "tcId": tc_id,
                "resultsArray": results_array,
            })

    return {"tgId": tg_id, "tests": response_tests}


def main():
    with open("/data/prompt.json") as f:
        prompt = json.load(f)

    domain_sep = bytes.fromhex(prompt["domainSeparator"])

    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "isSample": prompt["isSample"],
        "testGroups": [],
    }

    for tg in prompt["testGroups"]:
        response_group = process_test_group(tg, domain_sep)
        response["testGroups"].append(response_group)

    os.makedirs("/app", exist_ok=True)
    with open("/app/response.json", "w") as f:
        json.dump(response, f, indent=2)

    print(f"Response written to /app/response.json")
    print(f"Processed {len(response['testGroups'])} test groups")


if __name__ == "__main__":
    main()
