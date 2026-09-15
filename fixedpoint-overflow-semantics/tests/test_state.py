
"""
Verification tests for the FixedPoint<FRAC> library.

Generates a Rust integration test at /app/tests/verify.rs, builds and runs it
via cargo, then checks each individual Rust test for pass/fail.
"""

import os
import re
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Rust integration test source — written to /app/tests/verify.rs at test time
# ---------------------------------------------------------------------------

VERIFY_RS = r'''

use fixedpoint::FixedPoint;

type Q16 = FixedPoint<16>;
type Q8 = FixedPoint<8>;
type Q32 = FixedPoint<32>;

const ONE_16: i64 = 1 << 16;

// ==================== Basic construction ====================

#[test]
fn test_from_raw_roundtrip() {
    assert_eq!(Q16::from_raw(12345).to_raw(), 12345);
    assert_eq!(Q16::from_raw(-99999).to_raw(), -99999);
    assert_eq!(Q16::from_raw(0).to_raw(), 0);
    assert_eq!(Q16::from_raw(i64::MAX).to_raw(), i64::MAX);
    assert_eq!(Q16::from_raw(i64::MIN).to_raw(), i64::MIN);
}

#[test]
fn test_from_int() {
    let x = Q16::from_int(42).unwrap();
    assert_eq!(x.to_raw(), 42 * ONE_16);
    assert_eq!(Q16::from_int(0).unwrap().to_raw(), 0);
    assert_eq!(Q16::from_int(-1).unwrap().to_raw(), -ONE_16);
}

#[test]
fn test_from_f64_valid() {
    let x = Q16::from_f64(1.5).unwrap();
    assert_eq!(x.to_raw(), ONE_16 + ONE_16 / 2);
    let y = Q16::from_f64(-2.25).unwrap();
    assert_eq!(y.to_raw(), -2 * ONE_16 - ONE_16 / 4);
    assert_eq!(Q16::from_f64(0.0).unwrap().to_raw(), 0);
}

#[test]
fn test_from_f64_nan() {
    assert!(Q16::from_f64(f64::NAN).is_none(), "from_f64(NaN) must return None");
}

#[test]
fn test_from_f64_inf() {
    assert!(Q16::from_f64(f64::INFINITY).is_none(), "from_f64(+inf) must return None");
    assert!(Q16::from_f64(f64::NEG_INFINITY).is_none(), "from_f64(-inf) must return None");
}

#[test]
fn test_from_f64_out_of_range() {
    assert!(Q16::from_f64(1e30).is_none(), "from_f64(1e30) must return None");
    assert!(Q16::from_f64(-1e30).is_none(), "from_f64(-1e30) must return None");
}

// ==================== from_ratio ====================

#[test]
fn test_from_ratio_basic() {
    // 3/4 = 0.75 -> raw = 0.75 * 2^16 = 49152
    let r = Q16::from_ratio(3, 4).unwrap();
    assert_eq!(r.to_raw(), 3 * ONE_16 / 4);
}

#[test]
fn test_from_ratio_integer() {
    // 6/2 = 3.0
    let r = Q16::from_ratio(6, 2).unwrap();
    assert_eq!(r.to_raw(), 3 * ONE_16);
}

#[test]
fn test_from_ratio_negative() {
    // -5/2 = -2.5
    let r = Q16::from_ratio(-5, 2).unwrap();
    assert_eq!(r.to_raw(), -5 * ONE_16 / 2);
}

#[test]
fn test_from_ratio_zero_denom() {
    assert!(Q16::from_ratio(1, 0).is_none(), "from_ratio(1, 0) must return None");
}

#[test]
fn test_from_ratio_zero_numer() {
    assert_eq!(Q16::from_ratio(0, 42).unwrap().to_raw(), 0);
}

#[test]
fn test_from_ratio_large_numer() {
    // Large numerator that requires widened intermediate.
    // numer=2^46, denom=1: result = 2^46 * 2^16 / 1 = 2^62, fits i64.
    let r = Q16::from_ratio(1i64 << 46, 1);
    assert!(r.is_some(), "from_ratio with large numer that fits must succeed");
    assert_eq!(r.unwrap().to_raw(), 1i64 << 62);
}

#[test]
fn test_from_ratio_overflow() {
    // numer=2^47, denom=1: result = 2^47 * 2^16 = 2^63 which is i64::MAX+1 -> None
    assert!(Q16::from_ratio(1i64 << 47, 1).is_none(), "from_ratio overflow must return None");
}

#[test]
fn test_from_ratio_neg_denom() {
    // 6 / -3 = -2.0
    let r = Q16::from_ratio(6, -3).unwrap();
    assert_eq!(r.to_raw(), -2 * ONE_16);
}

// ==================== Checked add / sub ====================

#[test]
fn test_checked_add_basic() {
    let a = Q16::from_int(100).unwrap();
    let b = Q16::from_int(200).unwrap();
    assert_eq!(a.checked_add(b).unwrap().to_raw(), 300 * ONE_16);
}

#[test]
fn test_checked_add_overflow() {
    assert!(Q16::MAX.checked_add(Q16::from_raw(1)).is_none());
}

#[test]
fn test_checked_sub_basic() {
    let a = Q16::from_int(100).unwrap();
    let b = Q16::from_int(200).unwrap();
    assert_eq!(a.checked_sub(b).unwrap().to_raw(), -100 * ONE_16);
}

// ==================== Checked mul ====================

#[test]
fn test_checked_mul_one() {
    let one = Q16::from_raw(ONE_16);
    assert_eq!(one.checked_mul(one).unwrap().to_raw(), ONE_16);
}

#[test]
fn test_checked_mul_small() {
    // 3.0 * 4.0 = 12.0
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    assert_eq!(a.checked_mul(b).unwrap().to_raw(), 12 * ONE_16);
}

#[test]
fn test_checked_mul_widening_needed() {
    // (2^32 raw) * (2^32 raw): intermediate product is 2^64 which overflows
    // i64, but the fixed-point result (2^64 >> 16 = 2^48) fits in i64.
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(1i64 << 32);
    let r = a.checked_mul(b);
    assert!(r.is_some(), "checked_mul incorrectly reports overflow; needs wider intermediate");
    assert_eq!(r.unwrap().to_raw(), 1i64 << 48);
}

#[test]
fn test_checked_mul_negative_widening() {
    // (-2^32 raw) * (-2^32 raw) should also work via widening.
    let a = Q16::from_raw(-(1i64 << 32));
    let b = Q16::from_raw(-(1i64 << 32));
    let r = a.checked_mul(b);
    assert!(r.is_some(), "negative widening multiplication failed");
    assert_eq!(r.unwrap().to_raw(), 1i64 << 48);
}

#[test]
fn test_checked_mul_mixed_sign_widening() {
    // positive * negative: needs widening but result is negative and fits.
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(-(1i64 << 32));
    let r = a.checked_mul(b);
    assert!(r.is_some());
    assert_eq!(r.unwrap().to_raw(), -(1i64 << 48));
}

#[test]
fn test_checked_mul_actual_overflow() {
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    assert!(a.checked_mul(b).is_none());
}

// ==================== Checked div ====================

#[test]
fn test_checked_div_basic() {
    let a = Q16::from_int(6).unwrap();
    let b = Q16::from_int(2).unwrap();
    assert_eq!(a.checked_div(b).unwrap().to_raw(), 3 * ONE_16);
}

#[test]
fn test_checked_div_fractional() {
    // 1.0 / 4.0 = 0.25
    let a = Q16::from_raw(ONE_16);
    let b = Q16::from_raw(4 * ONE_16);
    let r = a.checked_div(b).unwrap();
    assert_eq!(r.to_raw(), ONE_16 / 4);
}

#[test]
fn test_checked_div_widening_needed() {
    // Large dividend / 1.0: the intermediate (raw << FRAC) overflows i64.
    let a = Q16::from_raw(1i64 << 48);
    let b = Q16::from_raw(ONE_16);
    let r = a.checked_div(b);
    assert!(r.is_some(), "checked_div fails for large dividends; needs wider intermediate");
    assert_eq!(r.unwrap().to_raw(), 1i64 << 48);
}

#[test]
fn test_checked_div_by_zero() {
    assert!(Q16::from_raw(ONE_16).checked_div(Q16::ZERO).is_none());
}

#[test]
fn test_checked_div_min_by_neg_one() {
    // MIN / -1.0 should overflow (result = -MIN > MAX).
    let a = Q16::MIN;
    let b = Q16::from_raw(-ONE_16);
    assert!(a.checked_div(b).is_none());
}

// ==================== Wrapping mul / div ====================

#[test]
fn test_wrapping_mul_widening() {
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(1i64 << 32);
    let r = a.wrapping_mul(b);
    assert_eq!(r.to_raw(), 1i64 << 48);
}

#[test]
fn test_wrapping_mul_basic() {
    let a = Q16::from_int(5).unwrap();
    let b = Q16::from_int(7).unwrap();
    assert_eq!(a.wrapping_mul(b).to_raw(), 35 * ONE_16);
}

#[test]
fn test_wrapping_div_widening() {
    let a = Q16::from_raw(1i64 << 48);
    let b = Q16::from_raw(ONE_16);
    let r = a.wrapping_div(b);
    assert_eq!(r.to_raw(), 1i64 << 48);
}

#[test]
fn test_wrapping_div_basic() {
    let a = Q16::from_int(10).unwrap();
    let b = Q16::from_int(5).unwrap();
    assert_eq!(a.wrapping_div(b).to_raw(), 2 * ONE_16);
}

#[test]
fn test_wrapping_div_min_neg_one() {
    // MIN / -1.0: overflows, wrapping result is MIN.
    let a = Q16::MIN;
    let b = Q16::from_raw(-ONE_16);
    let r = a.wrapping_div(b);
    assert_eq!(r, Q16::MIN);
}

// ==================== Saturating mul / div ====================

#[test]
fn test_saturating_mul_no_overflow() {
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    assert_eq!(a.saturating_mul(b).to_raw(), 12 * ONE_16);
}

#[test]
fn test_saturating_mul_overflow_positive() {
    // Two large same-sign values: saturate to MAX.
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    assert_eq!(a.saturating_mul(b), Q16::MAX);
}

#[test]
fn test_saturating_mul_overflow_negative() {
    // Large positive * negative: saturate to MIN.
    let a = Q16::MAX;
    let b = Q16::from_raw(-2 * ONE_16);
    assert_eq!(a.saturating_mul(b), Q16::MIN);
}

#[test]
fn test_saturating_div_overflow() {
    // MIN / -1.0 overflows: saturate to MAX.
    let a = Q16::MIN;
    let b = Q16::from_raw(-ONE_16);
    assert_eq!(a.saturating_div(b), Q16::MAX);
}

#[test]
#[should_panic]
fn test_saturating_div_by_zero_panics() {
    let _ = Q16::from_raw(ONE_16).saturating_div(Q16::ZERO);
}

// ==================== Overflowing mul / div ====================

#[test]
fn test_overflowing_mul_no_overflow() {
    let a = Q16::from_raw(ONE_16);
    let b = Q16::from_raw(ONE_16);
    let (r, o) = a.overflowing_mul(b);
    assert_eq!(r.to_raw(), ONE_16);
    assert!(!o, "1.0 * 1.0 should not overflow");
}

#[test]
fn test_overflowing_mul_overflow_flag() {
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    let (_, o) = a.overflowing_mul(b);
    assert!(o, "MAX * 2.0 must set overflow flag");
}

#[test]
fn test_overflowing_mul_widening_no_overflow() {
    // Needs wider intermediate but result fits i64: overflow flag must be false.
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(1i64 << 32);
    let (r, o) = a.overflowing_mul(b);
    assert_eq!(r.to_raw(), 1i64 << 48);
    assert!(!o, "widening multiplication that fits should NOT report overflow");
}

#[test]
fn test_overflowing_div_no_overflow() {
    let a = Q16::from_int(6).unwrap();
    let b = Q16::from_int(2).unwrap();
    let (r, o) = a.overflowing_div(b);
    assert_eq!(r.to_raw(), 3 * ONE_16);
    assert!(!o);
}

#[test]
fn test_overflowing_div_widening() {
    let a = Q16::from_raw(1i64 << 48);
    let b = Q16::from_raw(ONE_16);
    let (r, o) = a.overflowing_div(b);
    assert_eq!(r.to_raw(), 1i64 << 48);
    assert!(!o);
}

#[test]
fn test_overflowing_div_min_neg_one() {
    // MIN / -1.0: result overflows.
    let a = Q16::MIN;
    let b = Q16::from_raw(-ONE_16);
    let (r, o) = a.overflowing_div(b);
    assert!(o, "MIN / -1.0 must report overflow");
    assert_eq!(r, Q16::MIN);
}

// ==================== Operator overloads ====================

#[test]
fn test_add_operator() {
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    assert_eq!((a + b).to_raw(), 7 * ONE_16);
}

#[test]
fn test_sub_operator() {
    let a = Q16::from_int(10).unwrap();
    let b = Q16::from_int(3).unwrap();
    assert_eq!((a - b).to_raw(), 7 * ONE_16);
}

#[test]
fn test_mul_operator_correct_result() {
    // Must produce correct result (needs wider intermediate internally).
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(1i64 << 32);
    let r = a * b;
    assert_eq!(r.to_raw(), 1i64 << 48);
}

#[test]
fn test_mul_operator_panics_on_overflow() {
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    let result = std::panic::catch_unwind(|| {
        let _ = a * b;
    });
    assert!(result.is_err(), "* operator must panic on overflow");
}

#[test]
fn test_div_operator_correct_result() {
    let a = Q16::from_int(6).unwrap();
    let b = Q16::from_int(2).unwrap();
    let r = a / b;
    assert_eq!(r.to_raw(), 3 * ONE_16);
}

#[test]
fn test_div_operator_panics_on_zero() {
    let a = Q16::from_raw(ONE_16);
    let b = Q16::ZERO;
    let result = std::panic::catch_unwind(|| {
        let _ = a / b;
    });
    assert!(result.is_err(), "/ operator must panic on division by zero");
}

// ==================== Neg / Abs edge cases ====================

#[test]
fn test_neg_min() {
    assert!(Q16::MIN.checked_neg().is_none());
    assert_eq!(Q16::MIN.wrapping_neg(), Q16::MIN);
    assert_eq!(Q16::MIN.saturating_neg(), Q16::MAX);
    let (r, o) = Q16::MIN.overflowing_neg();
    assert_eq!(r, Q16::MIN);
    assert!(o);
}

#[test]
fn test_abs_min() {
    assert!(Q16::MIN.checked_abs().is_none());
    assert_eq!(Q16::MIN.wrapping_abs(), Q16::MIN);
    assert_eq!(Q16::MIN.saturating_abs(), Q16::MAX);
    let (r, o) = Q16::MIN.overflowing_abs();
    assert_eq!(r, Q16::MIN);
    assert!(o);
}

// ==================== Cross-FRAC genericity ====================

#[test]
fn test_q8_checked_mul_widening() {
    // (2^32 * 2^32) >> 8 = 2^64 >> 8 = 2^56, fits i64.
    let a = Q8::from_raw(1i64 << 32);
    let b = Q8::from_raw(1i64 << 32);
    let r = a.checked_mul(b);
    assert!(r.is_some());
    assert_eq!(r.unwrap().to_raw(), 1i64 << 56);
}

#[test]
fn test_q32_checked_mul() {
    let one_q32: i64 = 1i64 << 32;
    let a = Q32::from_raw(one_q32); // 1.0
    let b = Q32::from_raw(one_q32); // 1.0
    let r = a.checked_mul(b).unwrap();
    assert_eq!(r.to_raw(), one_q32); // 1.0 * 1.0 = 1.0
}

#[test]
fn test_q32_checked_div() {
    let one_q32: i64 = 1i64 << 32;
    let a = Q32::from_raw(6 * one_q32); // 6.0
    let b = Q32::from_raw(2 * one_q32); // 2.0
    let r = a.checked_div(b).unwrap();
    assert_eq!(r.to_raw(), 3 * one_q32); // 3.0
}

// ==================== Precision rescaling ====================

#[test]
fn test_checked_rescale_widen_q8_to_q16() {
    // Q8 raw=42 (value 42/256) -> Q16: must left-shift by 8 -> raw=42*256=10752
    let a = Q8::from_raw(42);
    let b: Option<Q16> = a.checked_rescale::<16>();
    assert!(b.is_some(), "widening rescale from Q8 to Q16 should succeed");
    assert_eq!(b.unwrap().to_raw(), 42 * 256);
}

#[test]
fn test_checked_rescale_narrow_q16_to_q8() {
    // Q16 raw=10752 -> Q8: must right-shift by 8 -> raw=42
    let a = Q16::from_raw(10752);
    let b: Option<Q8> = a.checked_rescale::<8>();
    assert!(b.is_some());
    assert_eq!(b.unwrap().to_raw(), 42);
}

#[test]
fn test_checked_rescale_widen_overflow() {
    // Q8 raw=2^56 -> Q32: left-shift by 24 -> 2^80, overflows i64
    let a = Q8::from_raw(1i64 << 56);
    let b: Option<Q32> = a.checked_rescale::<32>();
    assert!(b.is_none(), "widening rescale that overflows must return None");
}

#[test]
fn test_checked_rescale_identity() {
    let a = Q16::from_raw(12345);
    let b: Option<Q16> = a.checked_rescale::<16>();
    assert_eq!(b.unwrap().to_raw(), 12345);
}

#[test]
fn test_checked_rescale_negative_widen() {
    // Q8 raw=-42 -> Q16: left-shift by 8 -> raw=-10752
    let a = Q8::from_raw(-42);
    let b: Option<Q16> = a.checked_rescale::<16>();
    assert!(b.is_some());
    assert_eq!(b.unwrap().to_raw(), -10752);
}

#[test]
fn test_saturating_rescale_widen_positive() {
    let a = Q8::from_raw(1i64 << 56);
    let b: Q32 = a.saturating_rescale::<32>();
    assert_eq!(b, Q32::MAX, "positive overflow should saturate to MAX");
}

#[test]
fn test_saturating_rescale_widen_negative() {
    let a = Q8::from_raw(-(1i64 << 56));
    let b: Q32 = a.saturating_rescale::<32>();
    assert_eq!(b, Q32::MIN, "negative overflow should saturate to MIN");
}

#[test]
fn test_overflowing_rescale_overflow_flag() {
    let a = Q8::from_raw(1i64 << 56);
    let (_, o): (Q32, bool) = a.overflowing_rescale::<32>();
    assert!(o, "overflowing rescale must set flag on overflow");
}

#[test]
fn test_overflowing_rescale_no_overflow() {
    let a = Q8::from_raw(42);
    let (r, o): (Q16, bool) = a.overflowing_rescale::<16>();
    assert_eq!(r.to_raw(), 10752);
    assert!(!o);
}

#[test]
fn test_wrapping_rescale_widen() {
    let a = Q8::from_raw(42);
    let r: Q16 = a.wrapping_rescale::<16>();
    assert_eq!(r.to_raw(), 10752);
}

// ==================== Fused multiply-add ====================

#[test]
fn test_checked_mul_add_basic() {
    // 3.0 * 4.0 + 5.0 = 17.0
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    let c = Q16::from_int(5).unwrap();
    let r = a.checked_mul_add(b, c).unwrap();
    assert_eq!(r.to_raw(), 17 * ONE_16);
}

#[test]
fn test_checked_mul_add_fused_advantage() {
    // self * mul overflows i64 standalone, but self * mul + add fits.
    // (2^62 * 2^17) >> 16 = 2^63 which is i64::MAX+1 (standalone overflow).
    // But (2^63) + (-1) = i64::MAX which fits.
    let a = Q16::from_raw(1i64 << 62);
    let b = Q16::from_raw(2 * ONE_16); // 2.0
    let c = Q16::from_raw(-1);
    assert!(a.checked_mul(b).is_none(), "standalone mul must overflow");
    let r = a.checked_mul_add(b, c);
    assert!(r.is_some(), "fused mul_add must succeed when final result fits");
    assert_eq!(r.unwrap().to_raw(), i64::MAX);
}

#[test]
fn test_checked_mul_add_overflow() {
    // Even fused, the result overflows: MAX * 2.0 + MAX
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    let c = Q16::MAX;
    assert!(a.checked_mul_add(b, c).is_none());
}

#[test]
fn test_saturating_mul_add_no_overflow() {
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    let c = Q16::from_int(5).unwrap();
    assert_eq!(a.saturating_mul_add(b, c).to_raw(), 17 * ONE_16);
}

#[test]
fn test_saturating_mul_add_fused_saturation() {
    // MAX * 2.0 + (-ONE): fused result is ~2*MAX - ONE, still overflows -> saturate to MAX.
    // A decomposed approach that saturates the product first gives MAX + (-ONE) = MAX - ONE (wrong).
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    let c = Q16::from_raw(-ONE_16);
    assert_eq!(a.saturating_mul_add(b, c), Q16::MAX);
}

#[test]
fn test_overflowing_mul_add_no_overflow() {
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    let c = Q16::from_int(5).unwrap();
    let (r, o) = a.overflowing_mul_add(b, c);
    assert_eq!(r.to_raw(), 17 * ONE_16);
    assert!(!o);
}

#[test]
fn test_overflowing_mul_add_fused_flag() {
    // Same as checked_mul_add_fused_advantage: final result fits i64,
    // so overflow flag must be false even though standalone mul would overflow.
    let a = Q16::from_raw(1i64 << 62);
    let b = Q16::from_raw(2 * ONE_16);
    let c = Q16::from_raw(-1);
    let (r, o) = a.overflowing_mul_add(b, c);
    assert_eq!(r.to_raw(), i64::MAX);
    assert!(!o, "fused overflowing_mul_add must not report overflow when final result fits");
}

#[test]
fn test_overflowing_mul_add_true_overflow() {
    let a = Q16::MAX;
    let b = Q16::from_raw(2 * ONE_16);
    let c = Q16::MAX;
    let (_, o) = a.overflowing_mul_add(b, c);
    assert!(o, "fused result exceeds i64 range");
}

#[test]
fn test_wrapping_mul_add_basic() {
    let a = Q16::from_int(3).unwrap();
    let b = Q16::from_int(4).unwrap();
    let c = Q16::from_int(5).unwrap();
    assert_eq!(a.wrapping_mul_add(b, c).to_raw(), 17 * ONE_16);
}

#[test]
fn test_wrapping_mul_add_widening() {
    // Requires wider intermediate in the product.
    // (2^32 * 2^32) >> 16 + ONE_16 = 2^48 + ONE_16
    let a = Q16::from_raw(1i64 << 32);
    let b = Q16::from_raw(1i64 << 32);
    let c = Q16::from_raw(ONE_16);
    let r = a.wrapping_mul_add(b, c);
    assert_eq!(r.to_raw(), (1i64 << 48) + ONE_16);
}

// ==================== Midpoint ====================

#[test]
fn test_midpoint_basic() {
    // midpoint(2.0, 4.0) = 3.0
    let a = Q16::from_int(2).unwrap();
    let b = Q16::from_int(4).unwrap();
    assert_eq!(a.midpoint(b).to_raw(), 3 * ONE_16);
}

#[test]
fn test_midpoint_same() {
    let a = Q16::from_int(7).unwrap();
    assert_eq!(a.midpoint(a).to_raw(), 7 * ONE_16);
}

#[test]
fn test_midpoint_negative() {
    // midpoint(-6.0, 2.0) = -2.0
    let a = Q16::from_int(-6).unwrap();
    let b = Q16::from_int(2).unwrap();
    assert_eq!(a.midpoint(b).to_raw(), -2 * ONE_16);
}

#[test]
fn test_midpoint_max_max() {
    // midpoint(MAX, MAX) = MAX, must not overflow.
    assert_eq!(Q16::MAX.midpoint(Q16::MAX), Q16::MAX);
}

#[test]
fn test_midpoint_min_min() {
    // midpoint(MIN, MIN) = MIN, must not overflow.
    assert_eq!(Q16::MIN.midpoint(Q16::MIN), Q16::MIN);
}

#[test]
fn test_midpoint_max_min() {
    // midpoint(MAX, MIN) should be (MAX+MIN)/2 = -1/2 = 0 (truncated toward zero).
    let m = Q16::MAX.midpoint(Q16::MIN);
    assert_eq!(m.to_raw(), ((i64::MAX as i128 + i64::MIN as i128) / 2) as i64);
}

#[test]
fn test_midpoint_near_overflow() {
    // midpoint(MAX, MAX-1) = MAX-1 (truncated) or MAX-0.5 rounds down.
    let a = Q16::MAX;
    let b = Q16::from_raw(i64::MAX - 1);
    let m = a.midpoint(b);
    let expected = ((i64::MAX as i128 + (i64::MAX - 1) as i128) / 2) as i64;
    assert_eq!(m.to_raw(), expected);
}

#[test]
fn test_midpoint_zero() {
    // midpoint(0, 0) = 0
    assert_eq!(Q16::ZERO.midpoint(Q16::ZERO), Q16::ZERO);
}
'''

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

