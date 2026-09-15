
use std::fmt;
use std::ops::{Add, Div, Mul, Neg, Sub};

/// A signed fixed-point number with `FRAC` fractional bits, backed by `i64`.
///
/// The numeric value represented is `raw / 2^FRAC`.
/// `FRAC` must be in the range `0..=62`.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct FixedPoint<const FRAC: u32> {
    raw: i64,
}

impl<const FRAC: u32> FixedPoint<FRAC> {
    /// The zero value.
    pub const ZERO: Self = Self { raw: 0 };

    /// The value `1.0` in this fixed-point format.
    pub const ONE: Self = Self { raw: 1i64 << FRAC };

    /// The minimum representable value.
    pub const MIN: Self = Self { raw: i64::MIN };

    /// The maximum representable value.
    pub const MAX: Self = Self { raw: i64::MAX };

    /// The smallest positive representable value.
    pub const EPSILON: Self = Self { raw: 1 };

    /// Creates a `FixedPoint` from its raw bit representation.
    pub const fn from_raw(raw: i64) -> Self {
        Self { raw }
    }

    /// Returns the raw bit representation.
    pub const fn to_raw(self) -> i64 {
        self.raw
    }

    /// Creates a `FixedPoint` from an integer value.
    /// Returns `None` if the value cannot be exactly represented.
    pub const fn from_int(val: i64) -> Option<Self> {
        if FRAC == 0 {
            return Some(Self { raw: val });
        }
        if FRAC >= 63 {
            if val == 0 {
                return Some(Self::ZERO);
            } else {
                return None;
            }
        }
        let shifted = val << FRAC;
        if (shifted >> FRAC) != val {
            None
        } else {
            Some(Self { raw: shifted })
        }
    }

    /// Creates a `FixedPoint` from an `f64` value.
    /// Returns `None` if the value is not finite or cannot be represented.
    pub fn from_f64(val: f64) -> Option<Self> {
        let scale = (1u64 << FRAC) as f64;
        let scaled = val * scale;
        Some(Self { raw: scaled as i64 })
    }

    /// Creates a `FixedPoint` representing `numer / denom`.
    /// Returns `None` if `denom` is zero or the result overflows.
    pub fn from_ratio(numer: i64, denom: i64) -> Option<Self> {
        if denom == 0 {
            return None;
        }
        let shifted = numer << FRAC;
        Some(Self { raw: shifted / denom })
    }

    /// Converts to `f64` (may lose precision for large values).
    pub fn to_f64(self) -> f64 {
        let scale = (1u64 << FRAC) as f64;
        self.raw as f64 / scale
    }

    // ================================================================
    // Checked family: return None on overflow, never panic (except
    // checked_div returns None for division by zero).
    // ================================================================

    pub const fn checked_add(self, rhs: Self) -> Option<Self> {
        match self.raw.checked_add(rhs.raw) {
            Some(r) => Some(Self { raw: r }),
            None => None,
        }
    }

    pub const fn checked_sub(self, rhs: Self) -> Option<Self> {
        match self.raw.checked_sub(rhs.raw) {
            Some(r) => Some(Self { raw: r }),
            None => None,
        }
    }

    pub const fn checked_mul(self, rhs: Self) -> Option<Self> {
        match self.raw.checked_mul(rhs.raw) {
            Some(product) => Some(Self { raw: product >> FRAC }),
            None => None,
        }
    }

    pub const fn checked_div(self, rhs: Self) -> Option<Self> {
        if rhs.raw == 0 {
            return None;
        }
        let shifted = self.raw << FRAC;
        let result = shifted / rhs.raw;
        Some(Self { raw: result })
    }

    pub const fn checked_neg(self) -> Option<Self> {
        match self.raw.checked_neg() {
            Some(r) => Some(Self { raw: r }),
            None => None,
        }
    }

    pub const fn checked_abs(self) -> Option<Self> {
        if self.raw == i64::MIN {
            None
        } else {
            Some(Self { raw: self.raw.abs() })
        }
    }

    // ================================================================
    // Wrapping family: two's-complement wrap on overflow, never panic
    // (except wrapping_div panics on division by zero).
    // ================================================================

    pub const fn wrapping_add(self, rhs: Self) -> Self {
        Self {
            raw: self.raw.wrapping_add(rhs.raw),
        }
    }

    pub const fn wrapping_sub(self, rhs: Self) -> Self {
        Self {
            raw: self.raw.wrapping_sub(rhs.raw),
        }
    }

