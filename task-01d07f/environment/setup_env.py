#!/usr/bin/env python3
"""
Environment setup for STRIX-8 S-box analysis task.
Generates the C source for cipher.so, creates the SQLite analysis database,
and writes analyst notes.
"""

import sqlite3
import os

SBOX = [
    222, 127, 138, 233, 207, 186, 36, 81, 37, 85, 69, 18, 125, 237, 84, 215,
    122, 252, 148, 208, 90, 87, 24, 109, 119, 88, 190, 43, 102, 19, 245, 128,
    183, 194, 170, 223, 59, 108, 111, 250, 110, 149, 177, 196, 93, 70, 203, 156,
    34, 68, 150, 227, 2, 25, 113, 94, 30, 107, 230, 101, 100, 32, 91, 56,
    143, 46, 200, 184, 188, 201, 112, 224, 116, 225, 20, 67, 204, 79, 39, 164,
    64, 35, 51, 234, 29, 158, 142, 13, 187, 255, 97, 231, 240, 115, 60, 199,
    89, 218, 8, 5, 1, 160, 45, 192, 66, 193, 95, 220, 145, 242, 241, 80,
    14, 123, 246, 117, 165, 48, 75, 15, 126, 253, 217, 191, 53, 236, 114, 159,
    54, 219, 86, 247, 243, 254, 44, 175, 166, 7, 4, 103, 42, 169, 55, 180,
    249, 189, 198, 83, 131, 0, 141, 248, 105, 132, 26, 195, 73, 47, 11, 136,
    22, 134, 63, 74, 78, 62, 216, 121, 82, 209, 185, 58, 181, 226, 23, 130,
    251, 120, 104, 235, 28, 197, 213, 182, 49, 202, 133, 6, 17, 151, 9, 77,
    12, 153, 154, 205, 41, 92, 52, 65, 106, 61, 176, 171, 50, 71, 99, 152,
    168, 135, 239, 244, 21, 96, 178, 212, 206, 173, 214, 146, 147, 16, 157, 232,
    167, 210, 76, 57, 31, 124, 137, 40, 33, 162, 27, 139, 228, 179, 163, 211,
    155, 238, 161, 172, 38, 98, 10, 140, 118, 3, 229, 144, 221, 72, 174, 129,
]


def compute_inverse(sbox):
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return inv


def compute_anf(truth_table):
    anf = truth_table[:]
    for i in range(8):
        step = 1 << i
        for j in range(256):
            if j & step:
                anf[j] ^= anf[j ^ step]
    return anf


def anf_degree(anf):
    max_deg = 0
    for idx in range(len(anf)):
        if anf[idx]:
            deg = bin(idx).count("1")
            if deg > max_deg:
                max_deg = deg
    return max_deg


def component_degree(sbox, mask):
    tt = []
    for x in range(256):
        val = sbox[x] & mask
        parity = bin(val).count("1") % 2
        tt.append(parity)
    anf = compute_anf(tt)
    return anf_degree(anf)


