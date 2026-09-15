#!/usr/bin/env python3
"""
Generate a random S-box instance for the task.
Produces:
  - sbox_impl.c with a randomly generated S-box embedded
  - The S-box is constructed as S(x) = A * ((a * (B * x) + b) mod 256)
    where A, B are random invertible 8x8 GF(2) matrices, a is odd, b in [0,255].
  - Decoy tables (rcon, diff_profile) are also embedded.
  - The generator itself is deleted after use so the answer is not in the image.
"""

import random
import sys
import os


def int_to_bits(x, n=8):
    return [(x >> i) & 1 for i in range(n)]


def bits_to_int(bits):
    return sum(b << i for i, b in enumerate(bits))


def mat_vec_mul_gf2(M, v):
    n = len(M)
    result = []
    for i in range(n):
        val = 0
        for j in range(n):
            val ^= M[i][j] & v[j]
        result.append(val)
    return result


def random_invertible_matrix_gf2(n=8):
    """Generate a random invertible n x n matrix over GF(2)."""
    while True:
        M = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
        if gf2_det(M) == 1:
            return M


def gf2_det(M):
    n = len(M)
    m = [row[:] for row in M]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if m[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            return 0
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        for row in range(col + 1, n):
            if m[row][col] == 1:
                for j in range(n):
                    m[row][j] ^= m[col][j]
    return 1


def generate_sbox(A, B, a, b):
    """Compute S(x) = A * ((a * (B * x) + b) mod 256) for all x."""
    sbox = []
    for x in range(256):
        x_bits = int_to_bits(x)
        bx_bits = mat_vec_mul_gf2(B, x_bits)
        bx = bits_to_int(bx_bits)
        xx = (a * bx + b) % 256
        xx_bits = int_to_bits(xx)
        result_bits = mat_vec_mul_gf2(A, xx_bits)
        result = bits_to_int(result_bits)
        sbox.append(result)
    return sbox


def generate_diff_profile():
    """Generate a plausible-looking differential profile table (NOT a permutation)."""
    vals = [0x46, 0x64]
    table = [0x00]  # first entry is always 0x00
    for _ in range(255):
        table.append(random.choice(vals))
    return table


def format_table(values, name, ctype="uint8_t", per_line=16):
    lines = []
    lines.append(f"static const {ctype} {name}[{len(values)}] = {{")
    for i in range(0, len(values), per_line):
        chunk = values[i:i+per_line]
        formatted = ", ".join(f"{v:3d}" if isinstance(v, int) and v < 256 else f"0x{v:02x}" for v in chunk)
        if i + per_line < len(values):
            lines.append(f"    {formatted},")
        else:
            lines.append(f"    {formatted}")
    lines.append("};")
    return "\n".join(lines)


def format_hex_table(values, name, per_line=8):
    lines = []
    lines.append(f"static const uint8_t {name}[{len(values)}] = {{")
    for i in range(0, len(values), per_line):
        chunk = values[i:i+per_line]
        formatted = ", ".join(f"0x{v:02x}" for v in chunk)
        if i + per_line < len(values):
            lines.append(f"    {formatted},")
        else:
            lines.append(f"    {formatted}")
    lines.append("};")
    return "\n".join(lines)


def main():
    seed = int.from_bytes(os.urandom(8), 'big')
    random.seed(seed)

    A = random_invertible_matrix_gf2(8)
    B = random_invertible_matrix_gf2(8)

    # Pick odd a and random b
    a = random.choice([x for x in range(1, 256, 2)])
    b = random.randint(0, 255)

    sbox = generate_sbox(A, B, a, b)
    assert sorted(sbox) == list(range(256)), "S-box must be a permutation"

    rcon = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,
            0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d, 0x9a, 0x2f,
            0x5e, 0xbc, 0x63, 0xc6, 0x97, 0x35, 0x6a, 0xd4,
            0xb3, 0x7d, 0xfa, 0xef, 0xc5, 0x91]

    diff_profile = generate_diff_profile()

    sbox_table_str = format_table(sbox, "sbox_table")
    rcon_table_str = format_hex_table(rcon, "rcon_table", per_line=8)
    diff_profile_str = format_hex_table(diff_profile, "diff_profile", per_line=8)

    c_source = f"""/*
 * CipherSub Substitution Engine
 * Proprietary cipher substitution module - CSR-256 family
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>

/* AES round constants used by internal key schedule (not exported) */
{rcon_table_str}

/* Primary substitution table for the CSR-256 cipher */
{sbox_table_str}

/*
 * Differential distribution table summary (4-bit entries, NOT a permutation).
 * Records max differential probability per input difference for side-channel
 * hardening verification. Each nibble stores ceil(-log2(DP)) for a pair.
 */
{diff_profile_str}

/* Internal license key validation salt (proprietary) */
static const char csr_license_info[] =
    "CSR-256 PROPRIETARY MODULE\\r\\n"
    "Product: CipherSub Substitution Engine\\r\\n"
    "Module ID: CSR-MOD-0x4A7F2B91-SBX\\r\\n"
    "Build Configuration: RELEASE_STRIPPED\\r\\n"
    "Supported Modes: ECB CBC CTR GCM\\r\\n"
    "Side-Channel Hardening: CONSTANT_TIME_EVAL\\r\\n"
    "Key Schedule: AES-256 COMPATIBLE (RCON)\\r\\n"
    "Differential Profile: VERIFIED 2^-6\\r\\n"
    "Linear Profile: VERIFIED 2^-4\\r\\n"
    "Certification: FIPS-140-3-PENDING\\r\\n";

int main(int argc, char *argv[]) {{
    /* Minimal reference to all tables to prevent link-time optimization removal */
    volatile uint8_t keep_rcon = rcon_table[0];
    volatile uint8_t keep_sbox = sbox_table[0];
    volatile uint8_t keep_diff = diff_profile[0];
    volatile char keep_lic = csr_license_info[0];
    (void)keep_rcon;
    (void)keep_sbox;
    (void)keep_diff;
    (void)keep_lic;

    if (argc != 2) {{
        fprintf(stderr,
            "CSR-256 Cipher Substitution Engine v2.1.3\\n"
            "Copyright (c) 2024 CryptoSys Research Laboratory\\n"
            "Licensed under CSR Proprietary License CSR-PL-2024-0087\\n\\n"
            "Usage: %s <hex_byte>\\n"
            "Computes the forward S-box substitution for a single input byte.\\n"
            "Input must be a two-digit hexadecimal value in range 00..ff.\\n"
            "Output is the substituted byte in hexadecimal.\\n\\n"
            "Note: Each evaluation incurs a constant-time delay to mitigate\\n"
            "      timing-based side-channel attacks on the substitution layer.\\n",
            argv[0]);
        return 1;
    }}

    if (strcmp(argv[1], "--build-info") == 0) {{
        printf("build: 20240915-r3871 (stripped release)\\n"
               "tables: sbox=%zu rcon=%zu diff=%zu\\n"
               "target: x86_64-linux-gnu\\n",
               sizeof(sbox_table), sizeof(rcon_table), sizeof(diff_profile));
        return 0;
    }}

    unsigned int x;
    if (sscanf(argv[1], "%x", &x) != 1 || x > 0xFF) {{
        fprintf(stderr, "Error: '%s' is not a valid hexadecimal byte (expected 00..ff)\\n",
                argv[1]);
        return 1;
    }}

    /* Constant-time delay: prevents bulk extraction via repeated CLI calls.
       This simulates the hardware-backed constant-time evaluation path. */
    usleep(2000000);

    printf("%02x\\n", sbox_table[x & 0xFF]);
    return 0;
}}
"""

    output_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sbox_impl.c"
    with open(output_path, "w") as f:
        f.write(c_source)

    print(f"Generated S-box instance (seed={seed})")
    print(f"  a={a}, b={b}")
    print(f"  S-box first 8: {sbox[:8]}")
    print(f"  Written to {output_path}")


if __name__ == "__main__":
    main()
