#!/usr/bin/env python3

"""
ACVP test vector processor for AES-CBC and SHA2-256.
Reads prompt JSON files and generates correct response JSON files.
"""

import json
import hashlib
import os
from Crypto.Cipher import AES


# ---------------------------------------------------------------------------
# AES-CBC helpers
# ---------------------------------------------------------------------------

def aes_ecb_encrypt(key: bytes, block: bytes) -> bytes:
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def aes_ecb_decrypt(key: bytes, block: bytes) -> bytes:
    return AES.new(key, AES.MODE_ECB).decrypt(block)


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def aes_cbc_encrypt_single(key: bytes, iv: bytes, pt: bytes) -> bytes:
    """Encrypt a single AES-CBC block: CT = AES_ECB_ENCRYPT(key, pt XOR iv)."""
    return aes_ecb_encrypt(key, xor_bytes(pt, iv))


def aes_cbc_decrypt_single(key: bytes, iv: bytes, ct: bytes) -> bytes:
    """Decrypt a single AES-CBC block: PT = AES_ECB_DECRYPT(key, ct) XOR iv."""
    return xor_bytes(aes_ecb_decrypt(key, ct), iv)


def aes_key_shuffle(key: bytes, out_prev: bytes, out_last: bytes) -> bytes:
    """
    AES key shuffle after MCT inner loop.
    key: current key
    out_prev: OUT[998] (second-to-last output of inner loop)
    out_last: OUT[999] (last output of inner loop)
    """
    key_len = len(key) * 8
    if key_len == 128:
        return xor_bytes(key, out_last)
    elif key_len == 192:
        # Key[i+1] = Key[i] XOR (LSB(OUT[998], 64) || OUT[999])
        lsb_64 = out_prev[8:]  # last 8 bytes of 16-byte block
        combined = lsb_64 + out_last  # 8 + 16 = 24 bytes
        return xor_bytes(key, combined)
    elif key_len == 256:
        # Key[i+1] = Key[i] XOR (OUT[998] || OUT[999])
        combined = out_prev + out_last  # 16 + 16 = 32 bytes
        return xor_bytes(key, combined)
    else:
        raise ValueError(f"Unsupported key length: {key_len}")


def process_aes_cbc_aft(test_case: dict, direction: str) -> dict:
    """Process a single AES-CBC AFT test case (single or multi-block)."""
    tc_id = test_case["tcId"]
    key = bytes.fromhex(test_case["key"])
    iv = bytes.fromhex(test_case["iv"])

    if direction == "encrypt":
        pt = bytes.fromhex(test_case["pt"])
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        ct = cipher.encrypt(pt)
        return {"tcId": tc_id, "ct": ct.hex().upper()}
    else:
        ct = bytes.fromhex(test_case["ct"])
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        pt = cipher.decrypt(ct)
        return {"tcId": tc_id, "pt": pt.hex().upper()}


def process_aes_cbc_mct_encrypt(test_case: dict, key_len: int) -> dict:
    """Process AES-CBC MCT encrypt test case."""
    tc_id = test_case["tcId"]
    key = bytes.fromhex(test_case["key"])
    iv = bytes.fromhex(test_case["iv"])
    pt = bytes.fromhex(test_case["pt"])

    results_array = []

    for i in range(100):
        result_entry = {
            "key": key.hex().upper(),
            "iv": iv.hex().upper(),
            "pt": pt.hex().upper(),
        }

        ct_second_last = None
        ct_last = None

        for j in range(1000):
            if j == 0:
                ct = aes_cbc_encrypt_single(key, iv, pt)
                next_pt = iv
            else:
                ct = aes_cbc_encrypt_single(key, ct_last, pt)
                next_pt = ct_last

            ct_second_last = ct_last
            ct_last = ct
            pt = next_pt

        result_entry["ct"] = ct_last.hex().upper()
        results_array.append(result_entry)

        # Key shuffle using CT values (encrypt)
        key = aes_key_shuffle(key, ct_second_last, ct_last)
        iv = ct_last
        pt = ct_second_last

    return {"tcId": tc_id, "resultsArray": results_array}


def process_aes_cbc_mct_decrypt(test_case: dict, key_len: int) -> dict:
    """Process AES-CBC MCT decrypt test case."""
    tc_id = test_case["tcId"]
    key = bytes.fromhex(test_case["key"])
    iv = bytes.fromhex(test_case["iv"])
    ct = bytes.fromhex(test_case["ct"])

    results_array = []

    for i in range(100):
        result_entry = {
            "key": key.hex().upper(),
            "iv": iv.hex().upper(),
            "ct": ct.hex().upper(),
        }

        # Track CBC chain IV separately from the CT being decrypted.
        # In CBC decrypt, the chain IV is the previous CIPHERTEXT (input),
        # not the previous PLAINTEXT (output).
        cbc_iv = iv
        ct_cur = ct
        pt_prev = None
        pt_second_last = None
        pt_last = None

        for j in range(1000):
            pt = aes_cbc_decrypt_single(key, cbc_iv, ct_cur)

            # Update CBC chain: IV for next step = current CT block
            cbc_iv = ct_cur

            # Compute next CT to decrypt
            if j == 0:
                next_ct = iv
            else:
                next_ct = pt_prev

            pt_second_last = pt_last
            pt_last = pt
            pt_prev = pt
            ct_cur = next_ct

        result_entry["pt"] = pt_last.hex().upper()
        results_array.append(result_entry)

        # Key shuffle using PT values (decrypt)
        key = aes_key_shuffle(key, pt_second_last, pt_last)
        iv = pt_last
        ct = pt_second_last

    return {"tcId": tc_id, "resultsArray": results_array}


