#!/usr/bin/env python3

import json
import subprocess

MASK64 = (1 << 64) - 1
IRRED = 0x1B

_E = [
    0xA5A5A5A5A5A5A5A5,
    0xBADCAFE0DEADBEEF,
    0x1337FACE8BADF00D,
    0xFEEDFACEDEADC0DE,
    0x3C3C3C3C3C3C3C3C,
    0xDEADBEEFCAFEBABE,
    0x6969696969696969,
]

K0 = _E[5]
C0 = _E[0]
K1 = _E[2]
C1 = _E[4]
K2 = _E[3]
C2 = _E[6]
K3 = _E[1]


def gf2_64_mul(a, b):
    result = 0
    a = a & MASK64
    for i in range(64):
        if (b >> i) & 1:
            result ^= a
        carry = (a >> 63) & 1
        a = (a << 1) & MASK64
        if carry:
            a ^= IRRED
    return result


def gf2_64_inv(a):
    if a == 0:
        raise ValueError("Zero has no inverse")
    mod_poly = (1 << 64) | IRRED
    old_r, r = mod_poly, a
    old_s, s = 0, 1
    while r != 0:
        deg_old = old_r.bit_length() - 1
        deg_r = r.bit_length() - 1
        if deg_old < deg_r:
            old_r, r = r, old_r
            old_s, s = s, old_s
            deg_old, deg_r = deg_r, deg_old
        quotient = 0
        remainder = old_r
        while True:
            deg_rem = remainder.bit_length() - 1
            if deg_rem < deg_r:
                break
            shift = deg_rem - deg_r
            quotient ^= (1 << shift)
            remainder ^= (r << shift)
        qs = 0
        tq = quotient
        ts = s
        while tq:
            if tq & 1:
                qs ^= ts
            ts <<= 1
            tq >>= 1
        old_r, r = r, remainder
        old_s, s = s, old_s ^ qs
    while old_s.bit_length() > 64:
        deg = old_s.bit_length() - 1
        old_s ^= (mod_poly << (deg - 64))
    return old_s & MASK64


def inverse_transform(y):
    y = y ^ K3
    y = gf2_64_mul(y, gf2_64_inv(C2))
    y = y ^ K2
    y = gf2_64_mul(y, gf2_64_inv(C1))
    y = y ^ K1
    y = gf2_64_mul(y, gf2_64_inv(C0))
    y = y ^ K0
    return y


def verify_forward(pt_hex, expected_ct_hex):
    out = subprocess.run(
        ["python3", "/app/runner.py", pt_hex],
        capture_output=True, text=True, timeout=60
    )
    return out.stdout.strip() == expected_ct_hex


def fix_candidates():
    """Apply minimal targeted fixes to each candidate decryptor."""
    # Fix candidate A: incorrect reduction constant
    with open("/app/candidates/candidate_a.py") as f:
        code_a = f.read()
    fixed_a = code_a.replace("IRRED = 0x1D", "IRRED = 0x1B")
    with open("/app/candidates/fixed_a.py", "w") as f:
        f.write(fixed_a)

    # Fix candidate B: swapped pool index assignments for K1/K2
    with open("/app/candidates/candidate_b.py") as f:
        lines_b = f.readlines()
    fixed_lines = []
    for line in lines_b:
        if "K1 = _E[3]" in line:
            line = line.replace("_E[3]", "_E[2]")
        elif "K2 = _E[2]" in line:
            line = line.replace("_E[2]", "_E[3]")
        fixed_lines.append(line)
    with open("/app/candidates/fixed_b.py", "w") as f:
        f.writelines(fixed_lines)

    # Fix candidate C: wrong bit position in carry check
    with open("/app/candidates/candidate_c.py") as f:
        code_c = f.read()
    fixed_c = code_c.replace("a >> 62", "a >> 63")
    with open("/app/candidates/fixed_c.py", "w") as f:
        f.write(fixed_c)


