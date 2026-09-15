#!/usr/bin/env python3

"""
ACVP Conformance Auditor — generates correct reference responses,
compares vendor submissions, diagnoses bugs, and produces the audit report.
"""

import json
import hashlib
import os
from Crypto.Cipher import AES


# ===========================================================================
# Core crypto helpers
# ===========================================================================

def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def aes_ecb_enc(key, block):
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def aes_ecb_dec(key, block):
    return AES.new(key, AES.MODE_ECB).decrypt(block)


def cbc_enc1(key, iv, pt):
    return aes_ecb_enc(key, xor_bytes(pt, iv))


def cbc_dec1(key, iv, ct):
    return xor_bytes(aes_ecb_dec(key, ct), iv)


def key_shuffle(key, out_prev, out_last):
    kl = len(key) * 8
    if kl == 128:
        return xor_bytes(key, out_last)
    elif kl == 192:
        return xor_bytes(key, out_prev[8:] + out_last)
    else:
        return xor_bytes(key, out_prev + out_last)


# ===========================================================================
# AES-CBC processors
# ===========================================================================

def process_aft(tc, direction):
    k = bytes.fromhex(tc["key"])
    iv = bytes.fromhex(tc["iv"])
    if direction == "encrypt":
        pt = bytes.fromhex(tc["pt"])
        ct = AES.new(k, AES.MODE_CBC, iv=iv).encrypt(pt)
        return {"tcId": tc["tcId"], "ct": ct.hex().upper()}
    else:
        ct = bytes.fromhex(tc["ct"])
        pt = AES.new(k, AES.MODE_CBC, iv=iv).decrypt(ct)
        return {"tcId": tc["tcId"], "pt": pt.hex().upper()}


def process_mct_encrypt(tc):
    key = bytes.fromhex(tc["key"])
    iv = bytes.fromhex(tc["iv"])
    pt = bytes.fromhex(tc["pt"])
    results = []
    for i in range(100):
        entry = {"key": key.hex().upper(), "iv": iv.hex().upper(),
                 "pt": pt.hex().upper()}
        ct_prev = None
        ct_last = None
        for j in range(1000):
            if j == 0:
                ct = cbc_enc1(key, iv, pt)
                npt = iv
            else:
                ct = cbc_enc1(key, ct_last, pt)
                npt = ct_last
            ct_prev = ct_last
            ct_last = ct
            pt = npt
        entry["ct"] = ct_last.hex().upper()
        results.append(entry)
        key = key_shuffle(key, ct_prev, ct_last)
        iv = ct_last
        pt = ct_prev
    return {"tcId": tc["tcId"], "resultsArray": results}


def process_mct_decrypt(tc):
    key = bytes.fromhex(tc["key"])
    iv = bytes.fromhex(tc["iv"])
    ct = bytes.fromhex(tc["ct"])
    results = []
    for i in range(100):
        entry = {"key": key.hex().upper(), "iv": iv.hex().upper(),
                 "ct": ct.hex().upper()}
        cbc_iv = iv
        ct_cur = ct
        pt_prev = None
        pt_sl = None
        pt_last = None
        for j in range(1000):
            pt = cbc_dec1(key, cbc_iv, ct_cur)
            cbc_iv = ct_cur
            if j == 0:
                nct = iv
            else:
                nct = pt_prev
            pt_sl = pt_last
            pt_last = pt
            pt_prev = pt
            ct_cur = nct
        entry["pt"] = pt_last.hex().upper()
        results.append(entry)
        key = key_shuffle(key, pt_sl, pt_last)
        iv = pt_last
        ct = pt_sl
    return {"tcId": tc["tcId"], "resultsArray": results}


# ===========================================================================
# SHA2-256 processors
# ===========================================================================

