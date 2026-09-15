The SQLite database `/app/challenge.db` contains table `ieee754_values(id INTEGER PRIMARY KEY, hex_bits TEXT, category TEXT, precision_class TEXT)` with 100 IEEE 754 double-precision values encoded as 16-character uppercase hex strings of their 64-bit big-endian bit patterns (e.g., `3FF0000000000000` = 1.0). Values span categories including `special`, `exact_power2`, `small_integer`, `denormal`, `boundary`, `near_power10`, `high_precision`, `notation_crossover`, `multi_digit`, and `random`.

Two C converters are provided in `/app/src/`:
- `naive_convert.c`: Uses `%.17g` — always round-trip safe but never shortest.
- `fast_convert.c`: Attempts shortest representations using iterative precision search with C's `%e` formatting, but contains bugs that produce incorrect output for certain value classes. Build both with `make` in `/app`.

A Go round-trip verifier is at `/app/verify.go` (build with `go build -o /app/verify_bin /app/verify.go`; it reads `/app/results.json` and checks bit-exact round-trip via `strconv.ParseFloat`).

Produce `/app/results.json` conforming to `/app/output_schema.json`, containing:

1. A `results` array with one entry per database row: `id`, `hex_bits`, `category`, `shortest` (the absolutely shortest round-trip-safe decimal string), `notation` (`"fixed"`, `"scientific"`, or `"special"`), `min_digits` (minimum significant decimal digits required for round-trip safety; 0 for specials), `predecessor_hex` (16-char hex of the next smaller representable double in IEEE 754 total order, or `null` for NaN/Inf/-Inf), `successor_hex` (16-char hex of the next larger representable double in IEEE 754 total order, or `null` for NaN/Inf/-Inf).

2. A `divergences` array listing every value where `fast_convert` output differs from the correct shortest representation: `id`, `fast_output` (what fast_convert produced), `correct_output` (the correct shortest string), `bug_class` (one of `"negative_zero"`, `"exponent_padding"`, `"notation_selection"`).

3. A `summary` object keyed by category with `count`, `scientific_count`, `fixed_count`, `special_count`.

Shortest representation rules:
- **Round-trip**: parsing the string with any IEEE 754-compliant parser (C `strtod`, Go `strconv.ParseFloat`, Python `float()`) must yield a double with identical bit pattern to the original.
- **Minimality**: no valid string with fewer characters satisfying round-trip exists.
- **Notation**: use whichever of fixed or scientific is shorter; ties go to fixed.
- **Formatting**: no trailing zeros after decimal point, no unnecessary decimal point, no `+` or leading zeros in exponents, lowercase `e`, digit before decimal point.
- **Specials**: `NaN`, `Inf`, `-Inf`, `0`, `-0`.

Predecessor/successor rules:
- For +0: predecessor is -0 (`8000000000000000`), successor is smallest positive subnormal (`0000000000000001`).
- For -0: predecessor is smallest negative subnormal (`8000000000000001`), successor is +0 (`0000000000000000`).
- For other finite values: the immediately adjacent representable doubles in IEEE 754 total order obtained by decrementing/incrementing the bit pattern (with sign-magnitude arithmetic).
- For NaN, +Inf, -Inf: `null`.