#!/usr/bin/env python3
"""
Apply three fixes to /app/inchikey.c
"""

with open("/app/inchikey.c", "r") as f:
    code = f.read()

# ======================================================================
# Fix 1: Triplet table loop order
# The outer loop must iterate 'a' (first letter) and the inner loop 'c'
# (third letter). Currently they are swapped.
# ======================================================================
code = code.replace(
    """    for (int c = 0; c < 26; c++) {
        for (int b = 0; b < 26; b++) {
            for (int a = 0; a < 26; a++) {""",
    """    for (int a = 0; a < 26; a++) {
        for (int b = 0; b < 26; b++) {
            for (int c = 0; c < 26; c++) {""",
)

# ======================================================================
# Fix 2: Byte order in encode_base26
# Change from big-endian (reversed) to little-endian (direct) copy.
# ======================================================================
code = code.replace(
    "data[i] = digest[nbytes - 1 - i];",
    "data[i] = digest[i];",
)

# ======================================================================
# Fix 3: InChI prefix parsing
# Detect the standard marker 'S' between version '1' and '/' separator.
# ======================================================================
code = code.replace(
    """    const char *content = inchi + 8;   /* skip past "InChI=1/" */
    char flag = 'N';""",
    """    const char *p = inchi + 7;  /* point after "InChI=1" */
    char flag;
    if (*p == 'S') {
        flag = 'S';
        p++;
    } else {
        flag = 'N';
    }
    if (*p != '/') return -1;
    p++;
    const char *content = p;""",
)

with open("/app/inchikey.c", "w") as f:
    f.write(code)

print("All three bugs fixed in /app/inchikey.c")