def create_kpa_attack():
    """Create the known-plaintext attack module."""
    code = '''\
#!/usr/bin/env python3
"""Known-plaintext attack against the SEAT affine construction.

The SEAT transform is a composition of XOR-key-mixing and GF(2^64)
multiplication steps. Since both XOR (additive) and GF multiplication
(multiplicative, hence linear in GF(2^64)) are linear/affine operations,
the entire transform collapses to:

    y = A * x  XOR  B      (in GF(2^64))

where A = C0 * C1 * C2 and B is a constant depending on all keys.

Given just 2 known (plaintext, ciphertext) pairs, we recover A and B:
    y1 XOR y2 = A * (x1 XOR x2)
    A = (y1 XOR y2) * inv(x1 XOR x2)
    B = y1 XOR A * x1
"""

MASK64 = (1 << 64) - 1
IRRED = 0x1B  # x^64 + x^4 + x^3 + x + 1


def gf2_64_mul(a, b):
    result = 0
    a = a & MASK64
    for i in range(64):
        if (b >> i) & 1:
            result ^= a
        carry = (a >> 63) & 1
        a = (a << 1) & MASK64
        if carry:
            a ^= IRRED
    return result


def gf2_64_inv(a):
    if a == 0:
        raise ValueError("Zero has no inverse in GF(2^64)")
    mod_poly = (1 << 64) | IRRED
    old_r, r = mod_poly, a
    old_s, s = 0, 1
    while r != 0:
        deg_old = old_r.bit_length() - 1
        deg_r = r.bit_length() - 1
        if deg_old < deg_r:
            old_r, r = r, old_r
            old_s, s = s, old_s
            deg_old, deg_r = deg_r, deg_old
        quotient = 0
        remainder = old_r
        while True:
            deg_rem = remainder.bit_length() - 1
            if deg_rem < deg_r:
                break
            shift = deg_rem - deg_r
            quotient ^= (1 << shift)
            remainder ^= (r << shift)
        qs = 0
        tq = quotient
        ts = s
        while tq:
            if tq & 1:
                qs ^= ts
            ts <<= 1
            tq >>= 1
        old_r, r = r, remainder
        old_s, s = s, old_s ^ qs
    while old_s.bit_length() > 64:
        deg = old_s.bit_length() - 1
        old_s ^= (mod_poly << (deg - 64))
    return old_s & MASK64


def recover_params(pairs):
    """Recover the transform parameters (A, B) from known pairs.

    Args:
        pairs: list of (plaintext_int, ciphertext_int) tuples, minimum 2.

    Returns:
        (A, B) where the transform is y = gf_mul(A, x) XOR B.
    """
    assert len(pairs) >= 2, "Need at least 2 known pairs"
    x1, y1 = pairs[0]
    x2, y2 = pairs[1]
    dx = x1 ^ x2
    dy = y1 ^ y2
    A = gf2_64_mul(dy, gf2_64_inv(dx))
    B = y1 ^ gf2_64_mul(A, x1)
    return (A, B)


def attack_decrypt(ct, A, B):
    """Decrypt a ciphertext using recovered affine parameters.

    The forward transform is: ct = gf_mul(A, pt) XOR B
    So: pt = gf_mul(inv(A), ct XOR B)
    """
    return gf2_64_mul(gf2_64_inv(A), ct ^ B)
'''
    with open("/app/kpa_attack.py", "w") as f:
        f.write(code)


