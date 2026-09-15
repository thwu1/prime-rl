// Copyright 2024. Licensed under Apache-2.0.

//! Logical data types and their association macros.

/// All supported logical data types in the system.
#[derive(Debug)]
pub enum DataType {
    SmallInt,
    Integer,
    BigInt,
    Varchar,
    Char { width: u16 },
    Boolean,
    Real,
    Double,
}

// ---------------------------------------------------------------------------
// Extraction macros
// ---------------------------------------------------------------------------

/// Extract the match pattern from a (pattern, array, scalar) triple.
#[macro_export]
macro_rules! datatype_match_pattern {
    ($match_pattern:pat, $array:ty, $scalar:ty) => {
        $match_pattern
    };
}

/// Extract the array type from a (pattern, array, scalar) triple.
#[macro_export]
macro_rules! datatype_array {
    ($match_pattern:pat, $array:ty, $scalar:ty) => {
        $array
    };
}

/// Extract the scalar type from a (pattern, array, scalar) triple.
#[macro_export]
macro_rules! datatype_scalar {
    ($match_pattern:pat, $array:ty, $scalar:ty) => {
        $scalar
    };
}

// ---------------------------------------------------------------------------
// Association macros — map logical SQL types to physical Rust types
// ---------------------------------------------------------------------------

#[macro_export]
macro_rules! int16 {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::SmallInt, $crate::array::I16Array, i16)
    };
}

#[macro_export]
macro_rules! int32 {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::Integer, $crate::array::I32Array, i32)
    };
}

#[macro_export]
macro_rules! int64 {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::BigInt, $crate::array::I64Array, i64)
    };
}

#[macro_export]
macro_rules! float32 {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::Real, $crate::array::F32Array, f32)
    };
}

#[macro_export]
macro_rules! float64 {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::Double, $crate::array::F64Array, f64)
    };
}

#[macro_export]
macro_rules! varchar {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::Varchar, $crate::array::StringArray, String)
    };
}

#[macro_export]
macro_rules! fwchar {
    ($macro:ident) => {
        $macro!($crate::datatype::DataType::Char { .. }, $crate::array::StringArray, String)
    };
}

pub use datatype_match_pattern;
pub use datatype_array;
pub use datatype_scalar;
pub use int16;
pub use int32;
pub use int64;
pub use float32;
pub use float64;
pub use varchar;
pub use fwchar;
