#!/usr/bin/env python3
"""ACVP CTR-DRBG Test Vector Processor.

Reads ACVP prompt JSON from /app/prompts/ctrdrbg_prompt.json and writes
conformant response JSON to /app/responses/ctrdrbg_response.json.

Supports all ACVP ctrDRBG test types: prediction resistance, explicit
reseed, and standard generate, with or without the Block_Cipher_df
derivation function.
"""

import json
import sys
from drbg.core import ctr_drbg_instantiate, ctr_drbg_reseed, ctr_drbg_generate


MODE_TO_KEYLEN = {
    "AES-128": 16,
    "AES-192": 24,
    "AES-256": 32,
}


def process_test_group(group):
    """Process a single ACVP test group and return response data."""
    mode = group["mode"]
    keylen = MODE_TO_KEYLEN[mode]
    use_df = group["derFunc"]
    pred_resistance = group["predResistance"]
    reseed_enabled = group["reSeed"]
    returned_bits_len = group["returnedBitsLen"]

    results = []
    for test in group["tests"]:
        tc_id = test["tcId"]
        entropy_input = bytes.fromhex(test["entropyInput"])
        nonce = bytes.fromhex(test["nonce"]) if test["nonce"] else b""
        perso_string = bytes.fromhex(test["persoString"]) if test["persoString"] else b""

        key, V, rc = ctr_drbg_instantiate(
            entropy_input, nonce, perso_string, keylen, use_df
        )

        other_inputs = test["otherInput"]

        if pred_resistance:
            # Prediction resistance mode: two generate calls with PR reseeds
            oi0 = other_inputs[0]
            ai0 = bytes.fromhex(oi0["additionalInput"]) if oi0["additionalInput"] else b""
            ei0 = bytes.fromhex(oi0["entropyInput"]) if oi0["entropyInput"] else None
            _, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai0, keylen, use_df,
                prediction_resistance=True, entropy_input_pr=ei0
            )

            oi1 = other_inputs[1]
            ai1 = bytes.fromhex(oi1["additionalInput"]) if oi1["additionalInput"] else b""
            ei1 = bytes.fromhex(oi1["entropyInput"]) if oi1["entropyInput"] else None
            returned, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai1, keylen, use_df,
                prediction_resistance=True, entropy_input_pr=ei1
            )

        elif reseed_enabled:
            # Explicit reseed mode: process otherInput by intendedUse
            generate_count = 0
            returned = None
            for oi in other_inputs:
                ai = bytes.fromhex(oi["additionalInput"]) if oi["additionalInput"] else b""
                ei = bytes.fromhex(oi["entropyInput"]) if oi["entropyInput"] else b""

                if oi["intendedUse"] == "reSeed":
                    key, V, rc = ctr_drbg_reseed(key, V, rc, ei, ai, keylen, use_df)
                elif oi["intendedUse"] == "generate":
                    generate_count += 1
                    bits, key, V, rc = ctr_drbg_generate(
                        key, V, rc, returned_bits_len, ai, keylen, use_df,
                        prediction_resistance=False
                    )
                    if generate_count >= 2:
                        returned = bits

        else:
            # Standard mode: two generate calls without PR
            oi0 = other_inputs[0]
            ai0 = bytes.fromhex(oi0["additionalInput"]) if oi0["additionalInput"] else b""
            _, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai0, keylen, use_df,
                prediction_resistance=False
            )

            oi1 = other_inputs[1]
            ai1 = bytes.fromhex(oi1["additionalInput"]) if oi1["additionalInput"] else b""
            returned, key, V, rc = ctr_drbg_generate(
                key, V, rc, returned_bits_len, ai1, keylen, use_df,
                prediction_resistance=False
            )

        results.append({
            "tcId": tc_id,
            "returnedBits": returned.hex().upper()
        })

    return {"tgId": group["tgId"], "tests": results}


def main():
    prompt_path = "/app/prompts/ctrdrbg_prompt.json"
    response_path = "/app/responses/ctrdrbg_response.json"

    with open(prompt_path, "r") as f:
        prompt = json.load(f)

    response_groups = []
    for group in prompt["testGroups"]:
        response_groups.append(process_test_group(group))

    response = {
        "vsId": prompt["vsId"],
        "algorithm": prompt["algorithm"],
        "revision": prompt["revision"],
        "testGroups": response_groups
    }

    with open(response_path, "w") as f:
        json.dump(response, f, indent=2)


if __name__ == "__main__":
    main()
