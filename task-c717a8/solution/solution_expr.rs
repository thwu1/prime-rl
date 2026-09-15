// Copyright 2024. Licensed under Apache-2.0.

//! Vectorized expression evaluation framework.

use std::cmp::Ordering;
use std::marker::PhantomData;

use anyhow::Result;

use crate::array::{Array, ArrayBuilder, ArrayImpl};
use crate::datatype::DataType;
use crate::scalar::Scalar;
use crate::TypeMismatch;

// Re-import datatype macros into scope
use crate::datatype_match_pattern;
use crate::datatype_scalar;
use crate::int16;
use crate::int32;
use crate::int64;
use crate::float32;
use crate::float64;
use crate::varchar;
use crate::fwchar;

// ---------------------------------------------------------------------------
// Expression trait
// ---------------------------------------------------------------------------

/// A type-erased expression that operates on [`ArrayImpl`] values.
pub trait Expression {
    fn eval_expr(&self, data: &[&ArrayImpl]) -> Result<ArrayImpl>;
}

// ---------------------------------------------------------------------------
// ExpressionFunc
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub enum ExpressionFunc {
    CmpLe,
    CmpGe,
    CmpEq,
    CmpNe,
    StrContains,
}

// ---------------------------------------------------------------------------
// BinaryExpression
// ---------------------------------------------------------------------------

/// Vectorizes a scalar function over two `ArrayImpl` inputs with null propagation.
pub struct BinaryExpression<I1, I2, O, F> {
    func: F,
    _phantom: PhantomData<(I1, I2, O)>,
}

impl<I1: Scalar, I2: Scalar, O: Scalar, F> BinaryExpression<I1, I2, O, F>
where
    F: Fn(I1::RefType<'_>, I2::RefType<'_>) -> O,
    for<'a> &'a I1::ArrayType: TryFrom<&'a ArrayImpl, Error = TypeMismatch>,
    for<'a> &'a I2::ArrayType: TryFrom<&'a ArrayImpl, Error = TypeMismatch>,
    O::ArrayType: Into<ArrayImpl>,
{
    pub fn new(func: F) -> Self {
        Self {
            func,
            _phantom: PhantomData,
        }
    }

    pub fn eval_batch(&self, i1: &ArrayImpl, i2: &ArrayImpl) -> Result<ArrayImpl> {
        let i1: &I1::ArrayType = i1.try_into().map_err(|e: TypeMismatch| anyhow::anyhow!("{}", e))?;
        let i2: &I2::ArrayType = i2.try_into().map_err(|e: TypeMismatch| anyhow::anyhow!("{}", e))?;
        assert_eq!(i1.len(), i2.len(), "array length mismatch");
        let mut builder = <O::ArrayType as Array>::Builder::with_capacity(i1.len());
        for pair in i1.iter().zip(i2.iter()) {
            match pair {
                (Some(v1), Some(v2)) => {
                    let result = (self.func)(v1, v2);
                    builder.push(Some(result.as_scalar_ref()));
                }
                _ => builder.push(None),
            }
        }
        Ok(builder.finish().into())
    }
}

impl<I1: Scalar, I2: Scalar, O: Scalar, F> Expression for BinaryExpression<I1, I2, O, F>
where
    F: Fn(I1::RefType<'_>, I2::RefType<'_>) -> O,
    for<'a> &'a I1::ArrayType: TryFrom<&'a ArrayImpl, Error = TypeMismatch>,
    for<'a> &'a I2::ArrayType: TryFrom<&'a ArrayImpl, Error = TypeMismatch>,
    O::ArrayType: Into<ArrayImpl>,
{
    fn eval_expr(&self, data: &[&ArrayImpl]) -> Result<ArrayImpl> {
        if data.len() != 2 {
            return Err(anyhow::anyhow!(
                "BinaryExpression expects 2 inputs, got {}",
                data.len()
            ));
        }
        self.eval_batch(data[0], data[1])
    }
}

// ---------------------------------------------------------------------------
// Comparison functions with cross-type casting
// ---------------------------------------------------------------------------

/// Return `i1 < i2`, casting both to common type `C` via `Into`.
pub fn cmp_le<I1: Scalar, I2: Scalar, C: Scalar>(
    i1: I1::RefType<'_>,
    i2: I2::RefType<'_>,
) -> bool
where
    for<'a> I1::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> I2::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> C::RefType<'a>: PartialOrd,
{
    let i1 = I1::upcast_gat(i1);
    let i2 = I2::upcast_gat(i2);
    i1.into().partial_cmp(&i2.into()).unwrap() == Ordering::Less
}

/// Return `i1 > i2`, casting both to common type `C` via `Into`.
pub fn cmp_ge<I1: Scalar, I2: Scalar, C: Scalar>(
    i1: I1::RefType<'_>,
    i2: I2::RefType<'_>,
) -> bool
where
    for<'a> I1::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> I2::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> C::RefType<'a>: PartialOrd,
{
    let i1 = I1::upcast_gat(i1);
    let i2 = I2::upcast_gat(i2);
    i1.into().partial_cmp(&i2.into()).unwrap() == Ordering::Greater
}

