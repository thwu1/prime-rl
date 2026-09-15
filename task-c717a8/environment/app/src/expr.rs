// Copyright 2024. Licensed under Apache-2.0.

//! Vectorized expression evaluation framework.
//!
//! This module must be completed to enable vectorized evaluation of scalar
//! functions over columnar arrays, with support for cross-type comparisons,
//! null propagation, and runtime type dispatch.

use anyhow::Result;

use crate::array::ArrayImpl;
use crate::datatype::DataType;

// ---------------------------------------------------------------------------
// Expression trait (complete — do not modify)
// ---------------------------------------------------------------------------

/// A type-erased expression that operates on [`ArrayImpl`] values.
///
/// Can be made into `Box<dyn Expression>` for runtime dispatch.
pub trait Expression {
    /// Evaluate the expression on the given input arrays.
    fn eval_expr(&self, data: &[&ArrayImpl]) -> Result<ArrayImpl>;
}

// ---------------------------------------------------------------------------
// ExpressionFunc enum (complete — do not modify)
// ---------------------------------------------------------------------------

/// All supported expression functions for binary operations.
#[derive(Debug)]
pub enum ExpressionFunc {
    CmpLe,
    CmpGe,
    CmpEq,
    CmpNe,
    StrContains,
}

// ---------------------------------------------------------------------------
// TODO: Implement BinaryExpression<I1, I2, O, F>
// ---------------------------------------------------------------------------
//
// A struct that vectorizes a scalar function F over two ArrayImpl inputs.
//
// Type parameters:
//   I1, I2: Input scalar types (impl Scalar)
//   O: Output scalar type (impl Scalar)
//   F: The scalar function — Fn(I1::RefType<'_>, I2::RefType<'_>) -> O
//
// Required methods:
//   new(func: F) -> Self
//   eval_batch(&self, i1: &ArrayImpl, i2: &ArrayImpl) -> Result<ArrayImpl>
//
// Must also implement Expression trait for BinaryExpression.
//
// Key challenges:
//   - Correct trait bounds including for<'a> on TryFrom for array extraction
//   - O::ArrayType: Into<ArrayImpl> bound for output wrapping
//   - Null propagation: if either input is None, output is None
//   - The Scalar trait's where clause provides: ArrayType::RefItem<'a> = RefType<'a>

// ---------------------------------------------------------------------------
// TODO: Implement comparison functions
// ---------------------------------------------------------------------------
//
// Four functions: cmp_le, cmp_ge, cmp_eq, cmp_ne
//
// Signature pattern:
//   pub fn cmp_le<I1: Scalar, I2: Scalar, C: Scalar>(
//       i1: I1::RefType<'_>, i2: I2::RefType<'_>
//   ) -> bool
//
// These support cross-type comparison by casting both inputs to a common
// type C via Into. Use Scalar::upcast_gat before the Into conversion
// to handle GAT lifetime covariance.
//
// Required bounds (on each function):
//   for<'a> I1::RefType<'a>: Into<C::RefType<'a>>
//   for<'a> I2::RefType<'a>: Into<C::RefType<'a>>
//   for<'a> C::RefType<'a>: PartialOrd  (or PartialEq for eq/ne)

// ---------------------------------------------------------------------------
// TODO: Implement str_contains
// ---------------------------------------------------------------------------
//
// pub fn str_contains(i1: &str, i2: &str) -> bool

// ---------------------------------------------------------------------------
// TODO: Implement dispatch macros
// ---------------------------------------------------------------------------
//
// for_all_cmp_combinations! — enumerates all valid (left_type, right_type, cast_type)
//   triples for cross-type comparisons. Each entry uses datatype macro idents:
//   { int16, int32, int32 } means "i16 vs i32, cast both to i32".
//
// impl_cmp_expression_of! — generates match arms for build_binary_expression.
//   Uses the pattern: $type_ident! { datatype_match_pattern } for match patterns
//   and $type_ident! { datatype_scalar } for BinaryExpression type parameters.

// ---------------------------------------------------------------------------
// TODO: Implement build_binary_expression
// ---------------------------------------------------------------------------

/// Build a type-erased expression from runtime type information.
///
/// Given an [`ExpressionFunc`] and the [`DataType`]s of its two inputs,
/// constructs a `Box<dyn Expression>` that can evaluate the expression
/// on `ArrayImpl` inputs with the correct physical types.
pub fn build_binary_expression(
    _f: ExpressionFunc,
    _i1: DataType,
    _i2: DataType,
) -> Box<dyn Expression> {
    todo!("Implement expression dispatch with datatype macros")
}
