"""
CAVP CTR_DRBG Test Vector Validator.

Parses .rsp files from /app/vectors/ and validates each test vector
using the CTR_DRBG implementation in /app/ctr_drbg.py.
"""

import json
import os
import re
import sys

sys.path.insert(0, "/app")
from ctr_drbg import CTR_DRBG


def parse_rsp_file(filepath):
    """Parse a CAVP .rsp file into config sections with test vectors."""
    with open(filepath) as f:
        lines = f.readlines()

    configs = []
    current_config = None
    current_vector = None
    ai_index = 0

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        # Section header
        m = re.match(r"\[(.+)\]", line)
        if m:
            val = m.group(1)
            if val.startswith("AES-") or val.startswith("3Key"):
                # New cipher config group
                if current_config and current_vector:
                    current_config["vectors"].append(current_vector)
                    current_vector = None
                if current_config:
                    configs.append(current_config)
                current_config = {
                    "cipher_mode": val,
                    "params": {},
                    "vectors": [],
                }
            elif current_config is not None:
                k, v = val.split(" = ")
                current_config["params"][k.strip()] = v.strip()
            continue

        # Key-value in vector
        if " = " in line:
            key, _, value = line.partition(" = ")
            key = key.strip()
            value = value.strip()

            if key == "COUNT":
                if current_vector:
                    current_config["vectors"].append(current_vector)
                current_vector = {"COUNT": int(value)}
                ai_index = 0
            elif key == "AdditionalInput":
                ai_key = f"AdditionalInput_{ai_index}"
                current_vector[ai_key] = value
                ai_index += 1
            elif current_vector is not None:
                current_vector[key] = value

    if current_vector and current_config:
        current_config["vectors"].append(current_vector)
    if current_config:
        configs.append(current_config)

    return configs


def validate_vector(config, vector):
    """Run a single test vector and return pass/fail with computed bits."""
    cipher_mode = config["cipher_mode"]
    params = config["params"]

    # Determine keylen and use_df
    if "AES-256" in cipher_mode:
        keylen = 32
    elif "AES-192" in cipher_mode:
        keylen = 24
    elif "AES-128" in cipher_mode:
        keylen = 16
    else:
        return None  # Skip non-AES

    use_df = "use df" in cipher_mode

    drbg = CTR_DRBG(keylen=keylen, use_df=use_df)

    entropy = bytes.fromhex(vector["EntropyInput"])
    nonce_hex = vector.get("Nonce", "")
    nonce = bytes.fromhex(nonce_hex) if nonce_hex else b""
    ps_hex = vector.get("PersonalizationString", "")
    ps = bytes.fromhex(ps_hex) if ps_hex else b""

    drbg.instantiate(entropy, nonce, ps)

    returned_bits_len = int(params.get("ReturnedBitsLen", "512"))

    # First generate
    ai0_hex = vector.get("AdditionalInput_0", "")
    ai0 = bytes.fromhex(ai0_hex) if ai0_hex else b""
    drbg.generate(additional_input=ai0, requested_bits=returned_bits_len)

    # Second generate
    ai1_hex = vector.get("AdditionalInput_1", "")
    ai1 = bytes.fromhex(ai1_hex) if ai1_hex else b""
    returned_bits, _, _ = drbg.generate(
        additional_input=ai1, requested_bits=returned_bits_len
    )

    expected = vector["ReturnedBits"].lower()
    computed = returned_bits.hex()

    return {
        "count": vector["COUNT"],
        "passed": computed == expected,
        "expected_bits": expected,
        "computed_bits": computed,
    }


def main():
    vectors_dir = "/app/vectors"
    all_results = {"total": 0, "passed": 0, "failed": 0, "configs": []}

    for filename in sorted(os.listdir(vectors_dir)):
        if not filename.endswith(".rsp"):
            continue
        filepath = os.path.join(vectors_dir, filename)
        configs = parse_rsp_file(filepath)

        for config in configs:
            cipher_mode = config["cipher_mode"]
            if "AES" not in cipher_mode:
                continue

            params = config["params"]
            ps_len = int(params.get("PersonalizationStringLen", "0"))
            ai_len = int(params.get("AdditionalInputLen", "0"))

            mode = "use df" if "use df" in cipher_mode else "no df"
            cipher = cipher_mode.split()[0]  # e.g. "AES-256"

            config_result = {
                "cipher": cipher,
                "mode": mode,
                "personalization_len": ps_len,
                "additional_input_len": ai_len,
                "vectors": [],
            }

            for vector in config["vectors"]:
                result = validate_vector(config, vector)
                if result is None:
                    continue
                config_result["vectors"].append(result)
                all_results["total"] += 1
                if result["passed"]:
                    all_results["passed"] += 1
                else:
                    all_results["failed"] += 1

            if config_result["vectors"]:
                all_results["configs"].append(config_result)

    with open("/app/results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(
        f"Validation complete: {all_results['passed']}/{all_results['total']} passed, "
        f"{all_results['failed']} failed"
    )
    return 0 if all_results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