    pub const fn wrapping_mul(self, rhs: Self) -> Self {
        Self {
            raw: self.raw.wrapping_mul(rhs.raw) >> FRAC,
        }
    }

    pub const fn wrapping_div(self, rhs: Self) -> Self {
        let shifted = (self.raw as u64).wrapping_shl(FRAC) as i64;
        Self {
            raw: shifted.wrapping_div(rhs.raw),
        }
    }

    pub const fn wrapping_neg(self) -> Self {
        Self {
            raw: self.raw.wrapping_neg(),
        }
    }

    pub const fn wrapping_abs(self) -> Self {
        Self {
            raw: self.raw.wrapping_abs(),
        }
    }

    // ================================================================
    // Saturating family: clamp to MIN/MAX on overflow, never panic
    // (except saturating_div panics on division by zero).
    // ================================================================

    pub const fn saturating_add(self, rhs: Self) -> Self {
        Self {
            raw: self.raw.saturating_add(rhs.raw),
        }
    }

    pub const fn saturating_sub(self, rhs: Self) -> Self {
        Self {
            raw: self.raw.saturating_sub(rhs.raw),
        }
    }

    pub const fn saturating_mul(self, rhs: Self) -> Self {
        match self.checked_mul(rhs) {
            Some(v) => v,
            None => Self::ZERO,
        }
    }

    pub const fn saturating_div(self, rhs: Self) -> Self {
        match self.checked_div(rhs) {
            Some(v) => v,
            None => {
                if rhs.raw == 0 {
                    if self.raw >= 0 {
                        Self::MAX
                    } else {
                        Self::MIN
                    }
                } else {
                    Self::ZERO
                }
            }
        }
    }

    pub const fn saturating_neg(self) -> Self {
        Self {
            raw: self.raw.saturating_neg(),
        }
    }

    pub const fn saturating_abs(self) -> Self {
        Self {
            raw: self.raw.saturating_abs(),
        }
    }

    // ================================================================
    // Overflowing family: return (wrapped_result, did_overflow).
    // Panics on division by zero.
    // ================================================================

    pub const fn overflowing_add(self, rhs: Self) -> (Self, bool) {
        let (r, o) = self.raw.overflowing_add(rhs.raw);
        (Self { raw: r }, o)
    }

    pub const fn overflowing_sub(self, rhs: Self) -> (Self, bool) {
        let (r, o) = self.raw.overflowing_sub(rhs.raw);
        (Self { raw: r }, o)
    }

    pub const fn overflowing_mul(self, rhs: Self) -> (Self, bool) {
        let (product, _) = self.raw.overflowing_mul(rhs.raw);
        let result = product >> FRAC;
        (Self { raw: result }, false)
    }

    pub const fn overflowing_div(self, rhs: Self) -> (Self, bool) {
        let shifted = (self.raw as u64).wrapping_shl(FRAC) as i64;
        let (result, o) = shifted.overflowing_div(rhs.raw);
        (Self { raw: result }, o)
    }

    pub const fn overflowing_neg(self) -> (Self, bool) {
        let (r, o) = self.raw.overflowing_neg();
        (Self { raw: r }, o)
    }

    pub const fn overflowing_abs(self) -> (Self, bool) {
        if self.raw == i64::MIN {
            (Self { raw: i64::MIN }, true)
        } else {
            (Self { raw: self.raw.abs() }, false)
        }
    }

    // ================================================================
    // Precision rescaling: convert between different FRAC values
    // ================================================================

