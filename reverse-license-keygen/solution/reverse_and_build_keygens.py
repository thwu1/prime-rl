#!/usr/bin/env python3
"""
Reverse-engineer /app/license_check_alpha and /app/license_check_beta,
write keygens for both, identify the weak scheme, find a collision,
design a hardened replacement, and produce a comparative security audit.

Strategy:
1. Extract S-boxes from both binaries by scanning for 256-byte permutations
2. Extract algorithm constants by searching for known byte patterns
3. Identify which binary uses a 32-bit vs 64-bit hash core
4. Write keygens for both
5. Write collision finder exploiting the 32-bit weakness
6. Design patched source replacing the 32-bit hash with FNV-1a 64-bit
7. Produce analysis.json, audit.json, and collision.json
"""

import subprocess
import struct
import json
import os
import sys

BINARY_ALPHA = "/app/license_check_alpha"
BINARY_BETA = "/app/license_check_beta"
ANALYSIS_FILE = "/app/analysis.json"
AUDIT_FILE = "/app/audit.json"


def extract_sbox(binary_path, expected_first_byte):
    """Extract the S-box from a binary, identified by its first byte."""
    with open(binary_path, "rb") as f:
        data = f.read()

    for offset in range(len(data) - 256):
        if data[offset] == expected_first_byte:
            candidate = list(data[offset:offset + 256])
            if len(set(candidate)) == 256:
                return candidate
    raise RuntimeError(
        f"Could not find S-box starting with 0x{expected_first_byte:02X} "
        f"in {binary_path}"
    )


def check_constant_in_binary(binary_path, value, width=8):
    """Check if a constant exists in a binary (little-endian)."""
    with open(binary_path, "rb") as f:
        data = f.read()
    le_bytes = value.to_bytes(width, "little")
    return le_bytes in data


def write_keygen_alpha(sbox):
    """Write keygen for alpha scheme (64-bit FNV variant)."""
    code = '''#!/usr/bin/env python3
"""Keygen for license_check_alpha."""
import sys

SBOX = {sbox}
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1

def ror64(v, n):
    n &= 63
    return ((v >> n) | (v << (64 - n))) & MASK64

def hash_username(user):
    h = 0x243F6A8885A308D3
    for c in user:
        h ^= c
        h = (h * 0x100000001B3) & MASK64
        h = ror64(h, 17)
        h = (h + 0x9E3779B97F4A7C15) & MASK64
        h ^= h >> 31
    return h

def substitute(h):
    b = list(h.to_bytes(8, "little"))
    for i in range(8):
        b[i] = SBOX[b[i]]
    return int.from_bytes(bytes(b), "little")

def feistel(h):
    L = (h >> 32) & MASK32
    R = h & MASK32
    rk = [0xDEADBEEF, 0x0BADF00D, 0xFEEDFACE, 0x27182818]
    rm = [0x1337CAFE, 0xCAFEBABE, 0xC0FFEE42, 0x31415927]
    rs = [7, 11, 5, 13]
    for i in range(4):
        f = (R * rm[i]) & MASK32
        f ^= R >> rs[i]
        f = (f + rk[i]) & MASK32
        L, R = R, L ^ f
    return (L << 32) | R

def finalize(h):
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & MASK64
    h ^= h >> 33
    h = (h * 0xC4CEB9FE1A85EC53) & MASK64
    h ^= h >> 33
    return h

def derive_key(username):
    h = hash_username(username.encode("ascii"))
    h = substitute(h)
    h = feistel(h)
    h = finalize(h)
    return "{{:04x}}-{{:04x}}-{{:04x}}-{{:04x}}".format(
        (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
        (h >> 16) & 0xFFFF, h & 0xFFFF)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {{sys.argv[0]}} <username>", file=sys.stderr)
        sys.exit(1)
    print(derive_key(sys.argv[1]))
'''.format(sbox=repr(sbox))

    with open("/app/keygen_alpha.py", "w") as f:
        f.write(code)
    os.chmod("/app/keygen_alpha.py", 0o755)
    print("Wrote /app/keygen_alpha.py")


