The Rust library at `/app/src/lib.rs` implements `FixedPoint<const FRAC: u32>`, a signed fixed-point number backed by `i64` where `FRAC` bits are fractional (value = `raw / 2^FRAC`). The library contains correctness bugs that must be identified and fixed.

The public API includes:

**Constructors**: `from_raw`, `from_int`, `from_f64`, `from_ratio(numer: i64, denom: i64) -> Option<Self>`.
`from_f64` must return `None` for NaN, infinity, and values outside representable range. `from_ratio` must return `None` on zero denominator or when the result cannot be represented.

**Four overflow families** for add, sub, mul, div, neg, abs — following Rust's standard integer overflow conventions:

- `checked_*`: return `Option<Self>` — `None` on overflow. `checked_div` returns `None` on division by zero.
- `wrapping_*`: return two's-complement wrapped result. Panic on division by zero only.
- `saturating_*`: clamp to `Self::MIN`/`Self::MAX` on overflow (toward the mathematically correct sign). Panic on division by zero only.
- `overflowing_*`: return `(Self, bool)` — wrapped result and whether overflow occurred. Panic on division by zero only.

**Operator overloads** (`+`, `-`, `*`, `/`, unary `-`): must panic on overflow or division by zero.

**Precision rescaling**: `checked_rescale<NEW_FRAC>`, `wrapping_rescale`, `saturating_rescale`, `overflowing_rescale` convert between different fractional bit-widths while preserving the represented numeric value.

**Fused multiply-add**: `checked_mul_add(self, mul, add)` and variants compute `self * mul + add`. The result must be correct whenever the mathematical answer is representable, regardless of whether partial sub-expressions would independently overflow.

**Midpoint**: `midpoint(self, other) -> Self` returns the arithmetic midpoint of the two values. Must produce correct results even when the sum of the two values would exceed `i64` range.

All arithmetic operations must produce correct results across the full range of `i64` inputs, not just values where naive fixed-width computations happen to avoid intermediate overflow. All changes must be within `/app/src/lib.rs`. Preserve existing public API signatures. Run `cargo test` from `/app/` to verify.
