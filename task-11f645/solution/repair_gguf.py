#!/usr/bin/env python3
"""Repair corrupted GGUF v3 file.

Strategy: Read the corrupted binary and apply in-place byte patches to fix
all 5 structural defects. The key insight is that all corruptions are value
changes at specific byte offsets — no insertions or deletions — so the file
layout is identical to a correct file; only specific field values are wrong.

Diagnosis approach:
1. Read header → notice version is 2 (should be 3)
2. Walk metadata KV pairs manually, cross-checking against spec →
   discover kv_count is wrong (12 vs actual 14) and one type tag is
   corrupted (UINT32 instead of UINT64), causing cascading parse failure
3. Walk tensor info → discover one tensor type is wrong (Q2_K vs Q4_0)
4. Inspect alignment padding → discover non-zero padding bytes
"""

import struct


def main():
    with open('/app/model.gguf', 'rb') as f:
        data = bytearray(f.read())

    # --- Helper functions for reading GGUF binary ---
    def ru32(o):
        return struct.unpack_from('<I', data, o)[0]

    def ru64(o):
        return struct.unpack_from('<Q', data, o)[0]

    def rstr(o):
        n = ru64(o)
        return data[o + 8:o + 8 + n].decode('utf-8'), o + 8 + n

    # Fixed-size value sizes by metadata type tag
    FIXED_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1,
                   10: 8, 11: 8, 12: 8}

    def skip_val(o, t):
        """Skip a metadata value of the given type, returning offset after it."""
        if t == 8:  # STRING
            n = ru64(o)
            return o + 8 + n
        if t == 9:  # ARRAY
            et = ru32(o)
            cnt = ru64(o + 4)
            o += 12
            for _ in range(cnt):
                o = skip_val(o, et)
            return o
        return o + FIXED_SIZES[t]

    def valid_key_at(o):
        """Check if a valid GGUF metadata key string starts at offset o."""
        try:
            n = ru64(o)
            if n < 1 or n > 300:
                return False
            k = data[o + 8:o + 8 + n].decode('utf-8')
            return all(32 < ord(c) < 127 for c in k) and '.' in k
        except Exception:
            return False

    def try_tensor_infos(o, cnt):
        """Try parsing cnt tensor info entries at offset o.
        Returns the offset after all entries if successful, None if parsing fails."""
        for _ in range(cnt):
            try:
                n = ru64(o)
                if n < 1 or n > 200:
                    return None
                o += 8 + n
                nd = ru32(o)
                o += 4
                if nd < 1 or nd > 4:
                    return None
                for _ in range(nd):
                    d = ru64(o)
                    o += 8
                    if d > 100000:
                        return None
                tt = ru32(o)
                o += 4
                if tt > 40:
                    return None
                o += 8  # offset field
            except Exception:
                return None
        return o

    # --- Parse and fix header ---
    assert data[0:4] == b'GGUF', "Not a GGUF file"
    tc = int(ru64(8))

    # DEFECT 1: Version must be 3 (found 2)
    struct.pack_into('<I', data, 4, 3)

    # --- Walk metadata KV pairs to find actual count and type-tag bugs ---
    # The declared kv_count may be wrong, and one type tag may be corrupted.
    # Strategy: parse KV entries one by one, at each step checking if the
    # remaining data can be parsed as tensor_count tensor info entries.
    # If it can, we've reached the end of metadata.
    # If a type tag produces invalid subsequent parsing, try alternative types.

    o = 24  # start of metadata (after header fixed fields)
    actual_kv = 0
    type_tag_fixes = []

    while True:
        # Check: can the remaining data be parsed as tensor infos?
        if try_tensor_infos(o, tc) is not None:
            break

        # Not tensor infos → must be another KV entry
        if not valid_key_at(o):
            break

        key, key_end = rstr(o)
        tag_off = key_end
        tag = ru32(tag_off)
        val_off = tag_off + 4

        # Try skipping value with declared type
        try:
            next_off = skip_val(val_off, tag)
        except Exception:
            break

        # Validate: does the next position lead to valid continuation?
        good = (valid_key_at(next_off) or
                try_tensor_infos(next_off, tc) is not None)

        if not good and tag == 4:
            # DEFECT 3: Try UINT64 (type=10) instead of UINT32 (type=4)
            # This is a common serializer bug where a uint64 value's type tag
            # was incorrectly written as UINT32, causing a 4-byte parse shift.
            try:
                alt_next = skip_val(val_off, 10)
                if (valid_key_at(alt_next) or
                        try_tensor_infos(alt_next, tc) is not None):
                    type_tag_fixes.append((tag_off, 10))
                    next_off = alt_next
                    good = True
            except Exception:
                pass

        if not good:
            # Accept as last entry even without validation of what follows
            actual_kv += 1
            o = next_off
            break

        actual_kv += 1
        o = next_off

    # DEFECT 2: Fix metadata_kv_count in header
    struct.pack_into('<Q', data, 16, actual_kv)

    # Apply type tag fixes
    for tag_off, new_tag in type_tag_fixes:
        struct.pack_into('<I', data, tag_off, new_tag)

    # --- Walk tensor info and fix type bugs ---
    # First pass: collect all tensor info entries with their offsets
    tensor_entries = []
    tensor_start_o = o
    for i in range(tc):
        _, o = rstr(o)
        nd = ru32(o)
        o += 4
        n_el = 1
        for _ in range(nd):
            d = ru64(o)
            o += 8
            n_el *= d
        type_off = o
        tt = ru32(o)
        o += 4
        toff = ru64(o)
        o += 8
        tensor_entries.append((n_el, type_off, tt, toff))

    # DEFECT 4: Check for Q2_K (10) that should be Q4_0 (2)
    # Verify by checking whether the allocated data space between tensor
    # offsets is consistent with Q4_0 (18 bytes/32 elements) or Q2_K
    # (82 bytes/256 elements). The actual tensor data was written as Q4_0.
    for i, (n_el, type_off, tt, toff) in enumerate(tensor_entries):
        if tt == 10 and n_el % 32 == 0:
            # Compute expected data size for Q4_0 vs Q2_K
            q4_0_size = (n_el // 32) * 18
            q2_k_size = (n_el // 256) * 82 if n_el % 256 == 0 else None
            # Check available space to next tensor
            if i < len(tensor_entries) - 1:
                available = tensor_entries[i + 1][3] - toff
            else:
                # Last tensor: check total file size
                alignment = 64
                header_end_approx = o
                pad = (alignment - (header_end_approx % alignment)) % alignment
                tds = header_end_approx + pad
                available = len(data) - tds - toff
            # Q4_0 data (576 bytes) is larger than Q2_K data (328 bytes)
            # If available space accommodates Q4_0 but is too large for Q2_K
            # alignment, it's Q4_0
            if q2_k_size is None or available >= q4_0_size:
                struct.pack_into('<I', data, type_off, 2)

    # DEFECT 5: Fix alignment padding (must be 0x00, not 0xFF)
    header_end = o
    alignment = 64
    pad_needed = (alignment - (header_end % alignment)) % alignment
    for i in range(header_end, header_end + pad_needed):
        data[i] = 0x00

    # --- Write repaired file ---
    with open('/app/output.gguf', 'wb') as f:
        f.write(data)

    print(f"Repaired: /app/output.gguf ({len(data)} bytes)")
    print(f"  Fixed version: 2 -> 3")
    print(f"  Fixed kv_count: -> {actual_kv}")
    print(f"  Fixed {len(type_tag_fixes)} type tag(s)")
    print(f"  Zeroed {pad_needed} padding bytes")


main()