RUST_TESTS = [
    "test_from_raw_roundtrip",
    "test_from_int",
    "test_from_f64_valid",
    "test_from_f64_nan",
    "test_from_f64_inf",
    "test_from_f64_out_of_range",
    # from_ratio
    "test_from_ratio_basic",
    "test_from_ratio_integer",
    "test_from_ratio_negative",
    "test_from_ratio_zero_denom",
    "test_from_ratio_zero_numer",
    "test_from_ratio_large_numer",
    "test_from_ratio_overflow",
    "test_from_ratio_neg_denom",
    # checked add/sub
    "test_checked_add_basic",
    "test_checked_add_overflow",
    "test_checked_sub_basic",
    # checked mul
    "test_checked_mul_one",
    "test_checked_mul_small",
    "test_checked_mul_widening_needed",
    "test_checked_mul_negative_widening",
    "test_checked_mul_mixed_sign_widening",
    "test_checked_mul_actual_overflow",
    # checked div
    "test_checked_div_basic",
    "test_checked_div_fractional",
    "test_checked_div_widening_needed",
    "test_checked_div_by_zero",
    "test_checked_div_min_by_neg_one",
    # wrapping mul/div
    "test_wrapping_mul_widening",
    "test_wrapping_mul_basic",
    "test_wrapping_div_widening",
    "test_wrapping_div_basic",
    "test_wrapping_div_min_neg_one",
    # saturating mul/div
    "test_saturating_mul_no_overflow",
    "test_saturating_mul_overflow_positive",
    "test_saturating_mul_overflow_negative",
    "test_saturating_div_overflow",
    "test_saturating_div_by_zero_panics",
    # overflowing mul/div
    "test_overflowing_mul_no_overflow",
    "test_overflowing_mul_overflow_flag",
    "test_overflowing_mul_widening_no_overflow",
    "test_overflowing_div_no_overflow",
    "test_overflowing_div_widening",
    "test_overflowing_div_min_neg_one",
    # operators
    "test_add_operator",
    "test_sub_operator",
    "test_mul_operator_correct_result",
    "test_mul_operator_panics_on_overflow",
    "test_div_operator_correct_result",
    "test_div_operator_panics_on_zero",
    # neg/abs
    "test_neg_min",
    "test_abs_min",
    # cross-FRAC
    "test_q8_checked_mul_widening",
    "test_q32_checked_mul",
    "test_q32_checked_div",
    # rescale
    "test_checked_rescale_widen_q8_to_q16",
    "test_checked_rescale_narrow_q16_to_q8",
    "test_checked_rescale_widen_overflow",
    "test_checked_rescale_identity",
    "test_checked_rescale_negative_widen",
    "test_saturating_rescale_widen_positive",
    "test_saturating_rescale_widen_negative",
    "test_overflowing_rescale_overflow_flag",
    "test_overflowing_rescale_no_overflow",
    "test_wrapping_rescale_widen",
    # fused multiply-add
    "test_checked_mul_add_basic",
    "test_checked_mul_add_fused_advantage",
    "test_checked_mul_add_overflow",
    "test_saturating_mul_add_no_overflow",
    "test_saturating_mul_add_fused_saturation",
    "test_overflowing_mul_add_no_overflow",
    "test_overflowing_mul_add_fused_flag",
    "test_overflowing_mul_add_true_overflow",
    "test_wrapping_mul_add_basic",
    "test_wrapping_mul_add_widening",
    # midpoint
    "test_midpoint_basic",
    "test_midpoint_same",
    "test_midpoint_negative",
    "test_midpoint_max_max",
    "test_midpoint_min_min",
    "test_midpoint_max_min",
    "test_midpoint_near_overflow",
    "test_midpoint_zero",
]