    /// Converts this value to a different fractional precision.
    pub fn checked_rescale<const NEW_FRAC: u32>(self) -> Option<FixedPoint<NEW_FRAC>> {
        let shift = FRAC.abs_diff(NEW_FRAC);
        Some(FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift))
    }

    pub fn wrapping_rescale<const NEW_FRAC: u32>(self) -> FixedPoint<NEW_FRAC> {
        let shift = FRAC.abs_diff(NEW_FRAC);
        FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift)
    }

    pub fn saturating_rescale<const NEW_FRAC: u32>(self) -> FixedPoint<NEW_FRAC> {
        let shift = FRAC.abs_diff(NEW_FRAC);
        FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift)
    }

    pub fn overflowing_rescale<const NEW_FRAC: u32>(self) -> (FixedPoint<NEW_FRAC>, bool) {
        let shift = FRAC.abs_diff(NEW_FRAC);
        (FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift), false)
    }

    // ================================================================
    // Fused multiply-add: self * mul + add
    // ================================================================

    pub fn checked_mul_add(self, mul: Self, add: Self) -> Option<Self> {
        let product = self.checked_mul(mul)?;
        product.checked_add(add)
    }

    pub fn wrapping_mul_add(self, mul: Self, add: Self) -> Self {
        self.wrapping_mul(mul).wrapping_add(add)
    }

    pub fn saturating_mul_add(self, mul: Self, add: Self) -> Self {
        self.saturating_mul(mul).saturating_add(add)
    }

    pub fn overflowing_mul_add(self, mul: Self, add: Self) -> (Self, bool) {
        let (product, o1) = self.overflowing_mul(mul);
        let (result, o2) = product.overflowing_add(add);
        (result, o1 || o2)
    }

    // ================================================================
    // Midpoint
    // ================================================================

    /// Returns the arithmetic midpoint of `self` and `other`.
    pub fn midpoint(self, other: Self) -> Self {
        Self { raw: (self.raw + other.raw) / 2 }
    }

    // ================================================================
    // Comparison helpers
    // ================================================================

    pub const fn is_negative(self) -> bool {
        self.raw < 0
    }

    pub const fn is_positive(self) -> bool {
        self.raw > 0
    }

    pub const fn is_zero(self) -> bool {
        self.raw == 0
    }
}

// ================================================================
// Operator overloads
// ================================================================

impl<const FRAC: u32> Add for FixedPoint<FRAC> {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        match self.checked_add(rhs) {
            Some(r) => r,
            None => panic!("FixedPoint addition overflow"),
        }
    }
}

impl<const FRAC: u32> Sub for FixedPoint<FRAC> {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        match self.checked_sub(rhs) {
            Some(r) => r,
            None => panic!("FixedPoint subtraction overflow"),
        }
    }
}

impl<const FRAC: u32> Mul for FixedPoint<FRAC> {
    type Output = Self;
    fn mul(self, rhs: Self) -> Self {
        self.wrapping_mul(rhs)
    }
}

impl<const FRAC: u32> Div for FixedPoint<FRAC> {
    type Output = Self;
    fn div(self, rhs: Self) -> Self {
        self.wrapping_div(rhs)
    }
}

impl<const FRAC: u32> Neg for FixedPoint<FRAC> {
    type Output = Self;
    fn neg(self) -> Self {
        match self.checked_neg() {
            Some(r) => r,
            None => panic!("FixedPoint negation overflow"),
        }
    }
}

// ================================================================
// Ordering
// ================================================================

impl<const FRAC: u32> PartialOrd for FixedPoint<FRAC> {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl<const FRAC: u32> Ord for FixedPoint<FRAC> {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.raw.cmp(&other.raw)
    }
}

// ================================================================
// Display / Debug
// ================================================================

impl<const FRAC: u32> fmt::Display for FixedPoint<FRAC> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if FRAC == 0 {
            return write!(f, "{}", self.raw);
        }
        let negative = self.raw < 0;
        let abs_raw = if self.raw == i64::MIN {
            return write!(f, "-{}.0", (i64::MAX >> FRAC) + 1);
        } else {
            self.raw.unsigned_abs()
        };
        let int_part = abs_raw >> FRAC;
        let frac_mask = (1u64 << FRAC) - 1;
        let frac_raw = abs_raw & frac_mask;

        if negative {
            write!(f, "-")?;
        }
        write!(f, "{}", int_part)?;

        if frac_raw == 0 {
            write!(f, ".0")
        } else {
            write!(f, ".")?;
            let mut remainder = frac_raw as u128;
            let denom = 1u128 << FRAC;
            let mut digits = String::new();
            let max_digits = 20;
            for _ in 0..max_digits {
                remainder *= 10;
                let digit = remainder / denom;
                digits.push((b'0' + digit as u8) as char);
                remainder %= denom;
                if remainder == 0 {
                    break;
                }
            }
            let trimmed = digits.trim_end_matches('0');
            if trimmed.is_empty() {
                write!(f, "0")
            } else {
                write!(f, "{}", trimmed)
            }
        }
    }
}

impl<const FRAC: u32> fmt::Debug for FixedPoint<FRAC> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "FixedPoint<{}>(raw={}, val={})", FRAC, self.raw, self)
    }
}
