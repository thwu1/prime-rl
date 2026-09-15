#!/usr/bin/env python3

"""
ACVP compliance auditor: computes correct ACVP responses and generates
an audit report comparing them against a vendor's submitted responses.
Handles AFT and MCT test types across AES-GCM, HMAC-SHA2-256,
SHA2-256, and AES-CBC algorithm families.
"""

import json
import hmac
import hashlib
from pathlib import Path
from Crypto.Cipher import AES


def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


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


def process_sha256(vs):
    result = {
        "vsId": vs["vsId"],
        "algorithm": vs["algorithm"],
        "revision": vs["revision"],
        "testGroups": [],
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
                        md_arr[j] = hashlib.sha256(
                            md_arr[j-3] + md_arr[j-2] + md_arr[j-1]
                        ).digest()
                    current_seed = md_arr[1002]
                    results_array.append({
                        "md": current_seed.hex().upper()
                    })
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "resultsArray": results_array,
                })
        result["testGroups"].append(rtg)
    return result


def process_aes_cbc_mct(vs):
    result = {
        "vsId": vs["vsId"],
        "algorithm": vs["algorithm"],
        "revision": vs["revision"],
        "testGroups": [],
    }
    for tg in vs["testGroups"]:
        direction = tg["direction"]
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            key = bytes.fromhex(tc["key"])
            iv = bytes.fromhex(tc["iv"])
            if direction == "encrypt":
                pt = bytes.fromhex(tc["pt"])
                results_array = []
                cur_key, cur_iv, cur_pt = key, iv, pt
                for i in range(100):
                    ct_arr = [None] * 1000
                    pt_arr = [None] * 1001
                    pt_arr[0] = cur_pt
                    for j in range(1000):
                        cipher_iv = cur_iv if j == 0 else ct_arr[j-1]
                        cipher = AES.new(
                            cur_key, AES.MODE_CBC, iv=cipher_iv
                        )
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
                    key_len = len(cur_key)
                    if key_len == 16:
                        cur_key = xor_bytes(cur_key, ct_arr[999])
                    elif key_len == 24:
                        cur_key = xor_bytes(
                            cur_key, ct_arr[998][8:] + ct_arr[999]
                        )
                    else:
                        cur_key = xor_bytes(
                            cur_key, ct_arr[998] + ct_arr[999]
                        )
                    cur_iv = ct_arr[999]
                    cur_pt = ct_arr[998]
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "resultsArray": results_array,
                })
            else:
                ct = bytes.fromhex(tc["ct"])
                results_array = []
                cur_key, cur_iv, cur_ct = key, iv, ct
                for i in range(100):
                    pt_arr = [None] * 1000
                    ct_feed = [None] * 1001
                    ct_feed[0] = cur_ct
                    for j in range(1000):
                        cipher = AES.new(
                            cur_key, AES.MODE_CBC,
                            iv=cur_iv if j == 0 else pt_arr[j-1]
                        )
                        pt_arr[j] = cipher.decrypt(ct_feed[j])
                        if j == 0:
                            ct_feed[j+1] = cur_iv
                        else:
                            ct_feed[j+1] = pt_arr[j-1]
                    results_array.append({
                        "key": cur_key.hex().upper(),
                        "iv": cur_iv.hex().upper(),
                        "ct": cur_ct.hex().upper(),
                        "pt": pt_arr[999].hex().upper(),
                    })
                    key_len = len(cur_key)
                    if key_len == 16:
                        cur_key = xor_bytes(cur_key, pt_arr[999])
                    elif key_len == 24:
                        cur_key = xor_bytes(
                            cur_key, pt_arr[998][8:] + pt_arr[999]
                        )
                    else:
                        cur_key = xor_bytes(
                            cur_key, pt_arr[998] + pt_arr[999]
                        )
                    cur_iv = pt_arr[999]
                    cur_ct = pt_arr[998]
                rtg["tests"].append({
                    "tcId": tc["tcId"],
                    "resultsArray": results_array,
                })
        result["testGroups"].append(rtg)
    return result


PROCESSORS = {
    "ACVP-AES-GCM": process_aes_gcm,
    "HMAC-SHA2-256": process_hmac,
    "SHA2-256": process_sha256,
    "ACVP-AES-CBC": process_aes_cbc_mct,
}


def normalize_value(v):
    if isinstance(v, str):
        return v.upper()
    if isinstance(v, list):
        return [normalize_value(item) for item in v]
    if isinstance(v, dict):
        return {k: normalize_value(val) for k, val in v.items()}
    return v


def normalize_tc(tc):
    return {k: normalize_value(v) for k, v in tc.items()}


def build_tc_map(test_groups):
    m = {}
    for tg in test_groups:
        for tc in tg["tests"]:
            m[(tg["tgId"], tc["tcId"])] = tc
    return m


def main():
    vectors_dir = Path("/app/vectors")
    results_dir = Path("/app/results")
    vendor_dir = Path("/app/vendor_responses")
    results_dir.mkdir(parents=True, exist_ok=True)

    total_tc = 0
    total_disc = 0
    files_report = {}

    for vec_file in sorted(vectors_dir.glob("*.json")):
        with open(vec_file) as f:
            vs = json.load(f)

        processor = PROCESSORS.get(vs["algorithm"])
        if not processor:
            print(f"WARNING: Skipping unsupported algorithm: {vs['algorithm']}")
            continue

        correct = processor(vs)

        out_file = results_dir / vec_file.name
        with open(out_file, "w") as f:
            json.dump(correct, f, indent=2)
        print(f"Computed correct results for {vec_file.name}: {vs['algorithm']}")

        vendor_file = vendor_dir / vec_file.name
        with open(vendor_file) as f:
            vendor = json.load(f)

        correct_map = build_tc_map(correct["testGroups"])
        vendor_map = build_tc_map(vendor["testGroups"])

        disc_list = []
        for key in sorted(correct_map.keys()):
            total_tc += 1
            ctc = normalize_tc(correct_map[key])
            vtc = normalize_tc(vendor_map.get(key, {}))

            if ctc != vtc:
                total_disc += 1
                fields = {}
                all_fields = (set(ctc.keys()) | set(vtc.keys())) - {"tcId"}
                for field in sorted(all_fields):
                    cv = ctc.get(field)
                    vv = vtc.get(field)
                    if normalize_value(cv) != normalize_value(vv):
                        fields[field] = {
                            "vendor": str(vv) if vv is not None else "absent",
                            "correct": str(cv) if cv is not None else "absent",
                        }
                disc_list.append({
                    "tgId": key[0],
                    "tcId": key[1],
                    "fields": fields,
                })

        files_report[vec_file.name] = {"discrepancies": disc_list}

    report = {
        "total_test_cases": total_tc,
        "total_discrepancies": total_disc,
        "files": files_report,
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nAudit complete: {total_tc} test cases, {total_disc} discrepancies")


if __name__ == "__main__":
    main()
