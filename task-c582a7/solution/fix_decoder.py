#!/usr/bin/env python3
"""
Fixes the five bugs in the defmt decoder by analyzing the reference Rust
implementation and applying targeted corrections to decoder.py.

Bug 1: Bitfield max_byte = max_bit // 8 → (max_bit - 1) // 8
Bug 2: Signed hex bit width = 32 → INT_BITS.get(int_type, 32)
Bug 3: Debug hint propagation uses None → parent_hint_str
Bug 4: FormatSequence index read_u8() → read_u16_le()
Bug 5: ISO 8601 ms/us precision branches are swapped
"""

with open('/app/decoder.py', 'r') as f:
    content = f.read()

# --- Bug 1: Bitfield max_byte calculation ---
# Reference: In frame.rs, bitfield extraction uses (max_bit - 1) // 8
# to compute the last byte to read. When max_bit is a byte boundary
# (e.g., 8, 16), max_bit // 8 reads one extra byte.
content = content.replace(
    'max_byte = max_bit // 8',
    'max_byte = (max_bit - 1) // 8',
    1
)

# --- Bug 2: Signed integer hex formatting bit width ---
# Reference: In frame.rs, I128Hex uses type-specific casts:
# I8 → i8, I16 → i16, I32 → i32, I64 → i64, I128 → i128
# The Python code hardcodes bits = 32 for all types.
content = content.replace(
    '            bits = 32\n            uval',
    '            bits = INT_BITS.get(int_type, 32)\n            uval',
    1
)

# --- Bug 3a: Debug hint propagation for unsigned integers ---
# Reference: In frame.rs, when hint is Debug for Uxx:
#   Some(DisplayHint::Debug) => self.format_u128(*x, parent_hint, buf)
# The buggy code passes None instead of parent_hint_str.
content = content.replace(
    'return self._fmt_uint(value, None)',
    'return self._fmt_uint(value, parent_hint_str)',
    1
)

# --- Bug 3b: Debug hint propagation for signed integers ---
content = content.replace(
    'return self._fmt_int(value, int_type, None)',
    'return self._fmt_int(value, int_type, parent_hint_str)',
    1
)

# --- Bug 4: FormatSequence index reading ---
# Reference: In lib.rs, all format indices are u16 LE:
#   let index = bytes.read_u16::<LE>()?
# The buggy code reads u8 instead of u16 for sequence entries.
content = content.replace(
    '                    sub_idx = reader.read_u8()\n                    if sub_idx == 0:',
    '                    sub_idx = reader.read_u16_le()\n                    if sub_idx == 0:',
    1
)

# --- Bug 5: ISO 8601 ms/us precision swap ---
# Reference: In frame.rs:
#   TimePrecision::Millis => timestamp as i128 * 1_000_000 (ns)
#   TimePrecision::Micros => timestamp as i128 * 1_000 (ns)
# The buggy code has ms using microseconds and us using milliseconds.
# Fix by replacing the entire _iso8601 method body.
old_iso = '''    @staticmethod
    def _iso8601(value, precision):
        if precision == "ms":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000000:06d}Z"
        if precision == "us":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                milliseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000:03d}Z"'''

new_iso = '''    @staticmethod
    def _iso8601(value, precision):
        if precision == "ms":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                milliseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000:03d}Z"
        if precision == "us":
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=value
            )
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{value % 1000000:06d}Z"'''

content = content.replace(old_iso, new_iso, 1)

with open('/app/decoder.py', 'w') as f:
    f.write(content)

# Verify all replacements were applied
with open('/app/decoder.py', 'r') as f:
    fixed = f.read()

checks = [
    ('(max_bit - 1) // 8', 'Bug 1: bitfield max_byte'),
    ('INT_BITS.get(int_type, 32)', 'Bug 2: signed bit width'),
    ('self._fmt_uint(value, parent_hint_str)', 'Bug 3a: uint debug hint'),
    ('self._fmt_int(value, int_type, parent_hint_str)', 'Bug 3b: int debug hint'),
    ('sub_idx = reader.read_u16_le()', 'Bug 4: sequence u16'),
    ('milliseconds=value', 'Bug 5: iso8601 ms'),
]
for pattern, name in checks:
    assert pattern in fixed, f"Fix not applied: {name}"

print("All 5 fixes applied successfully.")
