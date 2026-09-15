#!/usr/bin/env python3

"""
ACVP test vector processor supporting:
  - ACVP-AES-GCM (encrypt/decrypt with variable tag and IV lengths)
  - HMAC-SHA2-256 (with variable-length MAC truncation)
  - PBKDF (PBKDF2 with configurable HMAC algorithm)
"""

import json
import hmac
import hashlib
from pathlib import Path
from Crypto.Cipher import AES


HMAC_ALG_MAP = {
    "SHA-1": "sha1",
    "SHA2-224": "sha224",
    "SHA2-256": "sha256",
    "SHA2-384": "sha384",
    "SHA2-512": "sha512",
    "SHA2-512/224": "sha512_224",
    "SHA2-512/256": "sha512_256",
}


def process_aes_gcm(vs):
    result = {
        "vsId": vs["vsId"],
        "algorithm": vs["algorithm"],
        "revision": vs["revision"],
        "testGroups": [],
    }

    for tg in vs["testGroups"]:
        direction = tg["direction"]
        tag_len_bytes = tg["tagLen"] // 8
        rtg = {"tgId": tg["tgId"], "tests": []}

        for tc in tg["tests"]:
            key = bytes.fromhex(tc["key"])
            iv = bytes.fromhex(tc["iv"])
            aad = bytes.fromhex(tc["aad"]) if tc.get("aad") else b""

            if direction == "encrypt":
                pt = bytes.fromhex(tc["pt"]) if tc.get("pt") else b""
                cipher = AES.new(key, AES.MODE_GCM, nonce=iv, mac_len=tag_len_bytes)
                cipher.update(aad)
                ct, tag = cipher.encrypt_and_digest(pt)
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "ct": ct.hex().upper(),
                    "tag": tag.hex().upper(),
                })
            else:
                ct = bytes.fromhex(tc["ct"]) if tc.get("ct") else b""
                tag = bytes.fromhex(tc["tag"])
                cipher = AES.new(key, AES.MODE_GCM, nonce=iv, mac_len=tag_len_bytes)
                cipher.update(aad)
                try:
                    pt = cipher.decrypt_and_verify(ct, tag)
                    rtg["tests"].append({
                        "tcId": tc["tcId"],
                        "pt": pt.hex().upper(),
                    })
                except (ValueError, KeyError):
                    rtg["tests"].append({
                        "tcId": tc["tcId"],
                        "testPassed": False,
                    })

        result["testGroups"].append(rtg)

    return result


def process_hmac(vs):
    alg_name = vs["algorithm"]
    if "SHA2-256" in alg_name:
        hash_func = "sha256"
    elif "SHA2-384" in alg_name:
        hash_func = "sha384"
    elif "SHA2-512" in alg_name:
        hash_func = "sha512"
    elif "SHA2-224" in alg_name:
        hash_func = "sha224"
    elif "SHA-1" in alg_name:
        hash_func = "sha1"
    else:
        raise ValueError(f"Unsupported HMAC algorithm: {alg_name}")

    result = {
        "vsId": vs["vsId"],
        "algorithm": vs["algorithm"],
        "revision": vs["revision"],
        "testGroups": [],
    }

    for tg in vs["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}

        for tc in tg["tests"]:
            key = bytes.fromhex(tc["key"])
            msg = bytes.fromhex(tc["msg"]) if tc.get("msg") else b""
            mac_len_bytes = tc["macLen"] // 8

            h = hmac.new(key, msg, hash_func)
            mac_val = h.digest()[:mac_len_bytes]

            rtg["tests"].append({
                "tcId": tc["tcId"],
                "mac": mac_val.hex().upper(),
            })

        result["testGroups"].append(rtg)

    return result


def process_pbkdf(vs):
    result = {
        "vsId": vs["vsId"],
        "algorithm": vs["algorithm"],
        "revision": vs["revision"],
        "testGroups": [],
    }

    for tg in vs["testGroups"]:
        hmac_alg = tg["hmacAlg"]
        hash_name = HMAC_ALG_MAP.get(hmac_alg)
        if not hash_name:
            raise ValueError(f"Unsupported PBKDF HMAC algorithm: {hmac_alg}")

        rtg = {"tgId": tg["tgId"], "tests": []}

        for tc in tg["tests"]:
            password = tc["password"].encode("utf-8")
            salt = bytes.fromhex(tc["salt"])
            iterations = tc["iterationCount"]
            key_len_bytes = tc["keyLen"] // 8

            dk = hashlib.pbkdf2_hmac(
                hash_name, password, salt, iterations, dklen=key_len_bytes
            )

            rtg["tests"].append({
                "tcId": tc["tcId"],
                "derivedKey": dk.hex().upper(),
            })

        result["testGroups"].append(rtg)

    return result


PROCESSORS = {
    "ACVP-AES-GCM": process_aes_gcm,
    "HMAC-SHA2-256": process_hmac,
    "PBKDF": process_pbkdf,
}


def main():
    vectors_dir = Path("/app/vectors")
    results_dir = Path("/app/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    for vec_file in sorted(vectors_dir.glob("*.json")):
        with open(vec_file) as f:
            vs = json.load(f)

        alg = vs["algorithm"]
        processor = PROCESSORS.get(alg)
        if not processor:
            print(f"WARNING: Skipping unsupported algorithm: {alg}")
            continue

        result = processor(vs)

        out_file = results_dir / vec_file.name
        with open(out_file, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Processed {vec_file.name}: {alg}")


if __name__ == "__main__":
    main()
