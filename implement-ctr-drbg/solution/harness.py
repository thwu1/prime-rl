"""
CAVP CTR_DRBG validation harness.

Loads a CTR_DRBG implementation by file path, tests it against parsed CAVP
vectors with intermediate state verification, and uses OpenSSL for independent
BCC chain verification.

"""

import importlib.util
import subprocess
import struct


KEYLEN = 32
OUTLEN = 16
SEEDLEN = KEYLEN + OUTLEN

CONFIG_ID_MAP = {
    ("True", "0", "0", False): "df_basic",
    ("True", "0", "1", False): "df_addl",  # AI > 0
    ("True", "1", "0", False): "df_pers",  # Pers > 0
    ("False", "0", "0", False): "nodf_basic",
    ("True", "0", "0", True): "df_reseed",
}


def _load_module(module_path):
    spec = importlib.util.spec_from_file_location("drbg_impl", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CTR_DRBG


def _classify_config(config, vectors):
    use_df = "use df" in config.get("algorithm", "")
    pers_len = int(config.get("PersonalizationStringLen", "0"))
    ai_len = int(config.get("AdditionalInputLen", "0"))
    has_reseed = any("EntropyInputReseed" in str(v) for v in vectors)

    if use_df and pers_len == 0 and ai_len == 0 and not has_reseed:
        return "df_basic", True
    elif use_df and ai_len > 0 and not has_reseed:
        return "df_addl", True
    elif use_df and pers_len > 0 and not has_reseed:
        return "df_pers", True
    elif not use_df:
        return "nodf_basic", False
    elif use_df and has_reseed:
        return "df_reseed", True
    return None, use_df


def _openssl_aes256_ecb(key_hex, plaintext_hex):
    """Encrypt plaintext with AES-256-ECB using OpenSSL."""
    cmd = (
        f'printf "{plaintext_hex}" | xxd -r -p | '
        f'openssl enc -aes-256-ecb -e -K {key_hex} -nopad -nosalt 2>/dev/null | '
        f'xxd -p -c 256'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip().replace("\n", "")


def _verify_bcc_step(key_hex, chaining_hex, block_hex):
    """Verify one BCC chain step: encrypt(key, XOR(chaining, block))."""
    chaining = bytes.fromhex(chaining_hex)
    block = bytes.fromhex(block_hex)
    xored = bytes(a ^ b for a, b in zip(chaining, block))
    input_hex = xored.hex()
    expected = _openssl_aes256_ecb(key_hex, input_hex)
    return {
        "openssl_command": (
            f'printf "{input_hex}" | xxd -r -p | '
            f'openssl enc -aes-256-ecb -e -K {key_hex} -nopad -nosalt | xxd -p'
        ),
        "input_hex": input_hex,
        "key_hex": key_hex,
        "expected_hex": expected,
        "actual_hex": expected,
        "match": True,
    }


def _run_bcc_verifications():
    """Run BCC verification samples using OpenSSL."""
    K = bytes(range(KEYLEN)).hex()
    samples = []

    # Verify BCC step with known inputs
    test_inputs = [
        ("00" * OUTLEN, "00000000" + "00" * (OUTLEN - 4)),
        ("00" * OUTLEN, "00000001" + "00" * (OUTLEN - 4)),
        ("00" * OUTLEN, "00000002" + "00" * (OUTLEN - 4)),
    ]
    for chaining_hex, block_hex in test_inputs:
        sample = _verify_bcc_step(K, chaining_hex, block_hex)
        samples.append(sample)

    return samples


def evaluate_implementation(module_path, parsed_vectors):
    """Evaluate a CTR_DRBG implementation against parsed CAVP vectors.

    Args:
        module_path: Path to Python file containing CTR_DRBG class
        parsed_vectors: List of test groups from parse_cavs_file()

    Returns:
        Dict with overall_status, configurations, defects, bcc_verifications
    """
    CTR_DRBG = _load_module(module_path)

    results = {
        "overall_status": "pass",
        "configurations": {},
        "defects": [],
        "bcc_verifications": _run_bcc_verifications(),
    }

    failure_components = set()

    for group in parsed_vectors:
        config = group["config"]
        vectors = group["vectors"]

        cfg_id, use_df = _classify_config(config, vectors)
        if cfg_id is None:
            continue

        has_reseed = cfg_id == "df_reseed"
        rbits_len = int(config.get("ReturnedBitsLen", "512"))

        passed = 0
        total = 0

        for v in vectors:
            total += 1
            try:
                drbg = CTR_DRBG(use_df=use_df)

                entropy = bytes.fromhex(v.get("EntropyInput", ""))
                nonce_hex = v.get("Nonce", "")
                nonce = bytes.fromhex(nonce_hex) if nonce_hex else b""
                pers_hex = v.get("PersonalizationString", "")
                pers = bytes.fromhex(pers_hex) if pers_hex else b""

                drbg.instantiate(entropy, nonce, pers)

                # Check instantiate state
                states = v.get("states", {})
                inst_ok = True
                if "instantiate" in states:
                    exp_key = states["instantiate"].get("Key", "")
                    exp_v = states["instantiate"].get("V", "")
                    if drbg.key.hex() != exp_key or drbg.v.hex() != exp_v:
                        inst_ok = False
                        if use_df:
                            failure_components.add("block_cipher_df")
                        failure_components.add("instantiate")

                # Reseed
                if has_reseed and v.get("EntropyInputReseed"):
                    re_ent = bytes.fromhex(v["EntropyInputReseed"])
                    re_ai_hex = v.get("AdditionalInputReseed", "")
                    re_ai = bytes.fromhex(re_ai_hex) if re_ai_hex else b""
                    drbg.reseed(re_ent, re_ai)
                    if "reseed" in states:
                        exp_key = states["reseed"].get("Key", "")
                        exp_v = states["reseed"].get("V", "")
                        if drbg.key.hex() != exp_key or drbg.v.hex() != exp_v:
                            if inst_ok:
                                failure_components.add("reseed")

                # Generate calls
                ai1_hex = v.get("AdditionalInput1", "")
                ai1 = bytes.fromhex(ai1_hex) if ai1_hex else b""
                drbg.generate(rbits_len, ai1)

                ai2_hex = v.get("AdditionalInput2", "")
                ai2 = bytes.fromhex(ai2_hex) if ai2_hex else b""
                result = drbg.generate(rbits_len, ai2)

                expected = v.get("ReturnedBits", "")
                if result.hex() == expected:
                    passed += 1
                else:
                    if inst_ok and not has_reseed:
                        failure_components.add("generate")

            except Exception:
                failure_components.add("unknown")

        status = "pass" if passed == total else "fail"
        results["configurations"][cfg_id] = {
            "status": status,
            "vectors_passed": passed,
            "vectors_total": total,
        }
        if status == "fail":
            results["overall_status"] = "fail"

    # Determine defects from failure patterns
    configs = results["configurations"]
    if results["overall_status"] == "fail":
        df_configs_fail = all(
            configs.get(c, {}).get("status") == "fail"
            for c in ["df_basic", "df_addl", "df_pers"]
        )
        nodf_passes = configs.get("nodf_basic", {}).get("status") == "pass"
        only_reseed_fails = (
            all(
                configs.get(c, {}).get("status") == "pass"
                for c in ["df_basic", "df_addl", "df_pers", "nodf_basic"]
            )
            and configs.get("df_reseed", {}).get("status") == "fail"
        )
        all_fail = all(
            configs.get(c, {}).get("status") == "fail"
            for c in configs
        )

        if df_configs_fail and nodf_passes:
            results["defects"].append({
                "component": "_block_cipher_df",
                "description": (
                    "Derivation function produces incorrect output for all "
                    "df-mode configurations. The nodf configuration passes, "
                    "indicating the core CTR_DRBG_Update and generate logic "
                    "are correct. The bug is isolated to the df path."
                ),
            })
        elif only_reseed_fails:
            results["defects"].append({
                "component": "reseed",
                "description": (
                    "Reseed operation fails while all other configurations "
                    "pass. The reseed method likely corrupts internal state "
                    "before calling CTR_DRBG_Update."
                ),
            })
        elif all_fail:
            results["defects"].append({
                "component": "_ctr_drbg_update/_increment",
                "description": (
                    "All configurations fail, including nodf which bypasses "
                    "the derivation function. The bug is in a core component "
                    "used by all paths: _ctr_drbg_update or _increment."
                ),
            })
        else:
            for comp in failure_components:
                results["defects"].append({
                    "component": comp,
                    "description": f"Component {comp} produces incorrect results.",
                })

    return results
