#!/usr/bin/env python3
"""
Solve the decompilation codegen matching task by applying targeted
source transformations to candidate.c, then verifying byte-identical
.text output against target.o. Generates analysis.json classifying
each difference as codegen-affecting or cosmetic.

"""

import json
import subprocess
import sys
import os
import re
import tempfile


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def compile_obj(src, obj):
    r = subprocess.run([
        "gcc", "-c", "-O0", "-fno-stack-protector", "-fno-pic",
        "-fcf-protection=none", "-std=c11", "-o", obj, src
    ], capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def extract_text(obj_path):
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.check_call([
            "objcopy", "-O", "binary", "-j", ".text", obj_path, tmp_path
        ])
        with open(tmp_path, 'rb') as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def texts_match():
    ok, err = compile_obj('/app/candidate.c', '/app/candidate.o')
    if not ok:
        print(f"  Compilation failed: {err}")
        return False
    target = extract_text('/app/target.o')
    candidate = extract_text('/app/candidate.o')
    if target == candidate:
        print(f"  .text match: {len(target)} bytes")
        return True
    min_len = min(len(target), len(candidate))
    diffs = sum(1 for i in range(min_len) if target[i] != candidate[i])
    diffs += abs(len(target) - len(candidate))
    print(f"  .text MISMATCH: {diffs} bytes differ "
          f"(target={len(target)}, candidate={len(candidate)})")
    return False


def apply_regex_transforms(source):
    """Apply all codegen-affecting transformations using regex."""
    transforms_applied = 0

    # T1: Split combined condition and move declaration after size check
    old = source
    source = re.sub(
        r'    const Header \*hdr = \(const Header \*\)data;\n'
        r'    if \(size < sizeof\(Header\) \|\| hdr->magic != MAGIC\)\n'
        r'        return 0;',
        '    if (size < sizeof(Header))\n'
        '        return 0;\n'
        '\n'
        '    const Header *hdr = (const Header *)data;\n'
        '\n'
        '    if (hdr->magic != MAGIC)\n'
        '        return 0;',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T1: split condition + move declaration")
    else:
        print("  T1: SKIPPED (pattern not found)")

    # T2: De Morgan's law: !(A >= 1 && A <= 3) -> A < 1 || A > 3
    old = source
    source = re.sub(
        r'    if \(!\(hdr->version >= 1 && hdr->version <= 3\)\)\n'
        r'        return 0;',
        '    if (hdr->version < 1 || hdr->version > 3)\n'
        '        return 0;',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T2: De Morgan")
    else:
        print("  T2: SKIPPED (pattern not found)")

    # T3: Cache loop count in local + change counter type to uint16_t
    old = source
    source = re.sub(
        r'    uint32_t hash = 5381;\n'
        r'\n'
        r'    for \(int i = 0; i < hdr->count; i\+\+\)',
        '    uint32_t hash = 5381;\n'
        '    uint16_t n = hdr->count;\n'
        '\n'
        '    for (uint16_t i = 0; i < n; i++)',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T3: cache count + uint16_t counter")
    else:
        print("  T3: SKIPPED (pattern not found)")

    # T4: hash * 33 ^ -> ((hash << 5) + hash) ^
    n_found = source.count('hash * 33 ^')
    if n_found > 0:
        source = source.replace('hash * 33 ^', '((hash << 5) + hash) ^')
        transforms_applied += 1
        print(f"  T4: shift-add ({n_found} replacements)")
    else:
        print("  T4: SKIPPED (pattern not found)")

    # T5: switch -> if/else-if chain
    old = source
    source = re.sub(
        r'        switch \(hdr->version\) \{\n'
        r'            case 2:\n'
        r'                hash \^= hash >> 16;\n'
        r'                break;\n'
        r'            case 3:\n'
        r'                hash \*= 0x01000193u;\n'
        r'                break;\n'
        r'        \}',
        '        if (hdr->version == 2) {\n'
        '            hash ^= hash >> 16;\n'
        '        } else if (hdr->version == 3) {\n'
        '            hash *= 0x01000193u;\n'
        '        }',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T5: switch -> if/else-if")
    else:
        print("  T5: SKIPPED (pattern not found)")

    # T6: Inline rotation temp variable
    old = source
    source = re.sub(
        r'        uint32_t rot = \(f << 5\) \| \(f >> 27\);\n'
        r'        f = rot \^ key;',
        '        f = ((f << 5) | (f >> 27)) ^ key;',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T6: inline rotation")
    else:
        print("  T6: SKIPPED (pattern not found)")

    # T7: Restructure swap to use nr pattern
    old = source
    source = re.sub(
        r'        left = left \^ \(f & 0xFFFF\);\n'
        r'        uint32_t tmp = left;\n'
        r'        left = right;\n'
        r'        right = tmp;',
        '        uint32_t nr = left ^ (f & 0xFFFF);\n'
        '        left = right;\n'
        '        right = nr;',
        source, count=1
    )
    if source != old:
        transforms_applied += 1
        print("  T7: nr swap pattern")
    else:
        print("  T7: SKIPPED (pattern not found)")

    print(f"\n  Applied {transforms_applied}/7 transformations")
    return source, transforms_applied


def build_corrected_source(candidate_source):
    """
    Fallback: construct the corrected source directly.
    Extracts the preamble (includes, macros, structs) from candidate.c
    and combines with known-correct function bodies that preserve
    cosmetic differences.
    """
    # Find where the first function starts
    func_marker = 'uint32_t hash_entries'
    idx = candidate_source.find(func_marker)
    if idx == -1:
        print("ERROR: cannot find hash_entries in candidate.c", file=sys.stderr)
        return None

    preamble = candidate_source[:idx]

    # Construct corrected functions preserving cosmetic differences:
    # - &data[off] (cosmetic: same as data + off at GIMPLE level)
    # - (hash >> 13), (hash >> 15) extra parens (cosmetic: >> higher prec than ^=)
    # - 0x5BD1E995 uppercase hex (cosmetic: same integer)
    # - return (hash) parens (cosmetic)
    # - unsigned int vs uint32_t (cosmetic: same type on x86-64 Linux)
    # - f = f * X, f = f ^ X, key = key + X (cosmetic: same GIMPLE as *=, ^=, +=)
    # - return ((left << 16) | right) extra outer parens (cosmetic)
    corrected = preamble + (
        'uint32_t hash_entries(const uint8_t *data, uint32_t size) {\n'
        '    if (size < sizeof(Header))\n'
        '        return 0;\n'
        '\n'
        '    const Header *hdr = (const Header *)data;\n'
        '\n'
        '    if (hdr->magic != MAGIC)\n'
        '        return 0;\n'
        '\n'
        '    if (hdr->version < 1 || hdr->version > 3)\n'
        '        return 0;\n'
        '\n'
        '    uint32_t hash = 5381;\n'
        '    uint16_t n = hdr->count;\n'
        '\n'
        '    for (uint16_t i = 0; i < n; i++) {\n'
        '        uint32_t off = hdr->data_offset + i * sizeof(Entry);\n'
        '        if (off + sizeof(Entry) > size)\n'
        '            break;\n'
        '\n'
        '        const Entry *e = (const Entry *)(&data[off]);\n'
        '\n'
        '        hash = ((hash << 5) + hash) ^ e->id;\n'
        '        hash = ((hash << 5) + hash) ^ e->value;\n'
        '\n'
        '        if (hdr->version == 2) {\n'
        '            hash ^= hash >> 16;\n'
        '        } else if (hdr->version == 3) {\n'
        '            hash *= 0x01000193u;\n'
        '        }\n'
        '    }\n'
        '\n'
        '    hash ^= (hash >> 13);\n'
        '    hash *= 0x5BD1E995;\n'
        '    hash ^= (hash >> 15);\n'
        '\n'
        '    return (hash);\n'
        '}\n'
        '\n'
        'uint32_t feistel_round(uint32_t block, uint32_t key, int rounds) {\n'
        '    unsigned int left = block >> 16;\n'
        '    unsigned int right = block & 0xFFFF;\n'
        '\n'
        '    for (int r = 0; r < rounds; r++) {\n'
        '        uint32_t f = right;\n'
        '        f = ((f << 5) | (f >> 27)) ^ key;\n'
        '        f = f * 0x9E3779B9;\n'
        '        f = f ^ (f >> 11);\n'
        '\n'
        '        uint32_t nr = left ^ (f & 0xFFFF);\n'
        '        left = right;\n'
        '        right = nr;\n'
        '\n'
        '        key = key + 0x61C88647;\n'
        '    }\n'
        '\n'
        '    return ((left << 16) | right);\n'
        '}\n'
    )
    return corrected


def create_analysis():
    analysis = {
        "codegen_affecting_count": 7,
        "cosmetic_count": 7,
        "differences": [
            {
                "description": "Declaration before size guard + combined || condition",
                "classification": "codegen",
                "reason": "Separate conditionals produce independent branch sequences; "
                          "combined || uses short-circuit. Declaration order changes "
                          "stack frame layout at -O0."
            },
            {
                "description": "Negated conjunction !(A >= 1 && A <= 3) vs "
                               "disjunction A < 1 || A > 3",
                "classification": "codegen",
                "reason": "GCC generates different comparison and branch instruction "
                          "patterns for negated && vs direct ||."
            },
            {
                "description": "int loop counter with direct hdr->count access vs "
                               "uint16_t counter with cached local n",
                "classification": "codegen",
                "reason": "int vs uint16_t changes comparison width (movsxd vs movzwl). "
                          "Direct struct access generates pointer dereference each iteration "
                          "vs stack-local load."
            },
            {
                "description": "hash * 33 vs ((hash << 5) + hash)",
                "classification": "codegen",
                "reason": "imull $33 instruction vs shl $5 + add sequence. Semantically "
                          "identical (33 = 2^5 + 1) but different opcodes."
            },
            {
                "description": "switch statement vs if/else-if chain for version check",
                "classification": "codegen",
                "reason": "switch generates different dispatch pattern (comparison cascade "
                          "with je to case bodies) vs if/else-if (sequential jne branches)."
            },
            {
                "description": "Temp variable rot for rotation vs inlined expression",
                "classification": "codegen",
                "reason": "Extra temp variable allocates additional stack slot and "
                          "generates extra mov instructions for store/reload at -O0."
            },
            {
                "description": "Modify left in-place + tmp swap vs direct nr computation",
                "classification": "codegen",
                "reason": "Different instruction sequence: XOR stored to left then copied "
                          "to tmp vs stored directly to nr. Different stack slot usage."
            },
            {
                "description": "&data[off] vs data + off (array subscript notation)",
                "classification": "cosmetic",
                "reason": "GCC folds ADDR_EXPR(ARRAY_REF(...)) to POINTER_PLUS_EXPR "
                          "during gimplification. Identical code at any -O level."
            },
            {
                "description": "Extra parentheses: (hash >> 13), (hash >> 15)",
                "classification": "cosmetic",
                "reason": "Redundant parens do not change the AST. >> has higher "
                          "precedence than ^= so the expression is parsed identically."
            },
            {
                "description": "Hex case: 0x5BD1E995 vs 0x5bd1e995",
                "classification": "cosmetic",
                "reason": "Hex digit case is insignificant in C. Same integer constant."
            },
            {
                "description": "return (hash) vs return hash",
                "classification": "cosmetic",
                "reason": "Parentheses around a return expression have no semantic "
                          "or codegen effect."
            },
            {
                "description": "unsigned int vs uint32_t in feistel_round locals",
                "classification": "cosmetic",
                "reason": "uint32_t is a typedef for unsigned int on x86-64 Linux. "
                          "They are the same type."
            },
            {
                "description": "Expanded compound assignments: f = f * X, f = f ^ X, "
                               "key = key + X",
                "classification": "cosmetic",
                "reason": "Compound assignment (*=, ^=, +=) is lowered to the expanded "
                          "form in GIMPLE before code generation. Both forms produce "
                          "identical instructions."
            },
            {
                "description": "Extra outer parentheses: return ((left << 16) | right)",
                "classification": "cosmetic",
                "reason": "Redundant outer parentheses in return expression do not "
                          "affect code generation."
            }
        ]
    }
    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("Wrote analysis.json")


def main():
    print("=== Step 1: Read candidate source ===")
    source = read_file('/app/candidate.c')
    print(f"Read {len(source)} bytes from candidate.c")

    print("\n=== Step 2: Apply regex transformations ===")
    transformed, n_applied = apply_regex_transforms(source)
    write_file('/app/candidate.c', transformed)

    print("\n=== Step 3: Verify .text match ===")
    if texts_match():
        print("Regex transformations produced matching code.")
    else:
        print("\nRegex approach did not produce matching code.")
        print("Falling back to direct source construction...\n")

        # Restore original and use fallback
        corrected = build_corrected_source(source)
        if corrected is None:
            print("ERROR: Fallback construction failed", file=sys.stderr)
            sys.exit(1)

        write_file('/app/candidate.c', corrected)
        print("Wrote fallback candidate.c")

        print("\n=== Step 3b: Verify fallback .text match ===")
        if not texts_match():
            print("ERROR: Even fallback source does not match target.o",
                  file=sys.stderr)
            # Show disassembly for debugging
            for label, obj in [("Target", "/app/target.o"),
                               ("Candidate", "/app/candidate.o")]:
                print(f"\n--- {label} ---")
                r = subprocess.run(["objdump", "-d", obj],
                                   capture_output=True, text=True)
                print(r.stdout[:4000])
            sys.exit(1)
        print("Fallback source matches target.o.")

    print("\n=== Step 4: Verify cosmetic differences preserved ===")
    final = read_file('/app/candidate.c')
    checks = [
        ("&data[off]", "&data[off] subscript notation"),
        ("0x5BD1E995", "uppercase hex constant"),
        ("unsigned int", "'unsigned int' type alias"),
    ]
    for pattern, name in checks:
        if pattern in final:
            print(f"  OK: {name} preserved")
        else:
            print(f"  WARN: {name} missing!")

    print("\n=== Step 5: Generate analysis.json ===")
    create_analysis()

    print("\n=== Done ===")


if __name__ == '__main__':
    main()
