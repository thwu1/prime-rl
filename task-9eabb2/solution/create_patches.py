#!/usr/bin/env python3
"""
Create MAGMA-compatible ground-truth instrumentation patches for libmfp.

Reads the clean source from /app/src_backup/mfp.c, generates patched variants
for each bug, and produces unified diffs at /app/patches/MFP00X.patch.
"""


import os
import difflib

SRC = "/app/src_backup/mfp.c"
PATCHES_DIR = "/app/patches"
os.makedirs(PATCHES_DIR, exist_ok=True)


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def make_patch(bug_id, original, modified):
    """Generate a unified diff patch between original and modified source."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(orig_lines, mod_lines,
                                fromfile='a/mfp.c', tofile='b/mfp.c')
    patch_content = ''.join(diff)

    if not patch_content:
        raise RuntimeError(f"Empty patch for {bug_id} — replacement string not found in source")

    patch_path = os.path.join(PATCHES_DIR, f"{bug_id}.patch")
    write_file(patch_path, patch_content)
    print(f"Created {patch_path} ({len(patch_content)} bytes)")


original = read_file(SRC)


# ── MFP001: Integer truncation in mfp_normalize ─────────────────────
# The uint32_t cast truncates the 64-bit product when data_len * scale > UINT32_MAX.
# Fix: compute full 64-bit product, check for overflow, reject if truncation occurs.
# Oracle: detect when truncation changes the value.

mod001 = original.replace(
    '        uint32_t new_len = (uint32_t)((uint64_t)e->data_len * scale);',
    '#ifdef MAGMA_ENABLE_FIXES\n'
    '        uint64_t full_len = (uint64_t)e->data_len * scale;\n'
    '        if ((uint32_t)full_len != full_len) return -1;\n'
    '        uint32_t new_len = (uint32_t)full_len;\n'
    '#else\n'
    '        uint32_t new_len = (uint32_t)((uint64_t)e->data_len * scale);\n'
    '#ifdef MAGMA_ENABLE_CANARIES\n'
    '        MAGMA_LOG("%MAGMA_BUG%", (uint64_t)e->data_len * scale != (uint64_t)new_len);\n'
    '#endif\n'
    '#endif'
)
make_patch("MFP001", original, mod001)


# ── MFP002: Missing bounds check in name parsing ────────────────────
# name_len from the input is used directly in memcpy without checking
# that offset + name_len <= buf_len.
# Fix: add bounds check before the memcpy.
# Oracle: detect when the read would exceed the buffer.

mod002 = original.replace(
    '        uint32_t name_len = doc->entries[i].name_len;\n'
    '\n'
    '        doc->entries[i].name = (char *)malloc(name_len + 1);',

    '        uint32_t name_len = doc->entries[i].name_len;\n'
    '\n'
    '#ifdef MAGMA_ENABLE_FIXES\n'
    '        if (offset + name_len > buf_len) return -1;\n'
    '#else\n'
    '#ifdef MAGMA_ENABLE_CANARIES\n'
    '        MAGMA_LOG("%MAGMA_BUG%", MAGMA_AND(name_len > 0, offset + name_len > buf_len));\n'
    '#endif\n'
    '#endif\n'
    '        doc->entries[i].name = (char *)malloc(name_len + 1);'
)
make_patch("MFP002", original, mod002)


# ── MFP003: Off-by-one in entry parsing loop ────────────────────────
# Loop uses <= where < is needed, causing one extra iteration that writes
# past the allocated entry array.
# Fix: change <= to <.
# Oracle: detect when the loop index reaches num_entries (out of bounds).

mod003 = original.replace(
    '    for (uint32_t i = 0; i <= doc->num_entries; i++) {\n'
    '        if (offset + 8 > buf_len) break;',

    '#ifdef MAGMA_ENABLE_FIXES\n'
    '    for (uint32_t i = 0; i < doc->num_entries; i++) {\n'
    '#else\n'
    '    for (uint32_t i = 0; i <= doc->num_entries; i++) {\n'
    '#ifdef MAGMA_ENABLE_CANARIES\n'
    '        MAGMA_LOG("%MAGMA_BUG%", i >= doc->num_entries);\n'
    '#endif\n'
    '#endif\n'
    '        if (offset + 8 > buf_len) break;'
)
make_patch("MFP003", original, mod003)


# ── MFP004: Division by zero in render_summary ──────────────────────
# Divides sum by e->type without checking for zero.
# Fix: guard against zero divisor.
# Oracle: detect when e->type is zero.

mod004 = original.replace(
    '            avg_value = sum / e->type;',

    '#ifdef MAGMA_ENABLE_FIXES\n'
    '            avg_value = (e->type != 0) ? sum / e->type : 0;\n'
    '#else\n'
    '#ifdef MAGMA_ENABLE_CANARIES\n'
    '            MAGMA_LOG("%MAGMA_BUG%", e->type == 0);\n'
    '#endif\n'
    '            avg_value = sum / e->type;\n'
    '#endif'
)
make_patch("MFP004", original, mod004)


print("\nAll patches created.")
