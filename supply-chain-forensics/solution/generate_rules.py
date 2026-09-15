#!/usr/bin/env python3
"""
YARA Rule Generation and Validation
Creates detection rules based on forensic analysis of malicious packages,
then validates against both malicious and benign package sets.
"""

import subprocess
import sys
import os

RULES_PATH = "/app/detection_rules.yar"
SUSPECTS_DIR = "/app/suspects"
BASELINES_DIR = "/app/baselines"

# YARA rules designed from forensic analysis findings.
# Each rule targets the specific malicious indicators found in the suspect
# packages while avoiding false positives on structurally similar baselines.
YARA_RULES = r"""
rule XOR_Base64_RAT_Dropper
{
    meta:
        description = "Detects XOR+reversed-base64 obfuscated RAT dropper (rapid-json-parse family)"
        severity = "critical"
        target_package = "rapid-json-parse"

    strings:
        $xor_func = "_t1 = function"
        $decode_func = "_t2 = function"
        $config_key = "const _cfg"
        $string_array = "_s["
        $self_delete = "fs.unlink(__filename"
        $xor_const = "const _m"

    condition:
        ($xor_func and $decode_func and $config_key) or
        ($string_array and $self_delete and $xor_const)
}

rule DNS_TXT_Command_Injection
{
    meta:
        description = "Detects DNS TXT record polling with command execution (go-financial-calc family)"
        severity = "critical"
        target_package = "go-financial-calc"

    strings:
        $dns_lookup = "net.LookupTXT"
        $exec_cmd = "exec.Command"
        $combined_output = "CombinedOutput"
        $import_net = "\"net\""
        $import_exec = "\"os/exec\""

    condition:
        ($dns_lookup and $exec_cmd) or
        ($import_net and $import_exec and $combined_output)
}

rule Array_Rotation_Telegram_Exfil
{
    meta:
        description = "Detects array rotation cipher with Telegram exfiltration (eth-wallet-utils family)"
        severity = "critical"
        target_package = "eth-wallet-utils"

    strings:
        $array_func = "_0x4a7c"
        $resolver_func = "_0x5c2d"
        $telegram_api = "api.telegram.org"
        $bot_prefix = "/bot"
        $send_message = "sendMessage"

    condition:
        ($array_func and $resolver_func) or
        ($telegram_api and $bot_prefix and $send_message)
}

rule Compressed_Payload_Setup_Py
{
    meta:
        description = "Detects zlib+base64 compressed payload execution in setup.py (pydata-tools family)"
        severity = "critical"
        target_package = "pydata-tools"

    strings:
        $zlib_decompress = "zlib.decompress"
        $b64_decode = "base64.b64decode"
        $exec_call = "exec("

    condition:
        $zlib_decompress and $b64_decode and $exec_call
}
"""


def write_rules():
    """Write YARA rules to the output file."""
    with open(RULES_PATH, "w") as f:
        f.write(YARA_RULES)
    print(f"YARA rules written to {RULES_PATH}")


def validate_rules():
    """Validate YARA rules against suspects and baselines."""
    # Check syntax
    result = subprocess.run(
        ["yara", RULES_PATH, "/dev/null"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: YARA syntax error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("YARA rules syntax: OK")

    # Check detection of each suspect
    suspects = ["rapid-json-parse", "go-financial-calc",
                 "eth-wallet-utils", "pydata-tools"]
    all_detected = True
    for suspect in suspects:
        target = os.path.join(SUSPECTS_DIR, suspect)
        result = subprocess.run(
            ["yara", "-r", RULES_PATH, target],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            matches = result.stdout.strip().split("\n")
            print(f"  DETECTED {suspect}: {len(matches)} match(es)")
            for m in matches:
                print(f"    {m}")
        else:
            print(f"  MISSED {suspect}: no rules matched!")
            all_detected = False

    # Check no false positives on baselines
    baselines = ["fast-json-tools", "go-decimal-math",
                  "eth-address-lib", "pyanalysis-tools"]
    no_fps = True
    for baseline in baselines:
        target = os.path.join(BASELINES_DIR, baseline)
        result = subprocess.run(
            ["yara", "-r", RULES_PATH, target],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            print(f"  FALSE POSITIVE on {baseline}:")
            for line in result.stdout.strip().split("\n"):
                print(f"    {line}")
            no_fps = False
        else:
            print(f"  CLEAN {baseline}: no false positives")

    if all_detected and no_fps:
        print("\nValidation PASSED: All suspects detected, no false positives.")
    else:
        print("\nValidation FAILED.", file=sys.stderr)
        if not all_detected:
            print("  Some suspects were not detected.", file=sys.stderr)
        if not no_fps:
            print("  False positives detected on baselines.", file=sys.stderr)
        sys.exit(1)


def main():
    write_rules()
    validate_rules()


if __name__ == "__main__":
    main()