def write_keygen_beta(sbox):
    """Write keygen for beta scheme (32-bit FNV-1 expanded to 64 bits)."""
    code = '''#!/usr/bin/env python3
"""Keygen for license_check_beta."""
import sys

SBOX = {sbox}
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1

def hash_username(user):
    h = 0x811C9DC5
    for c in user:
        h ^= c
        h = (h * 0x01000193) & MASK32
    lo = h
    hi = (((h * 0x517CC1B7) & MASK32) + 0x9E3779B9) & MASK32
    return (hi << 32) | lo

def substitute(h):
    b = list(h.to_bytes(8, "little"))
    for i in range(8):
        b[i] = SBOX[b[i]]
    return int.from_bytes(bytes(b), "little")

def feistel(h):
    L = (h >> 32) & MASK32
    R = h & MASK32
    rk = [0xCAFEBABE, 0x8BADF00D, 0xDEADC0DE, 0x31415926]
    rm = [0xBAADF00D, 0x1BADB002, 0xFEE1DEAD, 0x0D15EA5E]
    rs = [5, 9, 7, 11]
    for i in range(4):
        f = (R * rm[i]) & MASK32
        f ^= R >> rs[i]
        f = (f + rk[i]) & MASK32
        L, R = R, L ^ f
    return (L << 32) | R

def finalize(h):
    h ^= h >> 33
    h = (h * 0xBF58476D1CE4E5B9) & MASK64
    h ^= h >> 33
    h = (h * 0x94D049BB133111EB) & MASK64
    h ^= h >> 33
    return h

def derive_key(username):
    h = hash_username(username.encode("ascii"))
    h = substitute(h)
    h = feistel(h)
    h = finalize(h)
    return "{{:04x}}-{{:04x}}-{{:04x}}-{{:04x}}".format(
        (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
        (h >> 16) & 0xFFFF, h & 0xFFFF)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {{sys.argv[0]}} <username>", file=sys.stderr)
        sys.exit(1)
    print(derive_key(sys.argv[1]))
'''.format(sbox=repr(sbox))

    with open("/app/keygen_beta.py", "w") as f:
        f.write(code)
    os.chmod("/app/keygen_beta.py", 0o755)
    print("Wrote /app/keygen_beta.py")


def write_collision_finder(sbox):
    """Write collision finder exploiting beta's 32-bit hash weakness."""
    code = '''#!/usr/bin/env python3
"""
Find a collision in the beta license scheme.

The beta hash_username function uses a 32-bit FNV-1 core, producing only
2^32 distinct hash values. The subsequent pipeline (S-box, Feistel,
finalization) is a bijection, so collisions in hash_username directly
produce collisions in the final key. Birthday attack on 32-bit space
needs only ~O(2^16) = ~65K trials.
"""
import json
import sys

SBOX = {sbox}
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1

def hash_username_32(user_bytes):
    """Just the 32-bit FNV-1 core -- collisions here mean key collisions."""
    h = 0x811C9DC5
    for c in user_bytes:
        h ^= c
        h = (h * 0x01000193) & MASK32
    return h

def full_derive(user_bytes):
    h32 = hash_username_32(user_bytes)
    lo = h32
    hi = (((h32 * 0x517CC1B7) & MASK32) + 0x9E3779B9) & MASK32
    h = (hi << 32) | lo
    b = list(h.to_bytes(8, "little"))
    for i in range(8):
        b[i] = SBOX[b[i]]
    h = int.from_bytes(bytes(b), "little")
    L = (h >> 32) & MASK32
    R = h & MASK32
    rk = [0xCAFEBABE, 0x8BADF00D, 0xDEADC0DE, 0x31415926]
    rm = [0xBAADF00D, 0x1BADB002, 0xFEE1DEAD, 0x0D15EA5E]
    rs = [5, 9, 7, 11]
    for i in range(4):
        f = (R * rm[i]) & MASK32
        f ^= R >> rs[i]
        f = (f + rk[i]) & MASK32
        L, R = R, L ^ f
    h = (L << 32) | R
    h ^= h >> 33
    h = (h * 0xBF58476D1CE4E5B9) & MASK64
    h ^= h >> 33
    h = (h * 0x94D049BB133111EB) & MASK64
    h ^= h >> 33
    return h

def format_key(h):
    return "{{:04x}}-{{:04x}}-{{:04x}}-{{:04x}}".format(
        (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
        (h >> 16) & 0xFFFF, h & 0xFFFF)

def find_collision():
    """Birthday attack on the 32-bit FNV-1 hash."""
    seen = {{}}  # hash32 -> username string
    for i in range(500000):
        scrambled = (i * 2654435761) & 0xFFFFFFFF
        username = f"k{{scrambled:x}}"
        ub = username.encode("ascii")
        h32 = hash_username_32(ub)
        if h32 in seen and seen[h32] != username:
            other = seen[h32]
            key_val = full_derive(ub)
            key_str = format_key(key_val)
            return other, username, key_str
        seen[h32] = username
    raise RuntimeError("No collision found in 500000 trials (unexpected)")

if __name__ == "__main__":
    u1, u2, key = find_collision()
    print(f"Collision found: '{{u1}}' and '{{u2}}' -> {{key}}")
    result = {{"username1": u1, "username2": u2, "key": key}}
    with open("/app/collision.json", "w") as f:
        json.dump(result, f, indent=2)
    print("Saved to /app/collision.json")
'''.format(sbox=repr(sbox))

    with open("/app/find_collision.py", "w") as f:
        f.write(code)
    os.chmod("/app/find_collision.py", 0o755)
    print("Wrote /app/find_collision.py")


