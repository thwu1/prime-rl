A partial `<charconv>`-equivalent library resides at `/app/`. The `myconv` namespace in `/app/charconv.cpp` (header: `/app/charconv.hpp`) provides `to_chars` and `from_chars` for all standard integer types (bases 2–36) and floating-point types (`float`/`double`), including `chars_format`-parameterized overloads. The implementation contains multiple conformance defects against the C++17 charconv specification. A normative excerpt is at `/app/spec_reference.txt`. Fix all defects so the library passes verification.

**Integer `to_chars`**: Converts value to characters in `[first, last)` using digits `0`–`9` and lowercase `a`–`z` for bases above 10. Negative signed values are prefixed with `'-'`. Must handle the full range of every signed type including its minimum value. Returns `{ptr, errc::ok}` or `{last, errc::value_too_large}`.

**Integer `from_chars`**: Parses the `strtol`-style subject sequence in the `"C"` locale. No `"0x"`/`"0X"` prefix for base 16. Only `'-'` sign (no `'+'`), only for signed types. Must detect overflow precisely at the representable-range boundary for every type width.

**Float `to_chars(first, last, value)`**: Shortest decimal string whose `from_chars` recovers `value` exactly. Each type (`float`/`double`) must target its own precision—`to_chars(float)` must not simply widen to `double`. Style is `f` or `e` (shorter wins; tie favors `f`). Handles `±0`, `±inf`, `nan`.

**Float `to_chars(first, last, value, fmt)`**: Shortest representation restricted to the format determined by `fmt` (`f` for fixed, `e` for scientific, `a`-without-`"0x"` for hex, `g` for general) that still round-trips.

**Float `to_chars(first, last, value, fmt, precision)`**: `printf`-style conversion in the `"C"` locale at the given precision for the format determined by `fmt`. Hex output must omit the `"0x"` prefix.

**Float `from_chars(first, last, value, fmt)`**: Parses the `strtod`-style subject sequence in the `"C"` locale. Only `'-'` sign, no leading whitespace, no `"0x"` prefix for decimal formats. Must respect `[first, last)` and be locale-independent. Scientific requires an exponent; fixed forbids it; hex accepts a hex-float pattern (`hex_digits[.hex_digits]p[±]dec_digits`, no `"0x"` prefix). Returns `errc::result_out_of_range` on overflow—including when a `double` result overflows `float`. Underflow to subnormal/zero is not an error. Value unmodified on any error.

**Constraints:**
- Do not `#include <charconv>`.
- Do not modify `/app/charconv.hpp`.
- All fixes go in `/app/charconv.cpp`.
- Build: `make -C /app`.
