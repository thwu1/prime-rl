#!/usr/bin/env python3
"""Generate CBOR test corpus files in /app/corpus/."""

import os
import binascii

corpus_dir = "/app/corpus"
os.makedirs(corpus_dir, exist_ok=True)

# Hex-encoded corpus files (one CBOR item per line, pipe directly to encoders)

integers = [
    "00",                   # 0 inline
    "1800",                 # 0 in u8 (non-preferred)
    "190000",               # 0 in u16 (non-preferred)
    "1a00000000",           # 0 in u32 (non-preferred)
    "17",                   # 23 inline
    "1817",                 # 23 in u8 (non-preferred)
    "1818",                 # 24 in u8 (preferred)
    "18fe",                 # 254 in u8
    "18ff",                 # 255 in u8 (preferred)
    "1900ff",               # 255 in u16 (non-preferred)
    "190100",               # 256 in u16 (preferred)
    "1903e8",               # 1000 in u16
    "1a0000ffff",           # 65535 in u32 (non-preferred)
    "20",                   # -1 inline
    "3800",                 # -1 in s8 (non-preferred)
    "38ff",                 # -256 (arg 255) in s8 (preferred)
    "3900ff",               # -256 in s16 (non-preferred)
    "3903e7",               # -1000 in s16
]

floats = [
    "f90000",               # +0.0 f16
    "f98000",               # -0.0 f16
    "fa00000000",           # +0.0 f32
    "fa80000000",           # -0.0 f32
    "fb0000000000000000",   # +0.0 f64
    "fb8000000000000000",   # -0.0 f64
    "f93c00",               # 1.0 f16
    "fa3f800000",           # 1.0 f32
    "fb3ff0000000000000",   # 1.0 f64
    "f93e00",               # 1.5 f16
    "fa3fc00000",           # 1.5 f32
    "fb3ff8000000000000",   # 1.5 f64
    "f97c00",               # +Inf f16
    "fa7f800000",           # +Inf f32
    "fb7ff0000000000000",   # +Inf f64
    "f9fc00",               # -Inf f16
    "faff800000",           # -Inf f32
    "fbfff0000000000000",   # -Inf f64
    "f97e00",               # NaN f16 (canonical)
    "fa7fc00000",           # NaN f32
    "fb7ff8000000000000",   # NaN f64
    "fa47c35000",           # 100000.0 f32 (exceeds f16 max)
    "fb40f86a0000000000",   # 100000.0 f64
    "fb3ff199999999999a",   # 1.1 f64 (not exact in f16/f32)
]

maps = [
    "a0",                           # empty map
    "a2616101616202",               # {"a":1, "b":2} sorted
    "a2616202616101",               # {"b":2, "a":1} unsorted
    "a201020304",                   # {1:2, 3:4} int keys
    "a21903e801617a02",             # {1000:1, "z":2} mixed types
    "a2617a021903e801",             # {"z":2, 1000:1} reversed
    "a8f4008120018118640262616103617a0420051864060a07",  # RFC 8-key example
]

containers = [
    "80",                           # [] empty array
    "83010203",                     # [1, 2, 3] definite
    "9f010203ff",                   # [1, 2, 3] indefinite
    "9fff",                         # [] indefinite empty
    "5f42010243030405ff",           # indefinite byte string
    "7f657374726561646d696e67ff",   # indefinite text "streaming"
    "bf616101616202ff",             # indefinite map {"a":1, "b":2}
    "8181190000",                   # [[u16(0)]] nested
]

tags = [
    "c100",                                 # tag(1) + 0
    "db000000000000000100",                 # tag(1) + 0 via u64 (non-preferred)
    "c11903e8",                             # tag(1) + 1000
    "c11a000003e8",                         # tag(1) + u32(1000) (non-preferred)
    "c249010000000000000000",               # tag(2) + bignum
]

for name, data in [("integers", integers), ("floats", floats),
                    ("maps", maps), ("containers", containers), ("tags", tags)]:
    with open(os.path.join(corpus_dir, f"{name}.hex"), "w") as f:
        for line in data:
            f.write(line + "\n")

# Combined corpus
with open(os.path.join(corpus_dir, "all.hex"), "w") as f:
    for dataset in [integers, floats, maps, containers, tags]:
        for line in dataset:
            f.write(line + "\n")

# Raw binary CBOR files (require xxd -p to view as hex)
binary_samples = {
    # Map with 8 mixed-type keys in non-deterministic order
    "mixed_map.cbor": (
        "a8"
        "f400"           # false: 0
        "812001"         # [-1]: 1
        "81186402"       # [100]: 2
        "62616103"       # "aa": 3
        "617a04"         # "z": 4
        "2005"           # -1: 5
        "186406"         # 100: 6
        "0a07"           # 10: 7
    ),
    # Nested: {"vals": [NaN(f64), -0.0(f32), 1.0(f32)], "count": u32(3)}
    "nested.cbor": (
        "a2"
        "6576616c73"                 # "vals"
        "83"                         # array(3)
        "fb7ff8000000000000"         # NaN f64
        "fa80000000"                 # -0.0 f32
        "fa3f800000"                 # 1.0 f32
        "65636f756e74"               # "count"
        "1a00000003"                 # u32(3)
    ),
    # Non-preferred encodings: [u16(0), u8(23), indef[1,2]]
    "nonpreferred.cbor": (
        "83"                         # array(3)
        "190000"                     # u16(0) non-preferred
        "1817"                       # u8(23) non-preferred
        "9f0102ff"                   # indef [1, 2]
    ),
}

for name, hex_data in binary_samples.items():
    with open(os.path.join(corpus_dir, name), "wb") as f:
        f.write(binascii.unhexlify(hex_data))

print(f"Generated corpus in {corpus_dir}")
