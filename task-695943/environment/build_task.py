#!/usr/bin/env python3
"""Build script: generates libcipher.so and cipher.db for the task environment."""
import os
import sqlite3
import subprocess

SBOX = [
    85, 70, 80, 196, 131, 23, 1, 18, 163, 20, 112, 117, 50, 55, 83, 228,
    226, 65, 231, 52, 115, 160, 6, 165, 194, 199, 97, 166, 225, 38, 128, 133,
    249, 254, 221, 47, 104, 154, 185, 190, 25, 184, 155, 125, 58, 220, 255, 94,
    111, 157, 139, 76, 11, 204, 218, 40, 233, 191, 156, 202, 141, 219, 248, 174,
    192, 130, 19, 227, 164, 84, 197, 135, 224, 116, 162, 177, 246, 229, 51, 167,
    150, 81, 114, 48, 119, 53, 22, 209, 16, 195, 82, 182, 241, 21, 132, 87,
    43, 205, 238, 79, 8, 169, 138, 108, 109, 159, 14, 9, 78, 73, 216, 42,
    44, 61, 89, 72, 15, 30, 122, 107, 124, 187, 223, 45, 106, 152, 252, 59,
    203, 12, 170, 232, 175, 237, 75, 140, 77, 27, 56, 110, 41, 127, 92, 10,
    24, 90, 121, 137, 206, 62, 29, 95, 74, 172, 200, 105, 46, 143, 235, 13,
    179, 208, 198, 101, 34, 129, 151, 244, 145, 86, 64, 178, 245, 7, 17, 214,
    180, 215, 113, 98, 37, 54, 144, 243, 242, 0, 35, 36, 99, 100, 71, 181,
    207, 222, 186, 171, 236, 253, 153, 136, 93, 88, 60, 251, 188, 123, 31, 26,
    120, 217, 189, 91, 28, 250, 158, 63, 142, 57, 239, 234, 173, 168, 126, 201,
    183, 69, 33, 230, 161, 102, 2, 240, 49, 213, 68, 96, 39, 3, 146, 118,
    147, 148, 5, 247, 176, 66, 211, 212, 193, 210, 67, 103, 32, 4, 149, 134,
]


def compute_inverse(sbox):
    inv = [0] * 256
    for x, y in enumerate(sbox):
        inv[y] = x
    return inv


def compute_decoy(mult, add):
    return [(i * mult + add) % 256 for i in range(256)]


def format_c_array(values, name):
    lines = ["const uint8_t %s[256] = {" % name]
    for i in range(0, 256, 16):
        row = values[i:i + 16]
        lines.append("    " + ", ".join("%3d" % v for v in row) + ",")
    lines.append("};")
    return "\n".join(lines)


def main():
    inv_sbox = compute_inverse(SBOX)
    decoy_ks = compute_decoy(167, 53)
    decoy_rc = compute_decoy(211, 137)

    c_source = "#include <stdint.h>\n\n"
    c_source += format_c_array(SBOX, "cipher_sbox_forward") + "\n\n"
    c_source += format_c_array(inv_sbox, "cipher_sbox_inverse") + "\n\n"
    c_source += format_c_array(decoy_ks, "cipher_key_schedule") + "\n\n"
    c_source += format_c_array(decoy_rc, "cipher_round_constants") + "\n"

    src_path = "/tmp/sbox_impl.c"
    with open(src_path, "w") as f:
        f.write(c_source)

    subprocess.check_call([
        "gcc", "-shared", "-fPIC", "-O2",
        "-o", "/app/libcipher.so", src_path
    ])
    os.remove(src_path)

    conn = sqlite3.connect("/app/cipher.db")
    c = conn.cursor()

    c.execute("""CREATE TABLE cipher_metadata (
        param TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.executemany("INSERT INTO cipher_metadata VALUES (?, ?)", [
        ("cipher_name", "StairCipher-256"),
        ("version", "2.1.0"),
        ("block_size_bits", "8"),
        ("construction_type", "affine-arithmetic"),
        ("num_rounds", "10"),
        ("target_component", "cipher_sbox_forward"),
    ])

    c.execute("""CREATE TABLE library_symbols (
        symbol_name TEXT PRIMARY KEY,
        symbol_type TEXT,
        description TEXT,
        element_count INTEGER,
        element_size_bytes INTEGER
    )""")
    c.executemany("INSERT INTO library_symbols VALUES (?, ?, ?, ?, ?)", [
        ("cipher_sbox_forward", "data", "Primary substitution lookup table", 256, 1),
        ("cipher_sbox_inverse", "data", "Inverse substitution lookup table", 256, 1),
        ("cipher_key_schedule", "data", "Key schedule derivation table", 256, 1),
        ("cipher_round_constants", "data", "Per-round XOR constant table", 256, 1),
    ])

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