/// Return `i1 == i2`, casting both to common type `C` via `Into`.
pub fn cmp_eq<I1: Scalar, I2: Scalar, C: Scalar>(
    i1: I1::RefType<'_>,
    i2: I2::RefType<'_>,
) -> bool
where
    for<'a> I1::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> I2::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> C::RefType<'a>: PartialEq,
{
    let i1 = I1::upcast_gat(i1);
    let i2 = I2::upcast_gat(i2);
    i1.into().eq(&i2.into())
}

/// Return `i1 != i2`, casting both to common type `C` via `Into`.
pub fn cmp_ne<I1: Scalar, I2: Scalar, C: Scalar>(
    i1: I1::RefType<'_>,
    i2: I2::RefType<'_>,
) -> bool
where
    for<'a> I1::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> I2::RefType<'a>: Into<C::RefType<'a>>,
    for<'a> C::RefType<'a>: PartialEq,
{
    let i1 = I1::upcast_gat(i1);
    let i2 = I2::upcast_gat(i2);
    !i1.into().eq(&i2.into())
}

// ---------------------------------------------------------------------------
// String function
// ---------------------------------------------------------------------------

pub fn str_contains(i1: &str, i2: &str) -> bool {
    i1.contains(i2)
}

// ---------------------------------------------------------------------------
// Dispatch macros
// ---------------------------------------------------------------------------

/// Enumerates all valid cross-type comparison combinations.
///
/// Each triple `{ left, right, cast }` specifies:
///   - left: datatype macro for the left input
///   - right: datatype macro for the right input
///   - cast: datatype macro for the common type to cast both inputs to
macro_rules! for_all_cmp_combinations {
    ($macro:ident $(, $x:ident)*) => {
        $macro! {
            [$($x),*],
            // Same-type comparisons
            { int16, int16, int16 },
            { int32, int32, int32 },
            { int64, int64, int64 },
            { float32, float32, float32 },
            { float64, float64, float64 },
            // Cross-integer comparisons
            { int16, int32, int32 },
            { int32, int16, int32 },
            { int16, int64, int64 },
            { int64, int16, int64 },
            { int32, int64, int64 },
            { int64, int32, int64 },
            // Cross-float comparisons
            { float32, float64, float64 },
            { float64, float32, float64 },
            // Integer-float comparisons (lossless conversions only)
            { int16, float32, float32 },
            { float32, int16, float32 },
            { int16, float64, float64 },
            { float64, int16, float64 },
            { int32, float64, float64 },
            { float64, int32, float64 },
            { int32, float32, float64 },
            { float32, int32, float64 },
            // String comparisons
            { varchar, varchar, varchar },
            { fwchar, fwchar, fwchar },
            { varchar, fwchar, varchar },
            { fwchar, varchar, varchar }
        }
    };
}

/// Generates match arms for `build_binary_expression`.
///
/// Uses nested macro invocation: `$i1! { datatype_match_pattern }` expands
/// the association macro with the extraction macro to produce the match pattern.
macro_rules! impl_cmp_expression_of {
    ([$i1t:ident, $i2t:ident, $cmp_func:ident], $({ $i1:ident, $i2:ident, $convert:ident }),*) => {
        match ($i1t, $i2t) {
            $(
                ($i1! { datatype_match_pattern }, $i2! { datatype_match_pattern }) => {
                    Box::new(BinaryExpression::<
                        $i1! { datatype_scalar },
                        $i2! { datatype_scalar },
                        bool,
                        _
                    >::new(
                        $cmp_func::<
                            $i1! { datatype_scalar },
                            $i2! { datatype_scalar },
                            $convert! { datatype_scalar }
                        >,
                    ))
                }
            )*
            (other_dt1, other_dt2) => unimplemented!(
                "unsupported comparison: {:?} <{}> {:?}",
                other_dt1,
                stringify!($cmp_func),
                other_dt2
            )
        }
    };
}

// ---------------------------------------------------------------------------
// build_binary_expression
// ---------------------------------------------------------------------------

/// Build a type-erased expression from runtime type information.
pub fn build_binary_expression(
    f: ExpressionFunc,
    i1: DataType,
    i2: DataType,
) -> Box<dyn Expression> {
    match f {
        ExpressionFunc::CmpLe => {
            for_all_cmp_combinations! { impl_cmp_expression_of, i1, i2, cmp_le }
        }
        ExpressionFunc::CmpGe => {
            for_all_cmp_combinations! { impl_cmp_expression_of, i1, i2, cmp_ge }
        }
        ExpressionFunc::CmpEq => {
            for_all_cmp_combinations! { impl_cmp_expression_of, i1, i2, cmp_eq }
        }
        ExpressionFunc::CmpNe => {
            for_all_cmp_combinations! { impl_cmp_expression_of, i1, i2, cmp_ne }
        }
        ExpressionFunc::StrContains => Box::new(
            BinaryExpression::<String, String, bool, _>::new(str_contains),
        ),
    }
}
