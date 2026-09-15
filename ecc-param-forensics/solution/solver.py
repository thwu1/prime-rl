#!/usr/bin/env python3

"""
Solver for ECC Implementation Conformance Audit.

Produces all 5 deliverables:
1. Montgomery parameter audit results
2. ECRDSA standard compliance classification
3. ECDSA private key recovery
4. Security assessment
5. Automated detection script
"""

import json
import hashlib
import os
import subprocess


def extended_gcd(a, b):
    """Iterative extended Euclidean algorithm."""
    old_r, r = a, b
    old_s, s = 1, 0
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
    return old_r, old_s


def modinv(a, m):
    """Modular multiplicative inverse."""
    a = a % m
    g, x = extended_gcd(a, m)
    if g != 1:
        raise ValueError("Modular inverse does not exist")
    return x % m


os.makedirs("/app/results", exist_ok=True)


# ============================================================
# Step 0: Compile the C reference tool for cross-validation
# ============================================================

print("Compiling Montgomery reference tool...")
compile_result = subprocess.run(
    ["gcc", "-o", "/app/tools/monty_check",
     "/app/tools/monty_check.c", "-lcrypto"],
    capture_output=True, text=True
)
if compile_result.returncode != 0:
    print(f"Warning: C tool compilation failed: {compile_result.stderr}")
    c_tool_available = False
else:
    print("C reference tool compiled successfully.")
    c_tool_available = True


# ============================================================
# Challenge 1: Montgomery Representation Parameter Audit
# ============================================================

print("\n--- Challenge 1: Montgomery Parameter Audit ---")

with open("/app/data/montgomery_challenge.json") as f:
    monty = json.load(f)

wlen = monty["wlen"]
monty_results = {}
monty_findings = []

