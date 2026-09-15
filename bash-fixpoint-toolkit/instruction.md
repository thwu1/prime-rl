A pure-bash arithmetic toolkit at `/app/arith.sh` provides base conversion between bases 2–64, fixed-point decimal arithmetic, and octal-safe number sanitization using only bash arithmetic (`$(( ))`, `(( ))`, `let`). No external tools (`bc`, `dc`, `awk`, `python`, `perl`) may be used in the implementation. The script has multiple bugs across its subcommands. Fix all of them so every subcommand produces correct output.

**Base conversion** (`from_base`, `to_base`, `base_convert`):

- `arith.sh from_base <base> <number>` — parse a base-N literal and print its decimal value.
- `arith.sh to_base <base> <decimal>` — print the decimal integer in the target base.
- `arith.sh base_convert <from> <to> <number>` — convert between arbitrary bases.
- Bases range 2–64. Digit alphabet for values 0–63: `0-9`, `a-z`, `A-Z`, `@`, `_`. For bases ≤ 36, case is interchangeable on input. For bases > 36, `a`–`z` = 10–35, `A`–`Z` = 36–61, `@` = 62, `_` = 63.
- `to_base` must handle zero and negative decimal inputs. Negative outputs use a leading `-`.

**Fixed-point arithmetic** (`fp_add`, `fp_mul`, `fp_div`):

- `arith.sh fp_add <a> <b> <precision>`, `fp_mul`, `fp_div` — addition, multiplication, and division respectively.
- Division truncates toward zero; divide-by-zero → error.
- Operands are decimal strings (e.g., `1.5`, `-3.25`, `100`). Precision is the number of fractional digits in the output.
- Input fractional parts shorter than precision are right-padded with zeros (`1.5` at precision 4 → `1.5000`).
- Output: `<integer>.<frac>` with exactly `<precision>` fractional digits.
- Intermediate calculations must not overflow 64-bit signed integers when the final result is representable.

**Fixed-point square root** (`fp_sqrt`):

- `arith.sh fp_sqrt <value> <precision>` — compute the square root to the specified precision, truncating toward zero.
- Negative input → nonzero exit, error to stderr. Zero → `0` with the correct number of fractional digits.
- Must not overflow 64-bit for results representable in the output precision.

**Fixed-point exponentiation** (`fp_pow`):

- `arith.sh fp_pow <base> <integer_exponent> <precision>` — raise a fixed-point number to a non-negative integer power.
- Exponent 0 → `1` with the correct fractional digits. Negative base with odd exponent → negative result.
- Must not overflow 64-bit for representable results.

**Sanitize** (`sanitize`):

- `arith.sh sanitize <number>` — interpret a possibly zero-padded string as base-10 and print it, handling signed inputs (`-019` → `-19`, `+008` → `8`).

All output to stdout, one value per line. Errors to stderr with nonzero exit.
