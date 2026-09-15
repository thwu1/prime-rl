// Copyright 2024. Licensed under Apache-2.0.

//! Scalar and ScalarRef reciprocal trait system.
//!
//! `Scalar` is an owned value (e.g., `i32`, `String`).
//! `ScalarRef<'a>` is a borrowed view (e.g., `i32`, `&'a str`).
//!
//! The key innovation is `upcast_gat`: it explicitly performs the covariant
//! lifetime cast on GAT types that the Rust compiler cannot infer automatically.

use crate::array::*;
use crate::TypeMismatch;

// ---------------------------------------------------------------------------
// Traits
// ---------------------------------------------------------------------------

/// An owned single value associated with an [`Array`] type.
///
/// The `where` clause establishes the critical GAT connection:
/// `ArrayType::RefItem<'a> == RefType<'a>` for all lifetimes.
pub trait Scalar:
    std::fmt::Debug + Clone + Send + Sync + 'static
where
    for<'a> Self::ArrayType: Array<RefItem<'a> = Self::RefType<'a>>,
{
    /// The corresponding columnar array type.
    type ArrayType: Array<OwnedItem = Self>;

    /// The corresponding borrowed reference type (a GAT).
    type RefType<'a>: ScalarRef<'a, ScalarType = Self, ArrayType = Self::ArrayType>;

    /// Get a reference view of this owned value.
    fn as_scalar_ref(&self) -> Self::RefType<'_>;

    /// Upcast a GAT lifetime: convert `RefType<'long>` to `RefType<'short>`.
    ///
    /// This is needed because the Rust compiler cannot automatically prove
    /// covariance of GAT lifetime parameters. For primitive types this is
    /// identity; for `&'a str` it performs the natural reference coercion.
    fn upcast_gat<'short, 'long: 'short>(long: Self::RefType<'long>) -> Self::RefType<'short>;
}

/// A borrowed view of a [`Scalar`] value.
pub trait ScalarRef<'a>: std::fmt::Debug + Clone + Copy + Send + 'a {
    /// The corresponding columnar array type.
    type ArrayType: Array<RefItem<'a> = Self>;

    /// The corresponding owned scalar type.
    type ScalarType: Scalar<RefType<'a> = Self>;

    /// Convert this borrowed view into an owned scalar.
    fn to_owned_scalar(&self) -> Self::ScalarType;
}

// ---------------------------------------------------------------------------
// Scalar/ScalarRef impls for primitive types
// ---------------------------------------------------------------------------

macro_rules! impl_primitive_scalar {
    ($type:ty, $array_type:ty, $variant:ident) => {
        impl Scalar for $type {
            type ArrayType = $array_type;
            type RefType<'a> = $type;

            fn as_scalar_ref(&self) -> $type {
                *self
            }

            fn upcast_gat<'short, 'long: 'short>(long: $type) -> $type {
                long
            }
        }

        impl<'a> ScalarRef<'a> for $type {
            type ArrayType = $array_type;
            type ScalarType = $type;

            fn to_owned_scalar(&self) -> $type {
                *self
            }
        }
    };
}

impl_primitive_scalar!(i16, I16Array, Int16);
impl_primitive_scalar!(i32, I32Array, Int32);
impl_primitive_scalar!(i64, I64Array, Int64);
impl_primitive_scalar!(f32, F32Array, Float32);
impl_primitive_scalar!(f64, F64Array, Float64);
impl_primitive_scalar!(bool, BoolArray, Bool);

// ---------------------------------------------------------------------------
// Scalar/ScalarRef impls for String / &str
// ---------------------------------------------------------------------------

impl Scalar for String {
    type ArrayType = StringArray;
    type RefType<'a> = &'a str;

    fn as_scalar_ref(&self) -> &str {
        self.as_str()
    }

    /// For `&str`, upcasting simply coerces `&'long str` to `&'short str`
    /// via the natural covariance of references.
    fn upcast_gat<'short, 'long: 'short>(long: &'long str) -> &'short str {
        long
    }
}

impl<'a> ScalarRef<'a> for &'a str {
    type ArrayType = StringArray;
    type ScalarType = String;

    fn to_owned_scalar(&self) -> String {
        self.to_string()
    }
}

// ---------------------------------------------------------------------------
// ScalarImpl — dynamically-typed owned scalar
// ---------------------------------------------------------------------------

/// Runtime-typed owned scalar value.
#[derive(Debug, Clone)]
pub enum ScalarImpl {
    Int16(i16),
    Int32(i32),
    Int64(i64),
    Float32(f32),
    Float64(f64),
    Bool(bool),
    String(String),
}

impl ScalarImpl {
    pub fn type_name(&self) -> &'static str {
        match self {
            ScalarImpl::Int16(_) => "Int16",
            ScalarImpl::Int32(_) => "Int32",
            ScalarImpl::Int64(_) => "Int64",
            ScalarImpl::Float32(_) => "Float32",
            ScalarImpl::Float64(_) => "Float64",
            ScalarImpl::Bool(_) => "Bool",
            ScalarImpl::String(_) => "String",
        }
    }
}