def create_security_assessment():
    """Write the security assessment."""
    assessment = """\
# Security Assessment: SEAT Transform

## Vulnerability Classification

**Class**: Affine cipher over GF(2^64) — vulnerable to known-plaintext attack (KPA)

**Severity**: Critical — the entire construction is breakable with only 2 known
plaintext-ciphertext pairs, regardless of the number of internal rounds or constants.

## Analysis

### Obfuscated Wrapper Claims vs. Reality

The `obfuscated.py` module claims the SEAT transform is:
- "One-way" with "preimage resistance of 2^64 operations"
- "Irreversible" with "no known efficient inverse"
- Based on "nonlinear lattice combination" and "arithmetic carry-chain mixing"

**All of these claims are false.** Analysis of the obfuscated code reveals:

1. **`_nlc(a, b)`** ("nonlinear lattice combination"): computes `(a | b) - (a & b)`,
   which is algebraically equivalent to `a ^ b` (XOR). The "algebraic degree 2 in ANF"
   claim is incorrect — XOR has degree 1.

2. **`_acm(a, b)`** ("arithmetic carry-chain mixer"): computes `(a | b) + (a | b) - (a + b)`,
   which simplifies to `2*(a | b) - (a + b) = 2*(a & b) + (a ^ b) - (a + b)`.
   Since `a + b = 2*(a & b) + (a ^ b)` in binary, this reduces to `a ^ b`.

3. **`_sdm(a, b)`** ("split-domain mixer"): computes `(~a & b) + (a & ~b)`, which is
   `a ^ b` since for each bit position, exactly one of these terms contributes a 1 when
   the bits differ.

4. **`_fde` and `_fde_v2`** ("field diffusion engine"): Both implement standard schoolbook
   GF(2^64) multiplication with reduction polynomial x^64 + x^4 + x^3 + x + 1.
   The "variant" `_fde_v2` uses the `_sdm` pattern internally, but since `_sdm` is just
   XOR, it computes the identical GF multiplication.

### The Affine Structure

The SEAT transform applies the following sequence:

```
x -> XOR K0 -> GF_MUL C0 -> XOR K1 -> GF_MUL C1 -> XOR K2 -> GF_MUL C2 -> XOR K3
```

Expanding algebraically over GF(2^64):

```
y = C2 * (C1 * (C0 * (x + K0) + K1) + K2) + K3
  = (C0 * C1 * C2) * x + (C0 * C1 * C2 * K0 + C1 * C2 * K1 + C2 * K2 + K3)
  = A * x + B
```

where `A = C0 * C1 * C2` and `B` is a constant. All operations are in GF(2^64),
where addition is XOR, so this is an **affine map**.

### Known-Plaintext Attack

Given two known pairs (x1, y1) and (x2, y2):

```
y1 + y2 = A * (x1 + x2)        (the B terms cancel under XOR)
A = (y1 + y2) * (x1 + x2)^(-1)  (GF(2^64) inversion)
B = y1 + A * x1
```

This recovers the full transform with exactly **2 known pairs**. No brute force,
no knowledge of the internal constants K0..K3 or C0..C2 is needed.

### Minimum Pairs Required

Exactly 2 distinct plaintext-ciphertext pairs suffice, provided x1 != x2
(so that x1 + x2 is invertible in GF(2^64), which it always is for distinct inputs
since the only non-invertible element is 0).

## Recommended Structural Fix

To prevent this attack, the construction must introduce genuine nonlinearity.
The minimum modification: replace at least one XOR mixing step with a nonlinear
operation such as a substitution box (S-box) lookup or modular addition (mixing
GF(2) and integer arithmetic). For example, replacing `XOR K1` with
`(state + K1) mod 2^64` would break the GF(2^64) affine structure, since
integer addition is nonlinear over GF(2). A single such substitution is sufficient
to make the 2-pair algebraic recovery infeasible.
"""
    with open("/app/security_assessment.md", "w") as f:
        f.write(assessment)


def main():
    with open("/app/targets.json") as f:
        data = json.load(f)
    targets = data["targets"]

    with open("/app/test_vectors.json") as f:
        tv = json.load(f)["test_vectors"]

    # Verify with test vectors
    for v in tv:
        pt = int(v["plaintext"], 16)
        ct = int(v["ciphertext"], 16)
        recovered = inverse_transform(ct)
        assert recovered == pt, f"Inverse check failed for {v['plaintext']}"
        assert verify_forward(v["plaintext"], v["ciphertext"]), (
            f"Forward check failed for {v['plaintext']}"
        )
    print("Test vectors verified successfully")

    # Decrypt all targets
    results = []
    for ct_hex in targets:
        ct = int(ct_hex, 16)
        pt = inverse_transform(ct)
        results.append(f"{pt:016x}")

    # Verify each decrypted result against the library
    for i, (ct_hex, pt_hex) in enumerate(zip(targets, results)):
        assert verify_forward(pt_hex, ct_hex), (
            f"Verification failed for target {i}"
        )
    print("All targets verified against library")

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to /app/results.json")
    for i, (ct, pt) in enumerate(zip(targets, results)):
        print(f"  target[{i}]: {ct} -> {pt}")

    # Fix candidates
    fix_candidates()
    print("Fixed candidates written to /app/candidates/")

    # Create KPA attack module
    create_kpa_attack()
    print("KPA attack module written to /app/kpa_attack.py")

    # Create security assessment
    create_security_assessment()
    print("Security assessment written to /app/security_assessment.md")


if __name__ == "__main__":
    main()