# ---------------------------------------------------------------------------
# SHA2-256 helpers
# ---------------------------------------------------------------------------

def process_sha256_aft(test_case: dict) -> dict:
    """Process a single SHA2-256 AFT test case."""
    tc_id = test_case["tcId"]
    msg_hex = test_case["msg"]
    msg_len = test_case["len"]

    if msg_len == 0:
        msg_bytes = b""
    else:
        msg_bytes = bytes.fromhex(msg_hex)[:msg_len // 8]

    md = hashlib.sha256(msg_bytes).hexdigest().upper()
    return {"tcId": tc_id, "md": md}


def process_sha256_mct(test_case: dict, mct_version: str) -> dict:
    """Process SHA2-256 MCT test case."""
    tc_id = test_case["tcId"]
    seed = bytes.fromhex(test_case["msg"])
    initial_seed_length = test_case["len"]  # in bits

    results_array = []

    for j in range(100):
        a = seed[:]
        b = seed[:]
        c = seed[:]

        for i_inner in range(1000):
            msg = a + b + c
            if mct_version == "alternate":
                msg_len_bits = len(msg) * 8
                if msg_len_bits >= initial_seed_length:
                    msg = msg[:initial_seed_length // 8]
                else:
                    msg = msg + b"\x00" * ((initial_seed_length - msg_len_bits) // 8)
            md = hashlib.sha256(msg).digest()
            a = b
            b = c
            c = md

        results_array.append({"md": c.hex().upper()})
        seed = c

    return {"tcId": tc_id, "resultsArray": results_array}


def process_sha256_ldt(test_case: dict) -> dict:
    """Process SHA2-256 LDT test case using streaming hash."""
    tc_id = test_case["tcId"]
    large_msg = test_case["largeMsg"]
    content = bytes.fromhex(large_msg["content"])
    content_len_bytes = large_msg["contentLength"] // 8
    full_len_bytes = large_msg["fullLength"] // 8

    h = hashlib.sha256()

    # Create a large chunk for efficiency (~1MB)
    chunk_reps = max(1, (1024 * 1024) // content_len_bytes)
    chunk = content * chunk_reps
    chunk_size = len(chunk)

    written = 0
    while written + chunk_size <= full_len_bytes:
        h.update(chunk)
        written += chunk_size

    remaining = full_len_bytes - written
    if remaining > 0:
        reps = remaining // content_len_bytes
        if reps > 0:
            h.update(content * reps)

    md = h.hexdigest().upper()
    return {"tcId": tc_id, "md": md}


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def process_aes_cbc(prompt_path: str, result_path: str):
    """Process the AES-CBC ACVP prompt and generate response."""
    with open(prompt_path) as f:
        prompt = json.load(f)

    result = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "isSample": prompt["isSample"],
        "testGroups": [],
    }

    for tg in prompt["testGroups"]:
        tg_id = tg["tgId"]
        test_type = tg["testType"]
        direction = tg["direction"]
        key_len = tg["keyLen"]

        result_tg = {"tgId": tg_id, "tests": []}

        print(f"  Processing tgId={tg_id} ({test_type}, {direction}, {key_len}-bit)...",
              flush=True)

        for tc in tg["tests"]:
            if test_type == "AFT":
                result_tc = process_aes_cbc_aft(tc, direction)
            elif test_type == "MCT":
                if direction == "encrypt":
                    result_tc = process_aes_cbc_mct_encrypt(tc, key_len)
                else:
                    result_tc = process_aes_cbc_mct_decrypt(tc, key_len)
            else:
                raise ValueError(f"Unknown test type: {test_type}")
            result_tg["tests"].append(result_tc)

        result["testGroups"].append(result_tg)

    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  AES-CBC results written to {result_path}")


def process_sha256(prompt_path: str, result_path: str):
    """Process the SHA2-256 ACVP prompt and generate response."""
    with open(prompt_path) as f:
        prompt = json.load(f)

    result = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "isSample": prompt["isSample"],
        "testGroups": [],
    }

    for tg in prompt["testGroups"]:
        tg_id = tg["tgId"]
        test_type = tg["testType"]

        result_tg = {"tgId": tg_id, "tests": []}

        print(f"  Processing tgId={tg_id} ({test_type})...", flush=True)

        for tc in tg["tests"]:
            if test_type == "AFT":
                result_tc = process_sha256_aft(tc)
            elif test_type == "MCT":
                mct_version = tg.get("mctVersion", "standard")
                result_tc = process_sha256_mct(tc, mct_version)
            elif test_type == "LDT":
                result_tc = process_sha256_ldt(tc)
            else:
                raise ValueError(f"Unknown test type: {test_type}")
            result_tg["tests"].append(result_tc)

        result["testGroups"].append(result_tg)

    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  SHA2-256 results written to {result_path}")


def main():
    print("ACVP Test Vector Processor", flush=True)
    print("=" * 40, flush=True)

    print("\nProcessing AES-CBC...", flush=True)
    process_aes_cbc(
        "/app/prompts/aes_cbc_prompt.json",
        "/app/results/aes_cbc_results.json",
    )

    print("\nProcessing SHA2-256...", flush=True)
    process_sha256(
        "/app/prompts/sha256_prompt.json",
        "/app/results/sha256_results.json",
    )

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