def _write_test_file():
    os.makedirs("/app/tests", exist_ok=True)
    with open("/app/tests/verify.rs", "w") as f:
        f.write(VERIFY_RS)


def _build():
    result = subprocess.run(
        ["cargo", "test", "--test", "verify", "--no-run"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode == 0, result.stdout + "\n" + result.stderr


def _run_all():
    result = subprocess.run(
        ["cargo", "test", "--test", "verify", "--", "--test-threads=1"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.returncode, result.stdout + "\n" + result.stderr


def _check_passed(output, test_name):
    pattern = rf"test {re.escape(test_name)}.*\.\.\. ok"
    return bool(re.search(pattern, output))


# ---------------------------------------------------------------------------
# Pytest
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cargo_output():
    """Build and run all Rust tests once; share output across pytest tests."""
    _write_test_file()
    ok, build_out = _build()
    if not ok:
        pytest.fail(f"cargo build failed:\n{build_out}")
    rc, test_out = _run_all()
    return test_out


@pytest.mark.parametrize("rust_test", RUST_TESTS)
def test_rust(rust_test, cargo_output):
    assert _check_passed(cargo_output, rust_test), (
        f"Rust test '{rust_test}' did not pass.\n"
        f"Full cargo output:\n{cargo_output}"
    )
