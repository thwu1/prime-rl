#!/usr/bin/env python3
"""
Apply all fixes to the InChI processing pipeline.

Fixes:
1. CMakeLists.txt - add missing src/sdf_parser.c
2. inchikey.c - fix triplet table loop variable mapping (k->s[0], i->s[2] => i->s[0], k->s[2])
3. inchikey.c - fix byte endianness (digest[nbytes-1-i] => digest[i])
4. inchikey.c - fix standard InChI prefix detection
5. sdf_parser.c - strip newline from value_line before copying
6. dedup.c - implement dedup_insert with open-addressing hash table
"""

import os

# ======================================================================
# Fix 1: CMakeLists.txt — add missing src/sdf_parser.c
# ======================================================================

cmake_path = "/app/CMakeLists.txt"
with open(cmake_path, "r") as f:
    cmake = f.read()

cmake = cmake.replace(
    """add_executable(inchi_pipeline
    src/main.c
    src/inchikey.c
    src/sha256.c
    src/dedup.c
)""",
    """add_executable(inchi_pipeline
    src/main.c
    src/inchikey.c
    src/sha256.c
    src/sdf_parser.c
    src/dedup.c
)""",
)

with open(cmake_path, "w") as f:
    f.write(cmake)
print("Fix 1: Added src/sdf_parser.c to CMakeLists.txt")


# ======================================================================
# Fix 2-4: inchikey.c
# ======================================================================

inchikey_path = "/app/src/inchikey.c"
with open(inchikey_path, "r") as f:
    code = f.read()

# Fix 2: Triplet table loop variable mapping.
# The variables i,j,k iterate as outer/middle/inner.
# Currently: s[0]='A'+k (inner), s[2]='A'+i (outer) — WRONG.
# Correct:   s[0]='A'+i (outer), s[2]='A'+k (inner).
code = code.replace(
    """                s[0] = (char)('A' + k);
                s[1] = (char)('A' + j);
                s[2] = (char)('A' + i);""",
    """                s[0] = (char)('A' + i);
                s[1] = (char)('A' + j);
                s[2] = (char)('A' + k);""",
)
print("Fix 2: Fixed triplet table loop variable mapping")

# Fix 3: Byte endianness in encode_base26.
# Currently copies bytes in reverse (big-endian) order.
# InChI spec uses little-endian: byte 0 of digest -> byte 0 of data.
code = code.replace(
    "data[i] = digest[nbytes - 1 - i];",
    "data[i] = digest[i];",
)
print("Fix 3: Fixed byte endianness in encode_base26")

# Fix 4: Standard InChI prefix detection.
# Currently always skips 8 characters ("InChI=1/") and sets flag='N'.
# Need to detect 'S' marker at position 7 for standard InChI.
code = code.replace(
    """    const char *content = inchi + 8;   /* skip past "InChI=1/" */
    char flag = 'N';""",
    """    const char *p = inchi + 7;
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
print("Fix 4: Fixed standard InChI prefix detection")

with open(inchikey_path, "w") as f:
    f.write(code)


# ======================================================================
# Fix 5: sdf_parser.c — strip newline from InChI value line
# ======================================================================

sdf_path = "/app/src/sdf_parser.c"
with open(sdf_path, "r") as f:
    sdf_code = f.read()

# The parser reads the InChI value with fgets but doesn't strip the
# trailing newline. Add strip_newline(value_line) before copying.
sdf_code = sdf_code.replace(
    """            char value_line[4096];
            if (fgets(value_line, sizeof(value_line), fp)) {
                strncpy(records[count].inchi, value_line,
                        SDF_MAX_INCHI - 1);""",
    """            char value_line[4096];
            if (fgets(value_line, sizeof(value_line), fp)) {
                strip_newline(value_line);
                strncpy(records[count].inchi, value_line,
                        SDF_MAX_INCHI - 1);""",
)
print("Fix 5: Added strip_newline to SDF InChI value extraction")

with open(sdf_path, "w") as f:
    f.write(sdf_code)


# ======================================================================
# Fix 6: dedup.c — implement dedup_insert
# ======================================================================

dedup_path = "/app/src/dedup.c"
with open(dedup_path, "r") as f:
    dedup_code = f.read()

# Replace the stub implementation with a working open-addressing hash table
dedup_code = dedup_code.replace(
    """int dedup_insert(dedup_table *table, const char *key, int record_index)
{
    /*
     * TODO: Implement open-addressing hash table insertion with
     * linear probing.
     *
     * Hash the key string to determine a starting slot index.
     * Probe linearly until finding either:
     *   - An occupied slot with matching key: return that slot's
     *     record_index (duplicate detected).
     *   - An unoccupied slot: store the key and record_index,
     *     mark as occupied, return -1 (new entry).
     * If all slots have been probed without a match or empty slot,
     * return -2 (table full).
     */
    (void)table;
    (void)key;
    (void)record_index;
    return -1;  /* Stub: always reports "no duplicate" */
}""",
    """int dedup_insert(dedup_table *table, const char *key, int record_index)
{
    if (!table || !key || table->count >= table->capacity)
        return -2;

    /* djb2 hash */
    unsigned long hash = 5381;
    for (const char *p = key; *p; p++)
        hash = ((hash << 5) + hash) + (unsigned char)*p;

    int start = (int)(hash % (unsigned long)table->capacity);

    for (int i = 0; i < table->capacity; i++) {
        int probe = (start + i) % table->capacity;
        if (!table->entries[probe].occupied) {
            strncpy(table->entries[probe].key, key, 27);
            table->entries[probe].key[27] = '\\0';
            table->entries[probe].record_index = record_index;
            table->entries[probe].occupied = 1;
            table->count++;
            return -1;
        }
        if (strcmp(table->entries[probe].key, key) == 0) {
            return table->entries[probe].record_index;
        }
    }

    return -2;
}""",
)
print("Fix 6: Implemented dedup_insert with open-addressing hash table")

with open(dedup_path, "w") as f:
    f.write(dedup_code)


print("\nAll fixes applied successfully.")
