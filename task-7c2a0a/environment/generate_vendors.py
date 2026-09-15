#!/usr/bin/env python3
"""
Generate three buggy vendor ACVP submissions for the conformance audit task.

Vendor Alpha bugs:
  A1: AES-CBC MCT 192-bit key shuffle uses MSB(64) of OUT[998] instead of LSB(64)
  A2: SHA-256 LDT hashes content once instead of repeating to fullLength

Vendor Beta bugs:
  B1: AES-CBC MCT decrypt uses plaintext as CBC chain IV instead of ciphertext
  B2: SHA-256 MCT ignores mctVersion="alternate", always uses standard algorithm

Vendor Gamma bugs:
  G1: AES-CBC MCT 256-bit key shuffle swaps OUT[998] and OUT[999]
  G2: SHA-256 MCT does not update seed between outer iterations
"""

import json
import hashlib
import os
import sys
from Crypto.Cipher import AES


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


# ---------------------------------------------------------------------------
# Key shuffle variants
# ---------------------------------------------------------------------------

def ks_correct(key, out_prev, out_last):
    kl = len(key) * 8
    if kl == 128:
        return xor_bytes(key, out_last)
    elif kl == 192:
        return xor_bytes(key, out_prev[8:] + out_last)
    else:
        return xor_bytes(key, out_prev + out_last)


def ks_alpha(key, out_prev, out_last):
    """Bug A1: 192-bit uses MSB(64) instead of LSB(64)"""
    kl = len(key) * 8
    if kl == 128:
        return xor_bytes(key, out_last)
    elif kl == 192:
        return xor_bytes(key, out_prev[:8] + out_last)  # MSB bug
    else:
        return xor_bytes(key, out_prev + out_last)


def ks_gamma(key, out_prev, out_last):
    """Bug G1: 256-bit swaps OUT[998] and OUT[999]"""
    kl = len(key) * 8
    if kl == 128:
        return xor_bytes(key, out_last)
    elif kl == 192:
        return xor_bytes(key, out_prev[8:] + out_last)
    else:
        return xor_bytes(key, out_last + out_prev)  # swapped bug


# ---------------------------------------------------------------------------
# AES-CBC MCT encrypt (same for all vendors, key_shuffle varies)
# ---------------------------------------------------------------------------

def mct_encrypt(tc, key_shuffle_fn):
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
        key = key_shuffle_fn(key, ct_prev, ct_last)
        iv = ct_last
        pt = ct_prev
    return {"tcId": tc["tcId"], "resultsArray": results}


# ---------------------------------------------------------------------------
# AES-CBC MCT decrypt variants
# ---------------------------------------------------------------------------

def mct_decrypt_correct(tc, key_shuffle_fn):
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
            cbc_iv = ct_cur  # correct: chain IV = ciphertext input
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
        key = key_shuffle_fn(key, pt_sl, pt_last)
        iv = pt_last
        ct = pt_sl
    return {"tcId": tc["tcId"], "resultsArray": results}


def mct_decrypt_beta(tc, key_shuffle_fn):
    """Bug B1: chain IV = plaintext output instead of ciphertext input."""
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
            cbc_iv = pt  # BUG: should be ct_cur
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
        key = key_shuffle_fn(key, pt_sl, pt_last)
        iv = pt_last
        ct = pt_sl
    return {"tcId": tc["tcId"], "resultsArray": results}


# ---------------------------------------------------------------------------
# AES-CBC AFT (correct for all vendors)
# ---------------------------------------------------------------------------

def aft_encrypt(tc):
    k = bytes.fromhex(tc["key"])
    iv = bytes.fromhex(tc["iv"])
    pt = bytes.fromhex(tc["pt"])
    ct = AES.new(k, AES.MODE_CBC, iv=iv).encrypt(pt)
    return {"tcId": tc["tcId"], "ct": ct.hex().upper()}


def aft_decrypt(tc):
    k = bytes.fromhex(tc["key"])
    iv = bytes.fromhex(tc["iv"])
    ct = bytes.fromhex(tc["ct"])
    pt = AES.new(k, AES.MODE_CBC, iv=iv).decrypt(ct)
    return {"tcId": tc["tcId"], "pt": pt.hex().upper()}


# ---------------------------------------------------------------------------
# SHA-256 AFT (correct for all vendors)
# ---------------------------------------------------------------------------