def generate_c_source(sbox, inv_sbox):
    sbox_rows = []
    for i in range(0, 256, 16):
        row = ", ".join("0x{:02x}".format(v) for v in sbox[i:i+16])
        sbox_rows.append("    " + row)

    inv_rows = []
    for i in range(0, 256, 16):
        row = ", ".join("0x{:02x}".format(v) for v in inv_sbox[i:i+16])
        inv_rows.append("    " + row)

    sbox_block = ",\n".join(sbox_rows)
    inv_block = ",\n".join(inv_rows)

    source = (
        '/* STRIX-8 cipher component library - substitution layer */\n'
        '#include <stdint.h>\n'
        '#include <string.h>\n'
        '\n'
        '/* Bit permutation table for diffusion layer (64-bit block) */\n'
        'static const uint8_t perm_table[64] = {\n'
        '    0, 17, 34, 51, 4, 21, 38, 55,\n'
        '    8, 25, 42, 59, 12, 29, 46, 63,\n'
        '    1, 18, 35, 48, 5, 22, 39, 56,\n'
        '    9, 26, 43, 60, 13, 30, 47, 32,\n'
        '    2, 19, 36, 49, 6, 23, 40, 57,\n'
        '    10, 27, 44, 61, 14, 31, 16, 33,\n'
        '    3, 20, 37, 50, 7, 24, 41, 58,\n'
        '    11, 28, 45, 62, 15, 52, 53, 54\n'
        '};\n'
        '\n'
        '/* Round constants for key schedule */\n'
        'static const uint8_t round_constants[16] = {\n'
        '    0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80,\n'
        '    0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d, 0x9a, 0x2f\n'
        '};\n'
        '\n'
        '/* Forward nonlinear substitution table */\n'
        'static const uint8_t nl_layer[256] = {\n'
        + sbox_block + '\n'
        '};\n'
        '\n'
        '/* Inverse nonlinear substitution table */\n'
        'static const uint8_t nl_layer_inv[256] = {\n'
        + inv_block + '\n'
        '};\n'
        '\n'
        '/* Key whitening mask */\n'
        'static const uint8_t key_mask[8] = {\n'
        '    0xa5, 0x3c, 0x96, 0xf0, 0x5a, 0xc3, 0x69, 0x0f\n'
        '};\n'
        '\n'
        'uint8_t strix_sub(uint8_t x) {\n'
        '    return nl_layer[x];\n'
        '}\n'
        '\n'
        'uint8_t strix_sub_inv(uint8_t x) {\n'
        '    return nl_layer_inv[x];\n'
        '}\n'
        '\n'
        'void strix_sub_block(const uint8_t *in, uint8_t *out, int len) {\n'
        '    for (int i = 0; i < len; i++) {\n'
        '        out[i] = nl_layer[in[i]];\n'
        '    }\n'
        '}\n'
        '\n'
        'void strix_permute(uint8_t *block) {\n'
        '    uint8_t tmp[8];\n'
        '    memset(tmp, 0, 8);\n'
        '    for (int i = 0; i < 64; i++) {\n'
        '        int sb = i / 8, sbit = i % 8;\n'
        '        int d = perm_table[i], db = d / 8, dbit = d % 8;\n'
        '        if (block[sb] & (1 << sbit))\n'
        '            tmp[db] |= (1 << dbit);\n'
        '    }\n'
        '    memcpy(block, tmp, 8);\n'
        '}\n'
    )
    return source


def create_database(sbox):
    db_path = "/app/analysis.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("CREATE TABLE cipher_metadata (key TEXT PRIMARY KEY, value TEXT)")
    metadata = [
        ("cipher_name", "STRIX-8"),
        ("block_size_bits", "64"),
        ("num_rounds", "8"),
        ("sbox_input_bits", "8"),
        ("sbox_output_bits", "8"),
        ("design_origin", "custom"),
        ("construction_method",
         "The nonlinear layer was constructed using a chain of modular "
         "arithmetic operations (multiply-accumulate mod 256) to build a base "
         "permutation, then conjugated with independent invertible affine maps "
         "over GF(2)^8 for additional bit diffusion."),
        ("design_rationale",
         "Modular arithmetic mod 2^n provides natural nonlinearity through "
         "carry propagation while preserving bijectivity. The bit-level "
         "dependency structure of such operations is inherently hierarchical: "
         "bit i of the output depends only on bits 0..i of the input."),
        ("status", "UNDER REVIEW - Algebraic weakness suspected"),
        ("analyst_assigned", "K. Riedel"),
        ("review_priority", "HIGH"),
        ("library_file", "cipher.so (stripped ELF shared object)"),
        ("library_note",
         "The S-box forward table is accessed by the function strix_sub. "
         "The inverse is accessed by strix_sub_inv. Additional data arrays "
         "(permutation table, round constants, key mask) are also present in "
         "the .rodata section."),
    ]
    c.executemany("INSERT INTO cipher_metadata VALUES (?, ?)", metadata)

    c.execute(
        "CREATE TABLE degree_analysis ("
        "mask INTEGER PRIMARY KEY, mask_hex TEXT, mask_weight INTEGER, "
        "algebraic_degree INTEGER, analyzed_date TEXT, notes TEXT)"
    )
    analyzed_masks = sorted(set(
        list(range(1, 40)) + [64, 128, 255, 48, 96, 192, 240, 170, 85, 51, 204]
    ))
    for mask in analyzed_masks:
        deg = component_degree(sbox, mask)
        weight = bin(mask).count("1")
        mask_hex = "0x{:02x}".format(mask)
        notes = ""
        if deg < 7:
            notes = "ANOMALOUS: degree {} < 7, indicates structural weakness".format(deg)
        c.execute(
            "INSERT INTO degree_analysis VALUES (?, ?, ?, ?, ?, ?)",
            (mask, mask_hex, weight, deg, "2024-11-15", notes),
        )

    c.execute(
        "CREATE TABLE analysis_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, "
        "analyst TEXT, category TEXT, note TEXT)"
    )
    log_entries = [
        ("2024-11-10", "K. Riedel", "initial",
         "Beginning structural analysis of the STRIX-8 nonlinear substitution "
         "layer. Implementation provided as stripped shared library cipher.so."),
        ("2024-11-12", "K. Riedel", "observation",
         "Confirmed S-box is a permutation (bijective on {0,...,255}). "
         "Differential uniformity measured at 16. Nonlinearity is 96. "
         "These values are suboptimal compared to the AES S-box."),
        ("2024-11-14", "K. Riedel", "algebraic",
         "Started computing algebraic degrees of all 255 non-trivial component "
         "Boolean functions f_c(x) = <c, S(x)> for c in {1,...,255}."),
        ("2024-11-15", "K. Riedel", "algebraic",
         "Partial degree analysis complete (see degree_analysis table). "
         "CRITICAL FINDING: multiple component functions have algebraic degree "
         "significantly below the expected maximum of 7. This is inconsistent "
         "with a randomly chosen permutation."),
        ("2024-11-16", "K. Riedel", "algebraic",
         "The low-degree components form a structured pattern: masks yielding "
         "degree-d components span specific subspaces over GF(2). The subspaces "
         "are nested in a chain, suggesting the outer affine layer maps a "
         "natural degree stratification to the observed mask subspaces."),
        ("2024-11-17", "K. Riedel", "structural",
         "HYPOTHESIS: The S-box decomposes as S = A . X . B where A and B are "
         "invertible affine maps over GF(2)^8, and X is a nonlinear permutation "
         "whose coordinate functions have a specific degree profile inherited "
         "from the modular arithmetic construction."),
        ("2024-11-18", "K. Riedel", "reference",
         "Related literature: Klimov & Shamir, 'A New Class of Invertible "
         "Mappings' (FSE 2002) - discusses 'T-functions' where bit i of output "
         "depends only on bits 0..i of input. Also: Courtois et al., 'On the "
         "algebraic structure of certain S-boxes'. The bit-dependency pattern "
         "in modular arithmetic maps is sometimes called 'triangular' structure."),
        ("2024-11-19", "K. Riedel", "action_item",
         "TODO: Complete degree computation for all 255 masks. Use the degree "
         "stratification to recover the outer affine map A. Then characterize "
         "the nonlinear core X and recover the inner affine map B. Determine "
         "whether the structure enables a practical attack on the full cipher."),
    ]
    c.executemany(
        "INSERT INTO analysis_log (timestamp, analyst, category, note) "
        "VALUES (?, ?, ?, ?)",
        log_entries,
    )

    c.execute(
        "CREATE TABLE differential_profile ("
        "input_diff INTEGER, output_diff INTEGER, count INTEGER)"
    )
    for dx in range(1, 16):
        counts = {}
        for x in range(256):
            dy = sbox[x] ^ sbox[x ^ dx]
            counts[dy] = counts.get(dy, 0) + 1
        for dy, cnt in sorted(counts.items()):
            if cnt >= 4:
                c.execute(
                    "INSERT INTO differential_profile VALUES (?, ?, ?)",
                    (dx, dy, cnt),
                )

    conn.commit()
    conn.close()


