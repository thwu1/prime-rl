// Copyright 2024. Licensed under Apache-2.0.

//! Columnar array types with Generic Associated Types.
//!
//! Provides Array/ArrayBuilder traits, PrimitiveArray<T> for fixed-size types,
//! StringArray for variable-length strings, and ArrayImpl for dynamic dispatch.

use std::fmt::Debug;

use bitvec::prelude::BitVec;

use crate::TypeMismatch;

// ---------------------------------------------------------------------------
// Traits
// ---------------------------------------------------------------------------

/// A columnar array of values with null bitmap.
pub trait Array: Send + Sync + Sized + 'static {
    /// The builder type that constructs this array.
    type Builder: ArrayBuilder<Array = Self>;

    /// The owned scalar type stored in this array (e.g. `i32`, `String`).
    type OwnedItem: Debug + Clone + Send + Sync + 'static;

    /// The borrowed scalar type returned by `get` (e.g. `i32`, `&'a str`).
    /// Uses a Generic Associated Type (GAT) parameterized by lifetime `'a`.
    type RefItem<'a>: Debug + Copy + Send + 'a;

    /// Get the value at `idx`, or `None` if null.
    fn get(&self, idx: usize) -> Option<Self::RefItem<'_>>;

    /// Number of elements in the array.
    fn len(&self) -> usize;

    /// Returns an iterator over the array elements.
    fn iter(&self) -> ArrayIterator<'_, Self>;
}

/// Incrementally builds an [`Array`].
pub trait ArrayBuilder: Send + Sync + Sized + 'static {
    /// The array type this builder produces.
    type Array: Array<Builder = Self>;

    /// Create a new builder with the given capacity hint.
    fn with_capacity(capacity: usize) -> Self;

    /// Push a value (or null) onto the builder.
    fn push(&mut self, value: Option<<Self::Array as Array>::RefItem<'_>>);

    /// Consume the builder and produce a finished array.
    fn finish(self) -> Self::Array;
}

// ---------------------------------------------------------------------------
// ArrayIterator
// ---------------------------------------------------------------------------

/// Iterator over an [`Array`], yielding `Option<RefItem>` for each element.
pub struct ArrayIterator<'a, A: Array> {
    array: &'a A,
    pos: usize,
}

impl<'a, A: Array> ArrayIterator<'a, A> {
    pub fn new(array: &'a A) -> Self {
        Self { array, pos: 0 }
    }
}

impl<'a, A: Array> Iterator for ArrayIterator<'a, A> {
    type Item = Option<A::RefItem<'a>>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos < self.array.len() {
            let item = self.array.get(self.pos);
            self.pos += 1;
            Some(item)
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// PrimitiveType + PrimitiveArray
// ---------------------------------------------------------------------------

/// Marker trait for fixed-size primitive types.
pub trait PrimitiveType: Copy + Send + Sync + Default + Debug + 'static {}

impl PrimitiveType for i16 {}
impl PrimitiveType for i32 {}
impl PrimitiveType for i64 {}
impl PrimitiveType for f32 {}
impl PrimitiveType for f64 {}
impl PrimitiveType for bool {}

/// Type aliases for concrete primitive arrays.
pub type I16Array = PrimitiveArray<i16>;
pub type I32Array = PrimitiveArray<i32>;
pub type I64Array = PrimitiveArray<i64>;
pub type F32Array = PrimitiveArray<f32>;
pub type F64Array = PrimitiveArray<f64>;
pub type BoolArray = PrimitiveArray<bool>;

pub type I16ArrayBuilder = PrimitiveArrayBuilder<i16>;
pub type I32ArrayBuilder = PrimitiveArrayBuilder<i32>;
pub type I64ArrayBuilder = PrimitiveArrayBuilder<i64>;
pub type F32ArrayBuilder = PrimitiveArrayBuilder<f32>;
pub type F64ArrayBuilder = PrimitiveArrayBuilder<f64>;
pub type BoolArrayBuilder = PrimitiveArrayBuilder<bool>;

/// A columnar array storing fixed-size [`PrimitiveType`] values with a null bitmap.
///
/// Storage layout: separate data vector and bitmap for memory efficiency.
pub struct PrimitiveArray<T: PrimitiveType> {
    data: Vec<T>,
    bitmap: BitVec,
}

impl<T: PrimitiveType> Array for PrimitiveArray<T> {
    type Builder = PrimitiveArrayBuilder<T>;
    type OwnedItem = T;
    /// For primitives, RefItem is the same as OwnedItem (Copy types have no borrow overhead).
    type RefItem<'a> = T;