def sha_aft(tc):
    msg_hex = tc["msg"]
    msg_len = tc["len"]
    if msg_len == 0:
        mb = b""
    else:
        mb = bytes.fromhex(msg_hex)[:msg_len // 8]
    return {"tcId": tc["tcId"], "md": hashlib.sha256(mb).hexdigest().upper()}


# ---------------------------------------------------------------------------
# SHA-256 MCT variants
# ---------------------------------------------------------------------------

def sha_mct_correct(tc, mct_version):
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


def sha_mct_beta(tc, mct_version):
    """Bug B2: ignores mctVersion, always uses standard."""
    seed = bytes.fromhex(tc["msg"])
    results = []
    for j in range(100):
        a, b, c = seed[:], seed[:], seed[:]
        for _ in range(1000):
            msg = a + b + c  # no alternate handling
            md = hashlib.sha256(msg).digest()
            a, b, c = b, c, md
        results.append({"md": c.hex().upper()})
        seed = c
    return {"tcId": tc["tcId"], "resultsArray": results}


def sha_mct_gamma(tc, mct_version):
    """Bug G2: does not update seed between outer iterations."""
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
        # BUG: seed = c is missing; seed stays as original
    return {"tcId": tc["tcId"], "resultsArray": results}


# ---------------------------------------------------------------------------
# SHA-256 LDT variants
# ---------------------------------------------------------------------------

def sha_ldt_correct(tc):
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


def sha_ldt_alpha(tc):
    """Bug A2: hashes content once, no expansion."""
    content = bytes.fromhex(tc["largeMsg"]["content"])
    return {"tcId": tc["tcId"],
            "md": hashlib.sha256(content).hexdigest().upper()}


# ---------------------------------------------------------------------------
# Full processors
# ---------------------------------------------------------------------------

def process_aes(prompt, ks_fn, dec_fn):
    result = {
        "vsId": prompt["vsId"], "algorithm": prompt["algorithm"],
        "revision": prompt["revision"], "isSample": prompt["isSample"],
        "testGroups": [],
    }
    for tg in prompt["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            if tg["testType"] == "AFT":
                if tg["direction"] == "encrypt":
                    rtg["tests"].append(aft_encrypt(tc))
                else:
                    rtg["tests"].append(aft_decrypt(tc))
            elif tg["testType"] == "MCT":
                if tg["direction"] == "encrypt":
                    rtg["tests"].append(mct_encrypt(tc, ks_fn))
                else:
                    rtg["tests"].append(dec_fn(tc, ks_fn))
        result["testGroups"].append(rtg)
    return result


def process_sha(prompt, mct_fn, ldt_fn, ldt_cache=None):
    result = {
        "vsId": prompt["vsId"], "algorithm": prompt["algorithm"],
        "revision": prompt["revision"], "isSample": prompt["isSample"],
        "testGroups": [],
    }
    for tg in prompt["testGroups"]:
        rtg = {"tgId": tg["tgId"], "tests": []}
        for tc in tg["tests"]:
            if tg["testType"] == "AFT":
                rtg["tests"].append(sha_aft(tc))
            elif tg["testType"] == "MCT":
                mv = tg.get("mctVersion", "standard")
                rtg["tests"].append(mct_fn(tc, mv))
            elif tg["testType"] == "LDT":
                if ldt_cache and tc["tcId"] in ldt_cache:
                    rtg["tests"].append(ldt_cache[tc["tcId"]])
                else:
                    r = ldt_fn(tc)
                    if ldt_cache is not None:
                        ldt_cache[tc["tcId"]] = r
                    rtg["tests"].append(r)
        result["testGroups"].append(rtg)
    return result


def write_json(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    aes_p = json.load(open("/tmp/aes_cbc_prompt.json"))
    sha_p = json.load(open("/tmp/sha256_prompt.json"))

    # Pre-compute correct LDT results (expensive, ~50-80s)
    print("Pre-computing SHA-256 LDT (large data hashing)...", flush=True)
    ldt_cache = {}
    for tg in sha_p["testGroups"]:
        if tg["testType"] == "LDT":
            for tc in tg["tests"]:
                print(f"  LDT tcId={tc['tcId']} "
                      f"fullLength={tc['largeMsg']['fullLength']}...",
                      flush=True)
                ldt_cache[tc["tcId"]] = sha_ldt_correct(tc)
    print("LDT pre-computation done.", flush=True)

    # Vendor Alpha: A1=wrong 192 key shuffle, A2=LDT no expand
    print("Generating vendor Alpha...", flush=True)
    write_json(process_aes(aes_p, ks_alpha, mct_decrypt_correct),
               "/tmp/vendor_alpha/aes_cbc_results.json")
    write_json(process_sha(sha_p, sha_mct_correct, sha_ldt_alpha),
               "/tmp/vendor_alpha/sha256_results.json")

    # Vendor Beta: B1=wrong decrypt CBC chain, B2=MCT ignores version
    print("Generating vendor Beta...", flush=True)
    write_json(process_aes(aes_p, ks_correct, mct_decrypt_beta),
               "/tmp/vendor_beta/aes_cbc_results.json")
    write_json(process_sha(sha_p, sha_mct_beta, sha_ldt_correct,
                           ldt_cache=ldt_cache),
               "/tmp/vendor_beta/sha256_results.json")

    # Vendor Gamma: G1=wrong 256 key shuffle, G2=MCT no seed update
    print("Generating vendor Gamma...", flush=True)
    write_json(process_aes(aes_p, ks_gamma, mct_decrypt_correct),
               "/tmp/vendor_gamma/aes_cbc_results.json")
    write_json(process_sha(sha_p, sha_mct_gamma, sha_ldt_correct,
                           ldt_cache=ldt_cache),
               "/tmp/vendor_gamma/sha256_results.json")

    print("All vendor submissions generated.", flush=True)


if __name__ == "__main__":
    main()
