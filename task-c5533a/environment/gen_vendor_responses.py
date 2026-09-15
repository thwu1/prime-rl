#!/usr/bin/env python3
"""Generate vendor responses with realistic implementation flaws for the ACVP audit task.
This script runs ONLY during Docker build and is NOT present in the final image."""
import json
import hmac
import hashlib
from Crypto.Cipher import AES


def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def gen_aes_gcm():
    with open("/app/vectors/aes_gcm.json") as f:
        vs = json.load(f)
    result = {
        "vsId": vs["vsId"], "algorithm": vs["algorithm"],
        "revision": vs["revision"], "testGroups": [],
    }
    for tg in vs["testGroups"]:
        direction = tg["direction"]
        tag_len_bytes = tg["tagLen"] // 8
        iv_len = tg["ivLen"]
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
                # BUG: truncate IV to 12 bytes for non-96-bit IVs (wrong J0),
                # and skip tag verification entirely (security vulnerability)
                nonce = iv[:12] if iv_len != 96 else iv
                cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=tag_len_bytes)
                cipher.update(aad)
                pt = cipher.decrypt(ct)
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "pt": pt.hex().upper(),
                })
        result["testGroups"].append(rtg)
    return result


def gen_hmac():
    with open("/app/vectors/hmac_sha256.json") as f:
        vs = json.load(f)
    result = {
        "vsId": vs["vsId"], "algorithm": vs["algorithm"],
        "revision": vs["revision"], "testGroups": [],
    }
    for tg in vs["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            key_bytes = bytes.fromhex(tc["key"])
            msg = bytes.fromhex(tc["msg"]) if tc.get("msg") else b""
            h = hmac.new(key_bytes, msg, "sha256")
            # BUG: outputs full digest instead of truncating to macLen
            mac_val = h.digest()
            rtg["tests"].append({
                "tcId": tc["tcId"],
                "mac": mac_val.hex().upper(),
            })
        result["testGroups"].append(rtg)
    return result


def gen_sha256():
    with open("/app/vectors/sha256.json") as f:
        vs = json.load(f)
    result = {
        "vsId": vs["vsId"], "algorithm": vs["algorithm"],
        "revision": vs["revision"], "testGroups": [],
    }
    for tg in vs["testGroups"]:
        test_type = tg["testType"]
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            if test_type == "AFT":
                msg = bytes.fromhex(tc["msg"]) if tc.get("msg") else b""
                md = hashlib.sha256(msg).hexdigest().upper()
                rtg["tests"].append({"tcId": tc["tcId"], "md": md})
            elif test_type == "MCT":
                seed = bytes.fromhex(tc["msg"])
                results_array = []
                current_seed = seed
                for i in range(100):
                    md_arr = [None] * 1003
                    md_arr[0] = md_arr[1] = md_arr[2] = current_seed
                    for j in range(3, 1003):
                        # BUG: 2-message window instead of 3-message window
                        # Correct: SHA-256(MD[j-3] || MD[j-2] || MD[j-1])
                        # Buggy:   SHA-256(MD[j-2] || MD[j-1])
                        md_arr[j] = hashlib.sha256(
                            md_arr[j-2] + md_arr[j-1]
                        ).digest()
                    current_seed = md_arr[1002]
                    results_array.append({"md": current_seed.hex().upper()})
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "resultsArray": results_array,
                })
        result["testGroups"].append(rtg)
    return result


def gen_aes_cbc_mct():
    with open("/app/vectors/aes_cbc_mct.json") as f:
        vs = json.load(f)
    result = {
        "vsId": vs["vsId"], "algorithm": vs["algorithm"],
        "revision": vs["revision"], "testGroups": [],
    }
    for tg in vs["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            key = bytes.fromhex(tc["key"])
            iv = bytes.fromhex(tc["iv"])
            pt = bytes.fromhex(tc["pt"])
            results_array = []
            cur_key, cur_iv, cur_pt = key, iv, pt
            for i in range(100):
                ct_arr = [None] * 1000
                pt_arr = [None] * 1001
                pt_arr[0] = cur_pt
                for j in range(1000):
                    cipher_iv = cur_iv if j == 0 else ct_arr[j-1]
                    cipher = AES.new(cur_key, AES.MODE_CBC, iv=cipher_iv)
                    ct_arr[j] = cipher.encrypt(pt_arr[j])
                    if j == 0:
                        pt_arr[j+1] = cur_iv
                    else:
                        pt_arr[j+1] = ct_arr[j-1]
                results_array.append({
                    "key": cur_key.hex().upper(),
                    "iv": cur_iv.hex().upper(),
                    "pt": cur_pt.hex().upper(),
                    "ct": ct_arr[999].hex().upper(),
                })
                # BUG: XOR key with CT[998] instead of CT[999]
                # Correct: Key[i+1] = Key[i] XOR CT[999]
                # Buggy:   Key[i+1] = Key[i] XOR CT[998]
                cur_key = xor_bytes(cur_key, ct_arr[998])
                cur_iv = ct_arr[999]
                cur_pt = ct_arr[998]
            rtg["tests"].append({
                "tcId": tc["tcId"],
                "resultsArray": results_array,
            })
        result["testGroups"].append(rtg)
    return result


def main():
    import os
    os.makedirs("/app/vendor_responses", exist_ok=True)
    with open("/app/vendor_responses/aes_gcm.json", "w") as f:
        json.dump(gen_aes_gcm(), f, indent=2)
    with open("/app/vendor_responses/hmac_sha256.json", "w") as f:
        json.dump(gen_hmac(), f, indent=2)
    with open("/app/vendor_responses/sha256.json", "w") as f:
        json.dump(gen_sha256(), f, indent=2)
    with open("/app/vendor_responses/aes_cbc_mct.json", "w") as f:
        json.dump(gen_aes_cbc_mct(), f, indent=2)
    print("Generated vendor responses")


if __name__ == "__main__":
    main()