    fn get(&self, idx: usize) -> Option<T> {
        if self.bitmap[idx] {
            Some(self.data[idx])
        } else {
            None
        }
    }

    fn len(&self) -> usize {
        self.data.len()
    }

    fn iter(&self) -> ArrayIterator<'_, Self> {
        ArrayIterator::new(self)
    }
}

/// Builder for [`PrimitiveArray`].
pub struct PrimitiveArrayBuilder<T: PrimitiveType> {
    data: Vec<T>,
    bitmap: BitVec,
}

impl<T: PrimitiveType> ArrayBuilder for PrimitiveArrayBuilder<T> {
    type Array = PrimitiveArray<T>;

    fn with_capacity(capacity: usize) -> Self {
        Self {
            data: Vec::with_capacity(capacity),
            bitmap: BitVec::with_capacity(capacity),
        }
    }

    fn push(&mut self, value: Option<T>) {
        match value {
            Some(v) => {
                self.data.push(v);
                self.bitmap.push(true);
            }
            None => {
                self.data.push(T::default());
                self.bitmap.push(false);
            }
        }
    }

    fn finish(self) -> PrimitiveArray<T> {
        PrimitiveArray {
            data: self.data,
            bitmap: self.bitmap,
        }
    }
}

impl<T: PrimitiveType> PrimitiveArray<T> {
    /// Convenience constructor from a slice of optional values.
    pub fn from_slice(items: &[Option<T>]) -> Self {
        let mut builder = PrimitiveArrayBuilder::with_capacity(items.len());
        for item in items {
            builder.push(*item);
        }
        builder.finish()
    }
}

// ---------------------------------------------------------------------------
// StringArray
// ---------------------------------------------------------------------------

/// A columnar array storing variable-length UTF-8 strings.
///
/// Uses a flat byte buffer with offset array for compact storage.
pub struct StringArray {
    data: Vec<u8>,
    offsets: Vec<usize>,
    bitmap: BitVec,
}

impl Array for StringArray {
    type Builder = StringArrayBuilder;
    type OwnedItem = String;
    /// Returns `&'a str` — a borrowed view into the array's internal buffer.
    type RefItem<'a> = &'a str;

    fn get(&self, idx: usize) -> Option<&str> {
        if self.bitmap[idx] {
            let range = self.offsets[idx]..self.offsets[idx + 1];
            Some(unsafe { std::str::from_utf8_unchecked(&self.data[range]) })
        } else {
            None
        }
    }

    fn len(&self) -> usize {
        self.bitmap.len()
    }

    fn iter(&self) -> ArrayIterator<'_, Self> {
        ArrayIterator::new(self)
    }
}

/// Builder for [`StringArray`].
pub struct StringArrayBuilder {
    data: Vec<u8>,
    offsets: Vec<usize>,
    bitmap: BitVec,
}

impl ArrayBuilder for StringArrayBuilder {
    type Array = StringArray;

    fn with_capacity(capacity: usize) -> Self {
        let mut offsets = Vec::with_capacity(capacity + 1);
        offsets.push(0);
        Self {
            data: Vec::with_capacity(capacity),
            bitmap: BitVec::with_capacity(capacity),
            offsets,
        }
    }

    fn push(&mut self, value: Option<&str>) {
        match value {
            Some(v) => {
                self.data.extend(v.as_bytes());
                self.offsets.push(self.data.len());
                self.bitmap.push(true);
            }
            None => {
                self.offsets.push(self.data.len());
                self.bitmap.push(false);
            }
        }
    }