def process_sha_aft(tc):
    ml = tc["len"]
    if ml == 0:
        mb = b""
    else:
        mb = bytes.fromhex(tc["msg"])[:ml // 8]
    return {"tcId": tc["tcId"], "md": hashlib.sha256(mb).hexdigest().upper()}


def process_sha_mct(tc, mct_version):
    seed = bytes.fromhex(tc["msg"])
    isl = tc["len"]
    results = []
    for j in range(100):
        a, b, c = seed[:], seed[:], seed[:]
        for _ in range(1000):
            msg = a + b + c
            if mct_version == "alternate":
                mbl = len(msg) * 8
                if mbl >= isl:
                    msg = msg[:isl // 8]
                else:
                    msg = msg + b"\x00" * ((isl - mbl) // 8)
            md = hashlib.sha256(msg).digest()
            a, b, c = b, c, md
        results.append({"md": c.hex().upper()})
        seed = c
    return {"tcId": tc["tcId"], "resultsArray": results}


def process_sha_ldt(tc):
    lm = tc["largeMsg"]
    content = bytes.fromhex(lm["content"])
    cl = lm["contentLength"] // 8
    fl = lm["fullLength"] // 8
    h = hashlib.sha256()
    cr = max(1, (1024 * 1024) // cl)
    chunk = content * cr
    cs = len(chunk)
    w = 0
    while w + cs <= fl:
        h.update(chunk)
        w += cs
    rem = fl - w
    if rem > 0:
        reps = rem // cl
        if reps > 0:
            h.update(content * reps)
    return {"tcId": tc["tcId"], "md": h.hexdigest().upper()}


# ===========================================================================
# Full reference generation
# ===========================================================================

def generate_aes_reference(prompt):
    result = {
        "vsId": prompt["vsId"], "algorithm": prompt["algorithm"],
        "revision": prompt["revision"], "isSample": prompt["isSample"],
        "testGroups": [],
    }
    for tg in prompt["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        print(f"  AES tgId={tg['tgId']} ({tg['testType']}, "
              f"{tg['direction']}, {tg['keyLen']}-bit)...", flush=True)
        for tc in tg["tests"]:
            if tg["testType"] == "AFT":
                rtg["tests"].append(process_aft(tc, tg["direction"]))
            elif tg["testType"] == "MCT":
                if tg["direction"] == "encrypt":
                    rtg["tests"].append(process_mct_encrypt(tc))
                else:
                    rtg["tests"].append(process_mct_decrypt(tc))
        result["testGroups"].append(rtg)
    return result


def generate_sha_reference(prompt):
    result = {
        "vsId": prompt["vsId"], "algorithm": prompt["algorithm"],
        "revision": prompt["revision"], "isSample": prompt["isSample"],
        "testGroups": [],
    }
    for tg in prompt["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        print(f"  SHA tgId={tg['tgId']} ({tg['testType']})...", flush=True)
        for tc in tg["tests"]:
            if tg["testType"] == "AFT":
                rtg["tests"].append(process_sha_aft(tc))
            elif tg["testType"] == "MCT":
                mv = tg.get("mctVersion", "standard")
                rtg["tests"].append(process_sha_mct(tc, mv))
            elif tg["testType"] == "LDT":
                rtg["tests"].append(process_sha_ldt(tc))
        result["testGroups"].append(rtg)
    return result


# ===========================================================================
# Vendor comparison & diagnosis
# ===========================================================================

def compare_test_group(ref_tg, vendor_tg):
    """Compare a reference test group against a vendor test group.
    Returns True if all test cases match, False otherwise."""
    if len(ref_tg["tests"]) != len(vendor_tg["tests"]):
        return False
    for rt, vt in zip(ref_tg["tests"], vendor_tg["tests"]):
        if rt.get("tcId") != vt.get("tcId"):
            return False
        # Compare all value fields
        for field in ["ct", "pt", "md"]:
            if field in rt:
                if rt[field].upper() != vt.get(field, "").upper():
                    return False
        # Compare resultsArray for MCT
        if "resultsArray" in rt:
            rra = rt["resultsArray"]
            vra = vt.get("resultsArray", [])
            if len(rra) != len(vra):
                return False
            for ri, vi in zip(rra, vra):
                for f in ["key", "iv", "pt", "ct", "md"]:
                    if f in ri:
                        if ri[f].upper() != vi.get(f, "").upper():
                            return False
    return True


def find_failing_groups(ref_data, vendor_data):
    """Find test group IDs where vendor differs from reference."""
    failing = []
    for ref_tg in ref_data["testGroups"]:
        tg_id = ref_tg["tgId"]
        vtg = None
        for vt in vendor_data["testGroups"]:
            if vt["tgId"] == tg_id:
                vtg = vt
                break
        if vtg is None or not compare_test_group(ref_tg, vtg):
            failing.append(tg_id)
    return sorted(failing)


def classify_aes_bugs(failing_groups, prompt):
    """Classify AES-CBC bugs from the set of failing test groups."""
    # Build a map of tgId -> (testType, direction, keyLen)
    tg_info = {}
    for tg in prompt["testGroups"]:
        tg_info[tg["tgId"]] = (tg["testType"], tg["direction"], tg["keyLen"])

    mct_failing = [g for g in failing_groups if tg_info[g][0] == "MCT"]
    aft_failing = [g for g in failing_groups if tg_info[g][0] == "AFT"]

    if not mct_failing:
        return []

    # Check if only decrypt MCTs fail -> cbc_chain
    directions = set(tg_info[g][1] for g in mct_failing)
    key_lens = set(tg_info[g][2] for g in mct_failing)

    if directions == {"decrypt"} and len(mct_failing) == 3:
        return [{"affected_algorithm": "AES-CBC",
                 "affected_groups": sorted(mct_failing),
                 "category": "cbc_chain"}]

    # Check if only specific key lengths fail -> key_schedule
    if directions in [{"encrypt", "decrypt"}, {"encrypt"}, {"decrypt"}]:
        # Group by key length
        by_kl = {}
        for g in mct_failing:
            kl = tg_info[g][2]
            by_kl.setdefault(kl, []).append(g)

        # If all failing groups share one key length -> key_schedule
        if len(key_lens) == 1:
            return [{"affected_algorithm": "AES-CBC",
                     "affected_groups": sorted(mct_failing),
                     "category": "key_schedule"}]

    return [{"affected_algorithm": "AES-CBC",
             "affected_groups": sorted(mct_failing),
             "category": "key_schedule"}]


def classify_sha_bugs(failing_groups, prompt):
    """Classify SHA2-256 bugs from the set of failing test groups."""
    tg_info = {}
    for tg in prompt["testGroups"]:
        tg_info[tg["tgId"]] = tg["testType"]

    bugs = []
    for g in failing_groups:
        tt = tg_info[g]
        if tt == "LDT":
            bugs.append({"affected_algorithm": "SHA2-256",
                         "affected_groups": [g],
                         "category": "ldt_expansion"})
        elif tt == "MCT":
            # Need to distinguish mct_algorithm from mct_state
            # Check vendor MCT output: if all 100 results are identical -> mct_state
            bugs.append({"affected_algorithm": "SHA2-256",
                         "affected_groups": [g],
                         "category": "_mct_placeholder"})
    return bugs


def diagnose_sha_mct_bug(vendor_sha, tg_id):
    """Distinguish mct_algorithm from mct_state by examining vendor output."""
    vtg = None
    for tg in vendor_sha["testGroups"]:
        if tg["tgId"] == tg_id:
            vtg = tg
            break
    if vtg is None or not vtg["tests"]:
        return "mct_algorithm"

    ra = vtg["tests"][0].get("resultsArray", [])
    if len(ra) < 2:
        return "mct_algorithm"

    # If all 100 MCT results are identical -> seed not updated -> mct_state
    first_md = ra[0].get("md", "")
    all_same = all(r.get("md", "") == first_md for r in ra)
    if all_same:
        return "mct_state"
    else:
        return "mct_algorithm"


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 50, flush=True)
    print("ACVP Conformance Auditor", flush=True)
    print("=" * 50, flush=True)

    aes_prompt = json.load(open("/app/prompts/aes_cbc_prompt.json"))
    sha_prompt = json.load(open("/app/prompts/sha256_prompt.json"))

    # Step 1: Generate correct reference results
    print("\n[1/3] Generating correct AES-CBC reference...", flush=True)
    aes_ref = generate_aes_reference(aes_prompt)

    print("\n[2/3] Generating correct SHA2-256 reference...", flush=True)
    sha_ref = generate_sha_reference(sha_prompt)

    # Write reference results
    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/aes_cbc_results.json", "w") as f:
        json.dump(aes_ref, f, indent=2)
    with open("/app/results/sha256_results.json", "w") as f:
        json.dump(sha_ref, f, indent=2)
    print("\nReference results written.", flush=True)

    # Step 2: Compare vendor submissions and diagnose
    print("\n[3/3] Auditing vendor submissions...", flush=True)
    audit_report = {}

    for vendor in ["alpha", "beta", "gamma"]:
        print(f"\n  Auditing vendor {vendor}...", flush=True)
        vendor_aes = json.load(
            open(f"/app/vendor_submissions/{vendor}/aes_cbc_results.json"))
        vendor_sha = json.load(
            open(f"/app/vendor_submissions/{vendor}/sha256_results.json"))

        aes_failing = find_failing_groups(aes_ref, vendor_aes)
        sha_failing = find_failing_groups(sha_ref, vendor_sha)

        print(f"    AES failing groups: {aes_failing}", flush=True)
        print(f"    SHA failing groups: {sha_failing}", flush=True)

        # Classify bugs
        aes_bugs = classify_aes_bugs(aes_failing, aes_prompt)
        sha_bugs = classify_sha_bugs(sha_failing, sha_prompt)

        # Refine SHA MCT classification
        for bug in sha_bugs:
            if bug["category"] == "_mct_placeholder":
                for g in bug["affected_groups"]:
                    bug["category"] = diagnose_sha_mct_bug(vendor_sha, g)

        all_bugs = aes_bugs + sha_bugs
        for bug in all_bugs:
            print(f"    Bug: {bug['affected_algorithm']} "
                  f"groups={bug['affected_groups']} "
                  f"category={bug['category']}", flush=True)

        audit_report[f"vendor_{vendor}"] = {
            "aes_cbc_failing_groups": aes_failing,
            "sha256_failing_groups": sha_failing,
            "bugs": all_bugs,
        }

    with open("/app/audit_report.json", "w") as f:
        json.dump(audit_report, f, indent=2)

    print("\n\nAudit report written to /app/audit_report.json", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
