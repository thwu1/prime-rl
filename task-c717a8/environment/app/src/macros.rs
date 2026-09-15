// Copyright 2024. Licensed under Apache-2.0.

//! Macros to enumerate all array/scalar type variants.

/// Enumerates all array type variants in the system.
///
/// Each tuple has six elements:
/// `{ EnumVariant, suffix, ArrayType, ArrayBuilderType, ScalarType, ScalarRefType }`
///
/// Used to generate enum definitions, From/TryFrom impls, and dispatch code.
macro_rules! for_all_variants {
    ($macro:ident $(, $x:ident)*) => {
        $macro! {
            [$($x),*],
            { Int16, int16, I16Array, I16ArrayBuilder, i16, i16 },
            { Int32, int32, I32Array, I32ArrayBuilder, i32, i32 },
            { Int64, int64, I64Array, I64ArrayBuilder, i64, i64 },
            { Float32, float32, F32Array, F32ArrayBuilder, f32, f32 },
            { Float64, float64, F64Array, F64ArrayBuilder, f64, f64 },
            { Bool, bool, BoolArray, BoolArrayBuilder, bool, bool },
            { String, string, StringArray, StringArrayBuilder, String, &'a str }
        }
    };
}

pub(crate) use for_all_variants;
