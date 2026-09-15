// Copyright 2024. Licensed under Apache-2.0.

//! Vectorized expression evaluation framework for a database engine.
//!
//! This crate provides:
//! - Columnar array types with Generic Associated Types (GATs)
//! - Scalar/ScalarRef reciprocal trait system
//! - Dynamic dispatch via ArrayImpl/ScalarImpl enums
//! - Vectorized expression evaluation (to be implemented in `expr` module)

pub mod array;
pub mod datatype;
pub mod expr;
#[macro_use]
pub mod macros;
pub mod scalar;

use thiserror::Error;

#[derive(Error, Debug)]
#[error("Type mismatch on conversion: expected {expected}, got {actual}")]
pub struct TypeMismatch {
    pub expected: &'static str,
    pub actual: &'static str,
}
