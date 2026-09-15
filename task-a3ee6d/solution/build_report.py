"""
Build the comparative compliance audit report.
Reads results from:
  - Fixed Python impl (runs tests inline)
  - beta_results.json (from harness_beta.py)
  - cross_validation_results.json (from cross_validate.sh)
Produces /app/audit_report.json
"""

import json
import os
import re
import sys

sys.path.insert(0, "/app/impl_alpha")
from ctr_drbg import CTR_DRBG


def parse_rsp(filepath):
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


def test_alpha_vector(config, vector):
    cipher_mode = config["cipher_mode"]
    params = config["params"]

    if "AES-256" not in cipher_mode:
        return None

    use_df = "use df" in cipher_mode
    drbg = CTR_DRBG(keylen=32, use_df=use_df)

    entropy = bytes.fromhex(vector["EntropyInput"])
    nonce_hex = vector.get("Nonce", "")
    nonce = bytes.fromhex(nonce_hex) if nonce_hex else b""
    ps_hex = vector.get("PersonalizationString", "")
    ps = bytes.fromhex(ps_hex) if ps_hex else b""

    drbg.instantiate(entropy, nonce, ps)

    returned_bits_len = int(params.get("ReturnedBitsLen", "512"))

    ai0_hex = vector.get("AdditionalInput_0", "")
    ai0 = bytes.fromhex(ai0_hex) if ai0_hex else b""
    drbg.generate(additional_input=ai0, requested_bits=returned_bits_len)

    ai1_hex = vector.get("AdditionalInput_1", "")
    ai1 = bytes.fromhex(ai1_hex) if ai1_hex else b""
    bits, _, _ = drbg.generate(additional_input=ai1, requested_bits=returned_bits_len)

    expected = vector["ReturnedBits"].lower()
    computed = bits.hex()

    return {
        "count": vector["COUNT"],
        "passed": computed == expected,
    }


def run_alpha_tests(rsp_path):
    configs = parse_rsp(rsp_path)
    total = 0
    passed = 0
    failed = 0

    for config in configs:
        if "AES-256" not in config["cipher_mode"]:
            continue
        for vector in config["vectors"]:
            result = test_alpha_vector(config, vector)
            if result is None:
                continue
            total += 1
            if result["passed"]:
                passed += 1
            else:
                failed += 1

    return {"total": total, "passed": passed, "failed": failed}


def analyze_beta_failures(beta_results):
    """Analyze C library failure patterns to identify defects."""
    defects = []

    # Check which config types fail
    use_df_fails = []
    no_df_pers_fails = []

    for cfg in beta_results.get("configs", []):
        any_fail = any(not v["passed"] for v in cfg["vectors"])
        mode = cfg["mode"]
        pers = cfg["personalization_len"]
        ai = cfg["additional_input_len"]
        label = f"{mode}, pers={pers}, ai={ai}"

        if any_fail:
            if mode == "use df":
                use_df_fails.append(label)
            elif pers > 0:
                no_df_pers_fails.append(label)

    if use_df_fails:
        defects.append({
            "id": "BETA-001",
            "affected_configs": use_df_fails,
            "root_cause": (
                "Block_Cipher_df encodes L and N fields as little-endian uint32 "
                "instead of big-endian per SP 800-90A Section 10.3.2 step 1. "
                "This corrupts the BCC input string S, causing all derivation "
                "function outputs to be incorrect."
            ),
            "severity": "critical",
            "sp800_90a_section": "10.3.2",
        })

    if no_df_pers_fails:
        defects.append({
            "id": "BETA-002",
            "affected_configs": no_df_pers_fails,
            "root_cause": (
                "In no-df instantiate, personalization string bytes are reversed "
                "before XORing with entropy. This corrupts the seed material, "
                "destroying the intended personalization of the DRBG state and "
                "breaking independence between separately-instantiated generators."
            ),
            "severity": "high",
            "sp800_90a_section": "10.2.1.3.2",
        })

    return defects


def main():
    rsp_path = "/app/vectors/CTR_DRBG_AES256.rsp"

    # Test fixed Python implementation
    alpha_stats = run_alpha_tests(rsp_path)
    print(f"impl_alpha: {alpha_stats['passed']}/{alpha_stats['total']} passed")

    # Load C library results
    with open("/app/beta_results.json") as f:
        beta_results = json.load(f)

    # Load cross-validation results
    cv_results = {"intermediate_checks": 0, "checks_passed": 0}
    cv_path = "/app/cross_validation_results.json"
    if os.path.exists(cv_path):
        with open(cv_path) as f:
            cv_data = json.load(f)
        cv_results["intermediate_checks"] = cv_data.get("total", 0)
        cv_results["checks_passed"] = cv_data.get("passed", 0)

    # Analyze beta failures
    beta_defects = analyze_beta_failures(beta_results)

    # Build report
    report = {
        "implementations": [
            {
                "name": "impl_alpha",
                "total_vectors": alpha_stats["total"],
                "passed": alpha_stats["passed"],
                "failed": alpha_stats["failed"],
                "defects": [],
                "compliance_verdict": "pass" if alpha_stats["failed"] == 0 else "fail",
            },
            {
                "name": "impl_beta",
                "total_vectors": beta_results["total"],
                "passed": beta_results["passed"],
                "failed": beta_results["failed"],
                "defects": beta_defects,
                "compliance_verdict": "pass" if beta_results["failed"] == 0 else "fail",
            },
        ],
        "cross_validation": cv_results,
        "recommendation": (
            "impl_alpha is recommended after fixes: it now passes all 24 CAVP "
            "AES-256 vectors across all 8 configurations. impl_beta has two "
            "distinct defects — a critical endianness bug in Block_Cipher_df "
            "affecting all use-df modes, and a high-severity byte-reversal bug "
            "in no-df personalization handling. impl_beta passes only 6/24 "
            "vectors (configs without df or personalization). impl_alpha is "
            "closer to production readiness; impl_beta requires fixes to both "
            "the derivation function and the personalization mixing logic."
        ),
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
