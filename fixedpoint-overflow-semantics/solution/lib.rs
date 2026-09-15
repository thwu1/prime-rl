
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
        if !val.is_finite() {
            return None;
        }
        let scale = (1u64 << FRAC) as f64;
        let scaled = val * scale;
        if scaled >= 9223372036854775808.0_f64 || scaled < -9223372036854775808.0_f64 {
            return None;
        }
        Some(Self { raw: scaled as i64 })
    }

    /// Creates a `FixedPoint` representing `numer / denom`.
    /// Returns `None` if `denom` is zero or the result overflows.
    pub fn from_ratio(numer: i64, denom: i64) -> Option<Self> {
        if denom == 0 {
            return None;
        }
        let wide = (numer as i128) << FRAC;
        let result = wide / (denom as i128);
        if result > i64::MAX as i128 || result < i64::MIN as i128 {
            None
        } else {
            Some(Self { raw: result as i64 })
        }
    }

    /// Converts to `f64` (may lose precision for large values).
    pub fn to_f64(self) -> f64 {
        let scale = (1u64 << FRAC) as f64;
        self.raw as f64 / scale
    }

    // ================================================================
    // Checked family
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
        let wide = (self.raw as i128) * (rhs.raw as i128);
        let result = wide >> FRAC;
        if result > i64::MAX as i128 || result < i64::MIN as i128 {
            None
        } else {
            Some(Self { raw: result as i64 })
        }
    }

    pub const fn checked_div(self, rhs: Self) -> Option<Self> {
        if rhs.raw == 0 {
            return None;
        }
        let wide = (self.raw as i128) << FRAC;
        let result = wide / (rhs.raw as i128);
        if result > i64::MAX as i128 || result < i64::MIN as i128 {
            None
        } else {
            Some(Self { raw: result as i64 })
        }
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
    // Wrapping family
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
        let wide = (self.raw as i128) * (rhs.raw as i128);
        let result = wide >> FRAC;
        Self {
            raw: result as i64,
        }
    }

    pub const fn wrapping_div(self, rhs: Self) -> Self {
        if rhs.raw == 0 {
            panic!("division by zero");
        }
        let wide = (self.raw as i128) << FRAC;
        let result = wide / (rhs.raw as i128);
        Self {
            raw: result as i64,
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
    // Saturating family
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
        let wide = (self.raw as i128) * (rhs.raw as i128);
        let result = wide >> FRAC;
        if result > i64::MAX as i128 {
            Self::MAX
        } else if result < i64::MIN as i128 {
            Self::MIN
        } else {
            Self {
                raw: result as i64,
            }
        }
    }

    pub const fn saturating_div(self, rhs: Self) -> Self {
        if rhs.raw == 0 {
            panic!("division by zero");
        }
        let wide = (self.raw as i128) << FRAC;
        let result = wide / (rhs.raw as i128);
        if result > i64::MAX as i128 {
            Self::MAX
        } else if result < i64::MIN as i128 {
            Self::MIN
        } else {
            Self {
                raw: result as i64,
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
    // Overflowing family
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
        let wide = (self.raw as i128) * (rhs.raw as i128);
        let result = wide >> FRAC;
        let overflowed = result > i64::MAX as i128 || result < i64::MIN as i128;
        (Self { raw: result as i64 }, overflowed)
    }

    pub const fn overflowing_div(self, rhs: Self) -> (Self, bool) {
        if rhs.raw == 0 {
            panic!("division by zero");
        }
        let wide = (self.raw as i128) << FRAC;
        let result = wide / (rhs.raw as i128);
        let overflowed = result > i64::MAX as i128 || result < i64::MIN as i128;
        (Self { raw: result as i64 }, overflowed)
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

    pub fn checked_rescale<const NEW_FRAC: u32>(self) -> Option<FixedPoint<NEW_FRAC>> {
        if NEW_FRAC == FRAC {
            return Some(FixedPoint::<NEW_FRAC>::from_raw(self.raw));
        }
        if NEW_FRAC > FRAC {
            let shift = NEW_FRAC - FRAC;
            let wide = (self.raw as i128) << shift;
            if wide > i64::MAX as i128 || wide < i64::MIN as i128 {
                None
            } else {
                Some(FixedPoint::<NEW_FRAC>::from_raw(wide as i64))
            }
        } else {
            let shift = FRAC - NEW_FRAC;
            Some(FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift))
        }
    }

    pub fn wrapping_rescale<const NEW_FRAC: u32>(self) -> FixedPoint<NEW_FRAC> {
        if NEW_FRAC == FRAC {
            FixedPoint::<NEW_FRAC>::from_raw(self.raw)
        } else if NEW_FRAC > FRAC {
            let shift = NEW_FRAC - FRAC;
            let wide = (self.raw as i128) << shift;
            FixedPoint::<NEW_FRAC>::from_raw(wide as i64)
        } else {
            let shift = FRAC - NEW_FRAC;
            FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift)
        }
    }

    pub fn saturating_rescale<const NEW_FRAC: u32>(self) -> FixedPoint<NEW_FRAC> {
        if NEW_FRAC == FRAC {
            FixedPoint::<NEW_FRAC>::from_raw(self.raw)
        } else if NEW_FRAC > FRAC {
            let shift = NEW_FRAC - FRAC;
            let wide = (self.raw as i128) << shift;
            if wide > i64::MAX as i128 {
                FixedPoint::<NEW_FRAC>::MAX
            } else if wide < i64::MIN as i128 {
                FixedPoint::<NEW_FRAC>::MIN
            } else {
                FixedPoint::<NEW_FRAC>::from_raw(wide as i64)
            }
        } else {
            let shift = FRAC - NEW_FRAC;
            FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift)
        }
    }

    pub fn overflowing_rescale<const NEW_FRAC: u32>(self) -> (FixedPoint<NEW_FRAC>, bool) {
        if NEW_FRAC == FRAC {
            (FixedPoint::<NEW_FRAC>::from_raw(self.raw), false)
        } else if NEW_FRAC > FRAC {
            let shift = NEW_FRAC - FRAC;
            let wide = (self.raw as i128) << shift;
            let overflowed = wide > i64::MAX as i128 || wide < i64::MIN as i128;
            (FixedPoint::<NEW_FRAC>::from_raw(wide as i64), overflowed)
        } else {
            let shift = FRAC - NEW_FRAC;
            (FixedPoint::<NEW_FRAC>::from_raw(self.raw >> shift), false)
        }
    }

    // ================================================================
    // Fused multiply-add: self * mul + add
    // ================================================================

    pub fn checked_mul_add(self, mul: Self, add: Self) -> Option<Self> {
        let wide_product = (self.raw as i128) * (mul.raw as i128);
        let shifted = wide_product >> FRAC;
        let wide_sum = shifted + (add.raw as i128);
        if wide_sum > i64::MAX as i128 || wide_sum < i64::MIN as i128 {
            None
        } else {
            Some(Self::from_raw(wide_sum as i64))
        }
    }

    pub fn wrapping_mul_add(self, mul: Self, add: Self) -> Self {
        let wide_product = (self.raw as i128) * (mul.raw as i128);
        let shifted = wide_product >> FRAC;
        let wide_sum = shifted + (add.raw as i128);
        Self::from_raw(wide_sum as i64)
    }

    pub fn saturating_mul_add(self, mul: Self, add: Self) -> Self {
        let wide_product = (self.raw as i128) * (mul.raw as i128);
        let shifted = wide_product >> FRAC;
        let wide_sum = shifted + (add.raw as i128);
        if wide_sum > i64::MAX as i128 {
            Self::MAX
        } else if wide_sum < i64::MIN as i128 {
            Self::MIN
        } else {
            Self::from_raw(wide_sum as i64)
        }
    }

    pub fn overflowing_mul_add(self, mul: Self, add: Self) -> (Self, bool) {
        let wide_product = (self.raw as i128) * (mul.raw as i128);
        let shifted = wide_product >> FRAC;
        let wide_sum = shifted + (add.raw as i128);
        let overflowed = wide_sum > i64::MAX as i128 || wide_sum < i64::MIN as i128;
        (Self::from_raw(wide_sum as i64), overflowed)
    }

    // ================================================================
    // Midpoint
    // ================================================================

    /// Returns the arithmetic midpoint of `self` and `other`.
    pub fn midpoint(self, other: Self) -> Self {
        let wide_sum = (self.raw as i128) + (other.raw as i128);
        Self { raw: (wide_sum / 2) as i64 }
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
        match self.checked_mul(rhs) {
            Some(r) => r,
            None => panic!("FixedPoint multiplication overflow"),
        }
    }
}

impl<const FRAC: u32> Div for FixedPoint<FRAC> {
    type Output = Self;
    fn div(self, rhs: Self) -> Self {
        match self.checked_div(rhs) {
            Some(r) => r,
            None => panic!("FixedPoint division overflow or division by zero"),
        }
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