def write_analysis():
    """Write the security analysis JSON identifying the weak scheme."""
    analysis = {
        "weak_scheme": "beta",
        "effective_bits": 32,
        "reason": (
            "The beta scheme's hash_username function uses a 32-bit FNV-1 hash "
            "(init=0x811C9DC5, prime=0x01000193) as its core, operating entirely "
            "within a uint32_t. The result is then expanded to 64 bits via a "
            "deterministic linear transform (multiply by 0x517CC1B7 and add "
            "0x9E3779B9 for the upper 32 bits). Since the expansion is a "
            "deterministic function of the 32-bit hash, the effective entropy "
            "is limited to 32 bits. The subsequent S-box substitution, Feistel "
            "network, and finalization are all bijections on 64-bit values, so "
            "they preserve collision structure. Birthday attack on a 32-bit "
            "space requires only ~2^16 (~65,000) trials, making collisions "
            "trivially findable. In contrast, the alpha scheme uses a 64-bit "
            "FNV variant with rotate, add, and xor-shift mixing, providing "
            "full 64-bit entropy that requires ~2^32 trials for birthday attacks."
        )
    }
    with open(ANALYSIS_FILE, "w") as f:
        json.dump(analysis, f, indent=2)
    print("Wrote /app/analysis.json")


def write_patched_source(beta_sbox):
    """Write a hardened version of the beta binary with FNV-1a 64-bit hash."""
    sbox_lines = []
    for row in range(16):
        vals = beta_sbox[row * 16:(row + 1) * 16]
        line = "    " + ", ".join(f"0x{v:02X}" for v in vals) + ","
        sbox_lines.append(line)
    sbox_block = "\n".join(sbox_lines)

    # Template uses $SBOX$ placeholder to avoid brace-escaping issues
    template = r"""#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>

static const uint8_t SBOX[256] = {
$SBOX$
};

/*
 * Hardened hash function: FNV-1a 64-bit.
 * Operates on a full 64-bit state throughout, providing true 64-bit
 * entropy. Birthday attack requires ~2^32 trials (vs ~2^16 for the
 * original 32-bit FNV-1 core that was used here previously).
 */
static uint64_t hash_username(const char *user, size_t len) {
    uint64_t h = UINT64_C(0xCBF29CE484222325);
    size_t i;
    for (i = 0; i < len; i++) {
        h ^= (uint64_t)(unsigned char)user[i];
        h *= UINT64_C(0x100000001B3);
    }
    return h;
}

static uint64_t substitute(uint64_t h) {
    union { uint64_t u; uint8_t b[8]; } v;
    v.u = h;
    int i;
    for (i = 0; i < 8; i++) {
        v.b[i] = SBOX[v.b[i]];
    }
    return v.u;
}

static uint64_t feistel(uint64_t h) {
    uint32_t L = (uint32_t)(h >> 32);
    uint32_t R = (uint32_t)(h & UINT32_C(0xFFFFFFFF));
    const uint32_t rk[4] = {
        UINT32_C(0xCAFEBABE), UINT32_C(0x8BADF00D),
        UINT32_C(0xDEADC0DE), UINT32_C(0x31415926)
    };
    const uint32_t rm[4] = {
        UINT32_C(0xBAADF00D), UINT32_C(0x1BADB002),
        UINT32_C(0xFEE1DEAD), UINT32_C(0x0D15EA5E)
    };
    const unsigned int rs[4] = {5, 9, 7, 11};
    int i;
    for (i = 0; i < 4; i++) {
        uint32_t f = R * rm[i];
        f ^= R >> rs[i];
        f += rk[i];
        uint32_t tmp = L ^ f;
        L = R;
        R = tmp;
    }
    return ((uint64_t)L << 32) | (uint64_t)R;
}

static uint64_t finalize(uint64_t h) {
    h ^= h >> 33;
    h *= UINT64_C(0xBF58476D1CE4E5B9);
    h ^= h >> 33;
    h *= UINT64_C(0x94D049BB133111EB);
    h ^= h >> 33;
    return h;
}

static void derive_key(const char *username, char *out) {
    size_t len = strlen(username);
    uint64_t h = hash_username(username, len);
    h = substitute(h);
    h = feistel(h);
    h = finalize(h);
    snprintf(out, 20, "%04" PRIx64 "-%04" PRIx64 "-%04" PRIx64 "-%04" PRIx64,
             (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
             (h >> 16) & 0xFFFF, h & 0xFFFF);
}

int main(void) {
    char username[256], key[256];
    fprintf(stderr, "Username: ");
    if (!fgets(username, sizeof(username), stdin)) return 1;
    username[strcspn(username, "\n")] = 0;
    fprintf(stderr, "License Key: ");
    if (!fgets(key, sizeof(key), stdin)) return 1;
    key[strcspn(key, "\n")] = 0;
    if (!*username || !*key) { puts("INVALID"); return 1; }
    char expected[20];
    derive_key(username, expected);
    if (strcmp(key, expected) == 0) {
        puts("VALID");
        return 0;
    }
    puts("INVALID");
    return 1;
}
"""
    source = template.replace("$SBOX$", sbox_block)
    with open("/app/license_check_patched.c", "w") as f:
        f.write(source)
    print("Wrote /app/license_check_patched.c")

    # Compile
    result = subprocess.run(
        ["gcc", "-O2", "-static", "-s", "-o",
         "/app/license_check_patched", "/app/license_check_patched.c"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"Compilation failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    os.chmod("/app/license_check_patched", 0o755)
    print("Compiled /app/license_check_patched")


def write_keygen_patched(beta_sbox):
    """Write keygen for the patched scheme (FNV-1a 64-bit + beta pipeline)."""
    code = '''#!/usr/bin/env python3
"""Keygen for the patched license_check binary (FNV-1a 64-bit hash)."""
import sys

SBOX = {sbox}
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1

def hash_username(user):
    h = 0xCBF29CE484222325
    for c in user:
        h ^= c
        h = (h * 0x100000001B3) & MASK64
    return h

def substitute(h):
    b = list(h.to_bytes(8, "little"))
    for i in range(8):
        b[i] = SBOX[b[i]]
    return int.from_bytes(bytes(b), "little")

def feistel(h):
    L = (h >> 32) & MASK32
    R = h & MASK32
    rk = [0xCAFEBABE, 0x8BADF00D, 0xDEADC0DE, 0x31415926]
    rm = [0xBAADF00D, 0x1BADB002, 0xFEE1DEAD, 0x0D15EA5E]
    rs = [5, 9, 7, 11]
    for i in range(4):
        f = (R * rm[i]) & MASK32
        f ^= R >> rs[i]
        f = (f + rk[i]) & MASK32
        L, R = R, L ^ f
    return (L << 32) | R

def finalize(h):
    h ^= h >> 33
    h = (h * 0xBF58476D1CE4E5B9) & MASK64
    h ^= h >> 33
    h = (h * 0x94D049BB133111EB) & MASK64
    h ^= h >> 33
    return h

def derive_key(username):
    h = hash_username(username.encode("ascii"))
    h = substitute(h)
    h = feistel(h)
    h = finalize(h)
    return "{{:04x}}-{{:04x}}-{{:04x}}-{{:04x}}".format(
        (h >> 48) & 0xFFFF, (h >> 32) & 0xFFFF,
        (h >> 16) & 0xFFFF, h & 0xFFFF)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {{sys.argv[0]}} <username>", file=sys.stderr)
        sys.exit(1)
    print(derive_key(sys.argv[1]))
'''.format(sbox=repr(beta_sbox))

    with open("/app/keygen_patched.py", "w") as f:
        f.write(code)
    os.chmod("/app/keygen_patched.py", 0o755)
    print("Wrote /app/keygen_patched.py")


def write_audit():
    """Write comparative security audit of all three schemes."""
    audit = {
        "schemes": [
            {
                "name": "alpha",
                "hash_width_bits": 64,
                "collision_complexity": "O(2^32)",
                "key_space_bits": 64,
                "verdict": "secure",
                "justification": (
                    "Alpha's hash_username uses a 64-bit FNV variant with "
                    "rotate-right, addition, and xor-shift mixing operations, "
                    "maintaining full 64-bit internal state throughout. "
                    "Birthday attack requires ~2^32 (~4 billion) trials, "
                    "making practical collision attacks infeasible. The "
                    "subsequent S-box, Feistel, and finalization stages are "
                    "bijections that preserve the full 64-bit entropy."
                )
            },
            {
                "name": "beta",
                "hash_width_bits": 32,
                "collision_complexity": "O(2^16)",
                "key_space_bits": 32,
                "verdict": "insecure",
                "justification": (
                    "Beta's hash_username uses a 32-bit FNV-1 core "
                    "(init=0x811C9DC5, prime=0x01000193), producing only 2^32 "
                    "distinct values. The expansion to 64 bits via "
                    "h*0x517CC1B7+0x9E3779B9 is a deterministic 1:1 mapping "
                    "from 32-bit to 64-bit space, adding no entropy. Birthday "
                    "attack on 32 bits requires only ~2^16 (~65,000) trials, "
                    "enabling practical collision finding in under a second."
                )
            },
            {
                "name": "patched",
                "hash_width_bits": 64,
                "collision_complexity": "O(2^32)",
                "key_space_bits": 64,
                "verdict": "secure",
                "justification": (
                    "The patched scheme replaces beta's 32-bit FNV-1 core "
                    "with FNV-1a 64-bit (init=0xCBF29CE484222325, "
                    "prime=0x100000001B3), operating on the full 64-bit state "
                    "throughout. This eliminates the entropy bottleneck while "
                    "preserving the S-box, Feistel, and finalization stages. "
                    "Birthday attack now requires ~2^32 trials, matching "
                    "alpha's collision resistance."
                )
            }
        ],
        "recommended_scheme": "patched",
        "recommendation_rationale": (
            "The patched scheme should be deployed because it provides "
            "equivalent 64-bit collision resistance to alpha while "
            "maintaining backward compatibility with beta's S-box, Feistel "
            "network, and finalization pipeline. Its FNV-1a 64-bit hash is a "
            "well-studied, IETF-standardized algorithm (RFC draft), simpler "
            "than alpha's custom mixing construction. This reduces the risk "
            "of subtle implementation errors and enables reuse of existing "
            "beta infrastructure (S-box tables, key validators) with only "
            "the hash stage replaced. Alpha's custom non-standard hash "
            "construction, while currently secure, has not been subjected "
            "to the same level of independent cryptographic scrutiny."
        )
    }
    with open(AUDIT_FILE, "w") as f:
        json.dump(audit, f, indent=2)
    print("Wrote /app/audit.json")


def verify_keygen(binary, keygen, name):
    """Verify a keygen works against its binary."""
    test_users = ["admin", "root", "alice"]
    for user in test_users:
        result = subprocess.run(
            ["python3", keygen, user],
            capture_output=True, text=True, timeout=10
        )
        key = result.stdout.strip()
        result2 = subprocess.run(
            [binary],
            input=f"{user}\n{key}\n",
            capture_output=True, text=True, timeout=10
        )
        status = result2.stdout.strip()
        print(f"  [{name}] {user} -> {key} -> {status}")
        if status != "VALID":
            raise RuntimeError(f"Verification failed for {name} user '{user}'")


def main():
    print("=== Reverse Engineering Both Binaries ===")

    # Extract alpha S-box (starts with 0x80)
    print("\n[1] Extracting alpha S-box...")
    alpha_sbox = extract_sbox(BINARY_ALPHA, 0x80)
    print(f"    Found alpha S-box, {len(set(alpha_sbox))} distinct values")

    # Extract beta S-box (starts with 0xB7)
    print("\n[2] Extracting beta S-box...")
    beta_sbox = extract_sbox(BINARY_BETA, 0xB7)
    print(f"    Found beta S-box, {len(set(beta_sbox))} distinct values")

    # Verify algorithm constants
    print("\n[3] Verifying alpha constants...")
    alpha_consts = [
        (0x243F6A8885A308D3, 8, "hash_init"),
        (0x100000001B3, 8, "hash_mul"),
        (0xFF51AFD7ED558CCD, 8, "final_mul1"),
    ]
    for val, width, name in alpha_consts:
        found = check_constant_in_binary(BINARY_ALPHA, val, width)
        print(f"    {name}: {'FOUND' if found else 'MISSING'}")

    print("\n[4] Verifying beta constants...")
    beta_consts = [
        (0x811C9DC5, 4, "fnv32_init"),
        (0x01000193, 4, "fnv32_prime"),
        (0xBF58476D1CE4E5B9, 8, "final_mul1"),
    ]
    for val, width, name in beta_consts:
        found = check_constant_in_binary(BINARY_BETA, val, width)
        print(f"    {name}: {'FOUND' if found else 'MISSING'}")

    # Write keygens
    print("\n[5] Writing alpha keygen...")
    write_keygen_alpha(alpha_sbox)

    print("\n[6] Writing beta keygen...")
    write_keygen_beta(beta_sbox)

    # Verify keygens
    print("\n[7] Verifying alpha keygen...")
    verify_keygen(BINARY_ALPHA, "/app/keygen_alpha.py", "alpha")

    print("\n[8] Verifying beta keygen...")
    verify_keygen(BINARY_BETA, "/app/keygen_beta.py", "beta")

    # Write analysis
    print("\n[9] Writing security analysis...")
    write_analysis()

    # Write collision finder and find collision
    print("\n[10] Writing collision finder...")
    write_collision_finder(beta_sbox)

    print("\n[11] Finding collision...")
    result = subprocess.run(
        ["python3", "/app/find_collision.py"],
        capture_output=True, text=True, timeout=60
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Design and build the hardened replacement
    print("\n[12] Writing patched source (FNV-1a 64-bit hash)...")
    write_patched_source(beta_sbox)

    print("\n[13] Writing patched keygen...")
    write_keygen_patched(beta_sbox)

    # Verify patched keygen
    print("\n[14] Verifying patched keygen...")
    verify_keygen("/app/license_check_patched", "/app/keygen_patched.py", "patched")

    # Write comparative security audit
    print("\n[15] Writing comparative security audit...")
    write_audit()

    print("\nDone!")


if __name__ == "__main__":
    main()