    fn finish(self) -> StringArray {
        StringArray {
            data: self.data,
            bitmap: self.bitmap,
            offsets: self.offsets,
        }
    }
}

impl StringArray {
    /// Convenience constructor from a slice of optional string slices.
    pub fn from_slice(items: &[Option<&str>]) -> Self {
        let mut builder = StringArrayBuilder::with_capacity(items.len());
        for item in items {
            builder.push(*item);
        }
        builder.finish()
    }
}

// ---------------------------------------------------------------------------
// ArrayImpl — dynamic dispatch enum over all array types
// ---------------------------------------------------------------------------

/// Runtime-typed array that wraps any concrete array type.
pub enum ArrayImpl {
    Int16(I16Array),
    Int32(I32Array),
    Int64(I64Array),
    Float32(F32Array),
    Float64(F64Array),
    Bool(BoolArray),
    String(StringArray),
}

impl ArrayImpl {
    /// Returns the type name of the contained array.
    pub fn type_name(&self) -> &'static str {
        match self {
            ArrayImpl::Int16(_) => "Int16",
            ArrayImpl::Int32(_) => "Int32",
            ArrayImpl::Int64(_) => "Int64",
            ArrayImpl::Float32(_) => "Float32",
            ArrayImpl::Float64(_) => "Float64",
            ArrayImpl::Bool(_) => "Bool",
            ArrayImpl::String(_) => "String",
        }
    }

    /// Get the value at `idx` as a dynamically-typed [`ScalarRefImpl`].
    pub fn get(&self, idx: usize) -> Option<crate::scalar::ScalarRefImpl<'_>> {
        use crate::scalar::ScalarRefImpl;
        match self {
            ArrayImpl::Int16(a) => a.get(idx).map(ScalarRefImpl::Int16),
            ArrayImpl::Int32(a) => a.get(idx).map(ScalarRefImpl::Int32),
            ArrayImpl::Int64(a) => a.get(idx).map(ScalarRefImpl::Int64),
            ArrayImpl::Float32(a) => a.get(idx).map(ScalarRefImpl::Float32),
            ArrayImpl::Float64(a) => a.get(idx).map(ScalarRefImpl::Float64),
            ArrayImpl::Bool(a) => a.get(idx).map(ScalarRefImpl::Bool),
            ArrayImpl::String(a) => a.get(idx).map(ScalarRefImpl::String),
        }
    }

    /// Number of elements in the contained array.
    pub fn len(&self) -> usize {
        match self {
            ArrayImpl::Int16(a) => a.len(),
            ArrayImpl::Int32(a) => a.len(),
            ArrayImpl::Int64(a) => a.len(),
            ArrayImpl::Float32(a) => a.len(),
            ArrayImpl::Float64(a) => a.len(),
            ArrayImpl::Bool(a) => a.len(),
            ArrayImpl::String(a) => a.len(),
        }
    }
}

// From<ConcreteArray> for ArrayImpl and TryFrom<&ArrayImpl> for &ConcreteArray
macro_rules! impl_array_conversion {
    ($variant:ident, $array_type:ty) => {
        impl From<$array_type> for ArrayImpl {
            fn from(a: $array_type) -> Self {
                ArrayImpl::$variant(a)
            }
        }

        impl<'a> TryFrom<&'a ArrayImpl> for &'a $array_type {
            type Error = TypeMismatch;
            fn try_from(a: &'a ArrayImpl) -> Result<Self, Self::Error> {
                match a {
                    ArrayImpl::$variant(inner) => Ok(inner),
                    other => Err(TypeMismatch {
                        expected: stringify!($variant),
                        actual: other.type_name(),
                    }),
                }
            }
        }
    };
}

impl_array_conversion!(Int16, I16Array);
impl_array_conversion!(Int32, I32Array);
impl_array_conversion!(Int64, I64Array);
impl_array_conversion!(Float32, F32Array);
impl_array_conversion!(Float64, F64Array);
impl_array_conversion!(Bool, BoolArray);
impl_array_conversion!(String, StringArray);