impl PartialEq for ScalarImpl {
    fn eq(&self, other: &Self) -> bool {
        use ScalarImpl::*;
        match (self, other) {
            (Int16(a), Int16(b)) => a == b,
            (Int32(a), Int32(b)) => a == b,
            (Int64(a), Int64(b)) => a == b,
            (Float32(a), Float32(b)) => a == b,
            (Float64(a), Float64(b)) => a == b,
            (Bool(a), Bool(b)) => a == b,
            (String(a), String(b)) => a == b,
            _ => false,
        }
    }
}

// ---------------------------------------------------------------------------
// ScalarRefImpl — dynamically-typed borrowed scalar
// ---------------------------------------------------------------------------

/// Runtime-typed borrowed scalar value.
#[derive(Debug, Clone, Copy)]
pub enum ScalarRefImpl<'a> {
    Int16(i16),
    Int32(i32),
    Int64(i64),
    Float32(f32),
    Float64(f64),
    Bool(bool),
    String(&'a str),
}

impl ScalarRefImpl<'_> {
    pub fn type_name(&self) -> &'static str {
        match self {
            ScalarRefImpl::Int16(_) => "Int16",
            ScalarRefImpl::Int32(_) => "Int32",
            ScalarRefImpl::Int64(_) => "Int64",
            ScalarRefImpl::Float32(_) => "Float32",
            ScalarRefImpl::Float64(_) => "Float64",
            ScalarRefImpl::Bool(_) => "Bool",
            ScalarRefImpl::String(_) => "String",
        }
    }
}

impl PartialEq for ScalarRefImpl<'_> {
    fn eq(&self, other: &Self) -> bool {
        use ScalarRefImpl::*;
        match (self, other) {
            (Int16(a), Int16(b)) => a == b,
            (Int32(a), Int32(b)) => a == b,
            (Int64(a), Int64(b)) => a == b,
            (Float32(a), Float32(b)) => a == b,
            (Float64(a), Float64(b)) => a == b,
            (Bool(a), Bool(b)) => a == b,
            (String(a), String(b)) => a == b,
            _ => false,
        }
    }
}

// ---------------------------------------------------------------------------
// From / TryFrom for ScalarImpl and ScalarRefImpl
// ---------------------------------------------------------------------------

macro_rules! impl_scalar_conversion {
    ($type:ty, $variant:ident) => {
        impl From<$type> for ScalarImpl {
            fn from(v: $type) -> Self {
                ScalarImpl::$variant(v)
            }
        }

        impl TryFrom<ScalarImpl> for $type {
            type Error = TypeMismatch;
            fn try_from(v: ScalarImpl) -> Result<Self, Self::Error> {
                match v {
                    ScalarImpl::$variant(v) => Ok(v),
                    other => Err(TypeMismatch {
                        expected: stringify!($variant),
                        actual: other.type_name(),
                    }),
                }
            }
        }

        impl<'a> From<$type> for ScalarRefImpl<'a> {
            fn from(v: $type) -> Self {
                ScalarRefImpl::$variant(v)
            }
        }

        impl<'a> TryFrom<ScalarRefImpl<'a>> for $type {
            type Error = TypeMismatch;
            fn try_from(v: ScalarRefImpl<'a>) -> Result<Self, Self::Error> {
                match v {
                    ScalarRefImpl::$variant(v) => Ok(v),
                    other => Err(TypeMismatch {
                        expected: stringify!($variant),
                        actual: other.type_name(),
                    }),
                }
            }
        }
    };
}

impl_scalar_conversion!(i16, Int16);
impl_scalar_conversion!(i32, Int32);
impl_scalar_conversion!(i64, Int64);
impl_scalar_conversion!(f32, Float32);
impl_scalar_conversion!(f64, Float64);
impl_scalar_conversion!(bool, Bool);

// String has different owned/ref types, so implement manually:

impl From<String> for ScalarImpl {
    fn from(v: String) -> Self {
        ScalarImpl::String(v)
    }
}

impl TryFrom<ScalarImpl> for String {
    type Error = TypeMismatch;
    fn try_from(v: ScalarImpl) -> Result<Self, Self::Error> {
        match v {
            ScalarImpl::String(v) => Ok(v),
            other => Err(TypeMismatch {
                expected: "String",
                actual: other.type_name(),
            }),
        }
    }
}

impl<'a> From<&'a str> for ScalarRefImpl<'a> {
    fn from(v: &'a str) -> Self {
        ScalarRefImpl::String(v)
    }
}

impl<'a> TryFrom<ScalarRefImpl<'a>> for &'a str {
    type Error = TypeMismatch;
    fn try_from(v: ScalarRefImpl<'a>) -> Result<Self, Self::Error> {
        match v {
            ScalarRefImpl::String(v) => Ok(v),
            other => Err(TypeMismatch {
                expected: "String",
                actual: other.type_name(),
            }),
        }
    }
}
