The `/app/` directory contains a numeric data processing project. IEEE 754 double-precision test vectors are distributed across several subdirectories under `/app/data/` in heterogeneous formats. A project manifest at `/app/manifest.json` describes some of the data sources, but additional sources exist that are not listed — you must discover them.

A C++ project skeleton exists at `/app/src/float_tool.cpp` with a CMake build system (`/app/CMakeLists.txt`). The environment has GCC with C++17 `<charconv>` support.

## Required outputs

**1. C++ float tool** — Build a working executable at `/app/build/float_tool`. It must read decimal float strings from stdin (one per line), parse each to an IEEE 754 double, and write the corresponding 16-character lowercase hex bit pattern to stdout (one per line). Skip blank or whitespace-only lines.

**2. Conformance audit** — Discover and extract every unique IEEE 754 double-precision value from all data sources under `/app/data/`. Each source file uses a different encoding; examine each to determine parsing strategy. For each unique bit pattern, compute the shortest round-trip-safe decimal string. Write results to `/app/output/audit.csv`.

## audit.csv format

No header row. Comma-separated columns:

```
hex_bits,shortest_string,source_count,category
```

- `hex_bits`: 16-char lowercase hex of the 64-bit IEEE 754 pattern (e.g., `400921fb54442d18`)
- `shortest_string`: shortest decimal string that round-trips to this exact bit pattern
- `source_count`: number of distinct source files containing this value
- `category`: one of `zero`, `subnormal`, `normal`, `infinity`, `nan`

Sort rows ascending by `hex_bits` interpreted as unsigned 64-bit integer.

## Shortest string rules

Each string must round-trip: parsing it back to a double must reproduce the exact original 64-bit pattern. Among all valid strings, choose the one with fewest total characters.

| Value class | String |
|---|---|
| NaN (any payload) | `nan` |
| +inf / -inf | `inf` / `-inf` |
| +0 / -0 | `0` / `-0` |
| Fixed notation | `[-]digits[.digits]` — no trailing zeros after decimal, no trailing point, leading `0` for \|value\|<1 |
| Scientific notation | `[-]digit[.digits]e[-]digits` — no trailing zeros in mantissa, no trailing point, no leading zeros in exponent, no `+` on exponent |

Use whichever notation produces fewer characters. Ties go to fixed.