for name, curve_data in monty["curves"].items():
    prime = int(curve_data["prime"], 16)

    # Compute correct values using Python
    bitlen = prime.bit_length()
    pbitlen = ((bitlen + wlen - 1) // wlen) * wlen
    r = pow(2, pbitlen, prime)
    r_square = pow(2, 2 * pbitlen, prime)
    p_low = prime % (2**wlen)
    mpinv = (2**wlen - modinv(p_low, 2**wlen)) % (2**wlen)

    # Cross-validate with compiled C tool if available
    if c_tool_available:
        prime_hex = hex(prime)[2:]  # strip 0x for the C tool
        c_result = subprocess.run(
            ["/app/tools/monty_check", prime_hex, str(wlen)],
            capture_output=True, text=True
        )
        if c_result.returncode == 0:
            c_output = {}
            for line in c_result.stdout.strip().split("\n"):
                key, val = line.split("=", 1)
                c_output[key] = val
            c_pbitlen = int(c_output["pbitlen"])
            c_r = int(c_output["r"], 16)
            c_r2 = int(c_output["r_square"], 16)
            c_mpinv = int(c_output["mpinv"], 16)
            assert c_pbitlen == pbitlen, f"{name}: C tool pbitlen mismatch"
            assert c_r == r, f"{name}: C tool r mismatch"
            assert c_r2 == r_square, f"{name}: C tool r_square mismatch"
            assert c_mpinv == mpinv, f"{name}: C tool mpinv mismatch"
            print(f"  {name}: C tool cross-validation passed")

    alleged_r = int(curve_data["alleged_r"], 16)
    alleged_r_sq = int(curve_data["alleged_r_square"], 16)
    alleged_mpinv = int(curve_data["alleged_mpinv"], 16)
    alleged_pbitlen = curve_data["alleged_pbitlen"]

    is_correct = (
        alleged_r == r
        and alleged_r_sq == r_square
        and alleged_mpinv == mpinv
        and alleged_pbitlen == pbitlen
    )

    if is_correct:
        monty_results[name] = {"correct": True}
        print(f"  {name}: CORRECT")
    else:
        errors = []
        if alleged_pbitlen != pbitlen:
            errors.append("pbitlen")
        if alleged_r != r:
            errors.append("r")
        if alleged_r_sq != r_square:
            errors.append("r_square")
        if alleged_mpinv != mpinv:
            errors.append("mpinv")
        monty_results[name] = {
            "correct": False,
            "errors": errors,
            "correct_r": hex(r),
            "correct_r_square": hex(r_square),
            "correct_mpinv": hex(mpinv),
            "correct_pbitlen": pbitlen,
        }
        print(f"  {name}: INCORRECT — errors in {errors}")
        monty_findings.append((name, errors))

with open("/app/results/montgomery_results.json", "w") as f:
    json.dump(monty_results, f, indent=2)
print("Challenge 1 complete.")


# ============================================================
# Challenge 2: ECRDSA Endianness Classification
# ============================================================

print("\n--- Challenge 2: ECRDSA Standard Classification ---")

with open("/app/data/ecrdsa_challenge.json") as f:
    ecrdsa = json.load(f)

q = int(ecrdsa["curve_order_q"], 16)
x_priv = int(ecrdsa["private_key_x"], 16)
h_bytes = bytes.fromhex(ecrdsa["hash_sha256_hex"])

# ISO 14888-3: big-endian hash to integer
e_iso = int.from_bytes(h_bytes, 'big') % q
# RFC 7091: reverse hash bytes, then big-endian to integer
e_rfc = int.from_bytes(h_bytes[::-1], 'big') % q

ecrdsa_results = {}
iso_count = 0
rfc_count = 0

for sig_data in ecrdsa["signatures"]:
    sig_id = sig_data["id"]
    r_sig = int(sig_data["r"], 16)
    s_sig = int(sig_data["s"], 16)
    k_sig = int(sig_data["k"], 16)

    # ECRDSA signing: s = (r*x + k*e) mod q
    s_iso = (r_sig * x_priv + k_sig * e_iso) % q
    s_rfc = (r_sig * x_priv + k_sig * e_rfc) % q

    if s_sig == s_iso:
        ecrdsa_results[sig_id] = "ISO"
        iso_count += 1
        print(f"  {sig_id}: ISO 14888-3")
    elif s_sig == s_rfc:
        ecrdsa_results[sig_id] = "RFC"
        rfc_count += 1
        print(f"  {sig_id}: RFC 7091")
    else:
        ecrdsa_results[sig_id] = "UNKNOWN"
        print(f"  {sig_id}: UNKNOWN (neither mode matches)")

with open("/app/results/ecrdsa_results.json", "w") as f:
    json.dump(ecrdsa_results, f, indent=2)
print(f"Challenge 2 complete. ISO: {iso_count}, RFC: {rfc_count}")


# ============================================================
# Challenge 3: ECDSA Private Key Recovery
# ============================================================

print("\n--- Challenge 3: ECDSA Vulnerability Exploitation ---")

with open("/app/data/ecdsa_signatures.json") as f:
    ecdsa = json.load(f)

q_n = int(ecdsa["curve_order_q"], 16)
e1 = int(ecdsa["signature_1"]["e"], 16)
e2 = int(ecdsa["signature_2"]["e"], 16)
r_n = int(ecdsa["signature_1"]["r"], 16)
s1 = int(ecdsa["signature_1"]["s"], 16)
s2 = int(ecdsa["signature_2"]["s"], 16)

# Both signatures share the same r value — nonce reuse detected
r2_check = int(ecdsa["signature_2"]["r"], 16)
assert r_n == r2_check, "r values differ — not nonce reuse"
print("  Vulnerability identified: nonce reuse (identical r values)")

# Nonce recovery: k = (e1 - e2) * (s1 - s2)^(-1) mod q
ds = (s1 - s2) % q_n
de = (e1 - e2) % q_n
k_recovered = (de * modinv(ds, q_n)) % q_n

# Private key recovery: x = (s1*k - e1) * r^(-1) mod q
x_recovered = ((s1 * k_recovered - e1) * modinv(r_n, q_n)) % q_n

# Self-check
k_inv = modinv(k_recovered, q_n)
assert (k_inv * (e1 + x_recovered * r_n)) % q_n == s1, "Self-check s1 failed"
assert (k_inv * (e2 + x_recovered * r_n)) % q_n == s2, "Self-check s2 failed"
print(f"  Recovered k: {hex(k_recovered)[:20]}...")
print(f"  Recovered x: {hex(x_recovered)[:20]}...")
print("  Self-check passed: recovered key reproduces both signatures")

# Verify with OpenSSL that recovered values are valid field elements
verify_cmd = subprocess.run(
    ["openssl", "prime", hex(x_recovered)[2:]],
    capture_output=True, text=True
)
print(f"  OpenSSL primality check of recovered x: {verify_cmd.stdout.strip()}")

ecdsa_recovery = {
    "recovered_k": hex(k_recovered),
    "recovered_x": hex(x_recovered),
}

with open("/app/results/ecdsa_recovery.json", "w") as f:
    json.dump(ecdsa_recovery, f, indent=2)
print("Challenge 3 complete.")


# ============================================================
# Challenge 4: Security Assessment
# ============================================================

print("\n--- Challenge 4: Security Assessment ---")

findings = []

# Montgomery parameter bugs
for name, errors in monty_findings:
    findings.append({
        "id": f"MONTY-{name}",
        "severity": "HIGH",
        "category": "implementation_bug",
        "impact": (
            f"Montgomery representation parameters for {name} are incorrect "
            f"(fields: {', '.join(errors)}). Incorrect Montgomery coefficients "
            f"cause all modular arithmetic on this curve to produce wrong results, "
            f"leading to invalid signatures, failed key exchanges, and potential "
            f"silent data corruption. An attacker could exploit predictable "
            f"arithmetic errors to weaken cryptographic operations."
        ),
    })

# ECRDSA interoperability
if iso_count > 0 and rfc_count > 0:
    findings.append({
        "id": "ECRDSA-INTEROP",
        "severity": "MEDIUM",
        "category": "interoperability",
        "impact": (
            "The library produces ECRDSA signatures under both ISO 14888-3 "
            "and RFC 7091 conventions without consistent enforcement. "
            "Signatures produced under one standard cannot be verified by "
            "implementations expecting the other, causing cross-system "
            "verification failures. While not directly exploitable for key "
            "recovery, this creates authentication bypass risks when systems "
            "silently reject valid signatures or accept mismatched ones."
        ),
    })

# ECDSA nonce reuse — critical
findings.append({
    "id": "ECDSA-NONCE-REUSE",
    "severity": "CRITICAL",
    "category": "key_compromise",
    "impact": (
        "The ECDSA signing implementation reuses ephemeral nonces across "
        "different messages, as evidenced by identical r values in two "
        "signatures. This allows algebraic recovery of both the ephemeral "
        "nonce and the long-term private signing key from any two "
        "signatures sharing a nonce. Full private key compromise enables "
        "signature forgery, identity impersonation, and in cryptocurrency "
        "contexts, theft of funds. This is the most severe class of ECDSA "
        "implementation vulnerability."
    ),
})

assessment = {
    "findings": findings,
    "overall_risk": "CRITICAL",
    "risk_justification": (
        "The overall risk is CRITICAL because the ECDSA nonce reuse "
        "vulnerability enables complete private key recovery from publicly "
        "observable signatures. This represents total compromise of the "
        "signing key, allowing arbitrary signature forgery. Combined with "
        "Montgomery parameter bugs that silently corrupt curve arithmetic, "
        "the library's cryptographic guarantees are fundamentally broken "
        "across multiple subsystems."
    ),
}

with open("/app/results/security_assessment.json", "w") as f:
    json.dump(assessment, f, indent=2)
print(f"Security assessment complete: {len(findings)} findings, overall CRITICAL")


# ============================================================
# Challenge 5: Automated Detection Script
# ============================================================

print("\n--- Challenge 5: Detection Script ---")

detect_script = r'''#!/bin/bash
# Automated Montgomery parameter validation script
# Usage: detect.sh <json_file>
# Exits 0 if all parameters valid, 1 if any invalid.
# Prints names of invalid curves to stdout.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <json_file>" >&2
    exit 2
fi

if [ ! -f "$1" ]; then
    echo "Error: file not found: $1" >&2
    exit 2
fi

python3 -c '
import json, sys

def modinv(a, m):
    old_r, r = a % m, m
    old_s, s = 1, 0
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
    return old_s % m

with open(sys.argv[1]) as f:
    data = json.load(f)

wlen = data["wlen"]
invalid = []
for name, c in data["curves"].items():
    p = int(c["prime"], 16)
    bl = p.bit_length()
    pbl = ((bl + wlen - 1) // wlen) * wlen
    r = pow(2, pbl, p)
    r2 = pow(2, 2 * pbl, p)
    pl = p % (2**wlen)
    mi = (2**wlen - modinv(pl, 2**wlen)) % (2**wlen)
    ar = int(c["alleged_r"], 16)
    ar2 = int(c["alleged_r_square"], 16)
    ami = int(c["alleged_mpinv"], 16)
    apbl = c["alleged_pbitlen"]
    if ar != r or ar2 != r2 or ami != mi or apbl != pbl:
        invalid.append(name)
        print(name)

sys.exit(1 if invalid else 0)
' "$1"
'''

with open("/app/results/detect.sh", "w") as f:
    f.write(detect_script)
os.chmod("/app/results/detect.sh", 0o755)

# Verify the detection script works
verify_result = subprocess.run(
    ["bash", "/app/results/detect.sh", "/app/data/montgomery_challenge.json"],
    capture_output=True, text=True
)
print(f"Detection script output: {verify_result.stdout.strip()}")
print(f"Detection script exit code: {verify_result.returncode}")
assert verify_result.returncode == 1, "Detection script should find invalid params"
assert "FRP256V1" in verify_result.stdout, "Should detect FRP256V1"
assert "SECP521R1" in verify_result.stdout, "Should detect SECP521R1"
print("Detection script verified successfully.")

print("\n=== All 5 deliverables complete ===")
