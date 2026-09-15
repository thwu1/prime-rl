// Copyright 2024. Licensed under Apache-2.0.

//! Logical data types for the database system.
//!
//! This module defines the `DataType` enum representing SQL logical types.
//!
//! TODO: You must also implement datatype association macros in this file.
//! These macros bridge logical SQL types to physical Rust types and are used
//! by the expression dispatch system in `expr.rs`.

/// All supported logical data types in the system.
#[derive(Debug)]
pub enum DataType {
    /// 16-bit integer — physical type: `i16` / `I16Array`
    SmallInt,
    /// 32-bit integer — physical type: `i32` / `I32Array`
    Integer,
    /// 64-bit integer — physical type: `i64` / `I64Array`
    BigInt,
    /// Variable-length string — physical type: `String` / `StringArray`
    Varchar,
    /// Fixed-width string — physical type: `String` / `StringArray`
    Char { width: u16 },
    /// Boolean — physical type: `bool` / `BoolArray`
    Boolean,
    /// 32-bit float — physical type: `f32` / `F32Array`
    Real,
    /// 64-bit float — physical type: `f64` / `F64Array`
    Double,
}

// ---------------------------------------------------------------------------
// TODO: Implement datatype extraction macros
// ---------------------------------------------------------------------------
//
// You need three extraction macros that decompose a (match_pattern, array_type,
// scalar_type) triple. Each takes three token-tree arguments and returns one:
//
//   datatype_match_pattern!(pat, arr, scalar) => pat
//   datatype_array!(pat, arr, scalar)         => arr
//   datatype_scalar!(pat, arr, scalar)        => scalar
//
// These must be #[macro_export] so they are visible crate-wide.

// ---------------------------------------------------------------------------
// TODO: Implement datatype association macros
// ---------------------------------------------------------------------------
//
// For each logical type, define a macro that calls its argument macro with
// the type's (match_pattern, array_type, scalar_type) triple. Example usage:
//
//   int32! { datatype_scalar }
//   // expands to: datatype_scalar!(DataType::Integer, I32Array, i32)
//   // which expands to: i32
//
// Required association macros (all #[macro_export]):
//   int16!    — SmallInt  → (DataType::SmallInt, I16Array, i16)
//   int32!    — Integer   → (DataType::Integer, I32Array, i32)
//   int64!    — BigInt    → (DataType::BigInt, I64Array, i64)
//   float32!  — Real      → (DataType::Real, F32Array, f32)
//   float64!  — Double    → (DataType::Double, F64Array, f64)
//   varchar!  — Varchar   → (DataType::Varchar, StringArray, String)
//   fwchar!   — Char {..} → (DataType::Char { .. }, StringArray, String)
//
// Use $crate:: prefixed paths for DataType and array types to ensure
// correct resolution regardless of the expansion site.