def write_notes():
    notes = (
        "STRIX-8 S-Box Analysis - Working Notes\n"
        "=======================================\n"
        "Classification: INTERNAL - REVIEW IN PROGRESS\n"
        "\n"
        "The STRIX-8 block cipher uses an 8-bit S-box as its core nonlinear\n"
        "substitution component. The S-box implementation is compiled into\n"
        "cipher.so (symbols stripped). Multiple data arrays are present in\n"
        "the binary's read-only data section.\n"
        "\n"
        "The cipher_metadata table in analysis.db documents the S-box\n"
        "construction method and the library's symbol layout.\n"
        "\n"
        "KEY FINDINGS SO FAR:\n"
        "- The S-box is a permutation (verified bijective)\n"
        "- Algebraic degree analysis reveals anomalous low-degree component\n"
        "  Boolean functions (see degree_analysis table in analysis.db)\n"
        "- The degree anomalies suggest the S-box is not a monolithic design\n"
        "  but rather a composition of simpler algebraic primitives\n"
        "- Construction is based on modular arithmetic mod 256, known to\n"
        "  produce hierarchical bit-dependency patterns (see analysis_log)\n"
        "\n"
        "TOOLS:\n"
        "  Database:  sqlite3 /app/analysis.db\n"
        "  Binary:    readelf, objdump, nm, file\n"
        "  Analysis:  python3 with ctypes for S-box extraction\n"
    )
    with open("/app/notes.txt", "w") as f:
        f.write(notes)


if __name__ == "__main__":
    os.makedirs("/app", exist_ok=True)

    inv_sbox = compute_inverse(SBOX)
    c_source = generate_c_source(SBOX, inv_sbox)
    with open("/tmp/strix_sbox.c", "w") as f:
        f.write(c_source)

    create_database(SBOX)
    write_notes()
    print("Environment setup complete.")
