"""
CTR_DRBG C library test harness using Python ctypes.
Loads libctrdrbg.so, runs all CAVP AES-256 test vectors,
and reports per-configuration pass/fail results.
"""

import ctypes
import json
import os
import re
import sys


# ---- Load C library ----

lib = ctypes.CDLL("/app/impl_beta/libctrdrbg.so")


# ---- Define CTR_DRBG_CTX struct matching the C layout ----

class CTR_DRBG_CTX(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_uint8 * 32),
        ("v", ctypes.c_uint8 * 16),
        ("keylen", ctypes.c_int),
        ("seedlen", ctypes.c_int),
        ("use_df", ctypes.c_int),
    ]


# ---- Set function signatures ----

lib.ctr_drbg_init.argtypes = [
    ctypes.POINTER(CTR_DRBG_CTX), ctypes.c_int, ctypes.c_int
]
lib.ctr_drbg_init.restype = None

lib.ctr_drbg_instantiate.argtypes = [
    ctypes.POINTER(CTR_DRBG_CTX),
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
]
lib.ctr_drbg_instantiate.restype = ctypes.c_int

lib.ctr_drbg_generate.argtypes = [
    ctypes.POINTER(CTR_DRBG_CTX),
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
]
lib.ctr_drbg_generate.restype = ctypes.c_int

lib.ctr_drbg_get_state.argtypes = [
    ctypes.POINTER(CTR_DRBG_CTX),
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.POINTER(ctypes.c_uint8),
]
lib.ctr_drbg_get_state.restype = None


# ---- Helpers ----

def to_arr(data):
    """Convert bytes to ctypes uint8 array."""
    arr = (ctypes.c_uint8 * len(data))()
    for i, b in enumerate(data):
        arr[i] = b
    return arr


def parse_rsp(filepath):
    """Parse a CAVP .rsp file into config sections with test vectors."""
    with open(filepath) as f:
        lines = f.readlines()

    configs = []
    cur_cfg = None
    cur_vec = None
    ai_idx = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        m = re.match(r"\[(.+)\]", line)
        if m:
            val = m.group(1)
            if val.startswith("AES-") or val.startswith("3Key"):
                if cur_cfg and cur_vec:
                    cur_cfg["vectors"].append(cur_vec)
                    cur_vec = None
                if cur_cfg:
                    configs.append(cur_cfg)
                cur_cfg = {"cipher_mode": val, "params": {}, "vectors": []}
            elif cur_cfg is not None:
                k, v = val.split(" = ")
                cur_cfg["params"][k.strip()] = v.strip()
            continue

        if " = " in line:
            key, _, value = line.partition(" = ")
            key = key.strip()
            value = value.strip()

            if key == "COUNT":
                if cur_vec:
                    cur_cfg["vectors"].append(cur_vec)
                cur_vec = {"COUNT": int(value)}
                ai_idx = 0
            elif key == "AdditionalInput":
                cur_vec[f"AdditionalInput_{ai_idx}"] = value
                ai_idx += 1
            elif cur_vec is not None:
                cur_vec[key] = value

    if cur_vec and cur_cfg:
        cur_cfg["vectors"].append(cur_vec)
    if cur_cfg:
        configs.append(cur_cfg)

    return configs


def test_vector(config, vector):
    """Test a single CAVP vector against the C library via ctypes."""
    cipher_mode = config["cipher_mode"]
    params = config["params"]

    if "AES-256" not in cipher_mode:
        return None

    keylen = 32
    use_df = 1 if "use df" in cipher_mode else 0

    ctx = CTR_DRBG_CTX()
    lib.ctr_drbg_init(ctypes.byref(ctx), keylen, use_df)

    entropy = bytes.fromhex(vector["EntropyInput"])
    nonce_hex = vector.get("Nonce", "")
    nonce = bytes.fromhex(nonce_hex) if nonce_hex else b""
    ps_hex = vector.get("PersonalizationString", "")
    ps = bytes.fromhex(ps_hex) if ps_hex else b""

    e_arr = to_arr(entropy)
    n_arr = to_arr(nonce) if nonce else None
    p_arr = to_arr(ps) if ps else None

    lib.ctr_drbg_instantiate(
        ctypes.byref(ctx),
        e_arr, len(entropy),
        n_arr, len(nonce),
        p_arr, len(ps),
    )

    returned_bits_len = int(params.get("ReturnedBitsLen", "512"))
    output_len = returned_bits_len // 8

    # First generate call
    ai0_hex = vector.get("AdditionalInput_0", "")
    ai0 = bytes.fromhex(ai0_hex) if ai0_hex else b""
    out0 = (ctypes.c_uint8 * output_len)()
    a0_arr = to_arr(ai0) if ai0 else None
    lib.ctr_drbg_generate(
        ctypes.byref(ctx),
        out0, output_len,
        a0_arr, len(ai0),
    )

    # Second generate call
    ai1_hex = vector.get("AdditionalInput_1", "")
    ai1 = bytes.fromhex(ai1_hex) if ai1_hex else b""
    out1 = (ctypes.c_uint8 * output_len)()
    a1_arr = to_arr(ai1) if ai1 else None
    lib.ctr_drbg_generate(
        ctypes.byref(ctx),
        out1, output_len,
        a1_arr, len(ai1),
    )

    expected = vector["ReturnedBits"].lower()
    computed = bytes(out1[:output_len]).hex()

    return {
        "count": vector["COUNT"],
        "passed": computed == expected,
        "expected": expected,
        "computed": computed,
    }


def main():
    rsp_path = "/app/vectors/CTR_DRBG_AES256.rsp"
    configs = parse_rsp(rsp_path)

    results = {"total": 0, "passed": 0, "failed": 0, "configs": []}

    for config in configs:
        cipher_mode = config["cipher_mode"]
        if "AES-256" not in cipher_mode:
            continue

        params = config["params"]
        mode = "use df" if "use df" in cipher_mode else "no df"
        ps_len = int(params.get("PersonalizationStringLen", "0"))
        ai_len = int(params.get("AdditionalInputLen", "0"))

        cfg_result = {
            "cipher": "AES-256",
            "mode": mode,
            "personalization_len": ps_len,
            "additional_input_len": ai_len,
            "vectors": [],
        }

        for vector in config["vectors"]:
            result = test_vector(config, vector)
            if result is None:
                continue
            cfg_result["vectors"].append(result)
            results["total"] += 1
            if result["passed"]:
                results["passed"] += 1
            else:
                results["failed"] += 1

        if cfg_result["vectors"]:
            results["configs"].append(cfg_result)

    with open("/app/beta_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"impl_beta: {results['passed']}/{results['total']} passed, "
          f"{results['failed']} failed")

    for cfg in results["configs"]:
        status = "PASS" if all(v["passed"] for v in cfg["vectors"]) else "FAIL"
        print(f"  {status} - {cfg['mode']}, pers={cfg['personalization_len']}, "
              f"ai={cfg['additional_input_len']}")

    return results


if __name__ == "__main__":
    main()
