//! Postcard serializer — compact binary wire format
//!
//! Encodes Rust types into a deterministic binary representation suitable
//! for resource-constrained embedded targets. Integers wider than 8 bits
//! use a variable-length encoding to save space on small values.

use core::mem;
use serde::ser::{self, Serialize, SerializeMap, SerializeSeq, SerializeStruct,
                  SerializeStructVariant, SerializeTuple, SerializeTupleStruct,
                  SerializeTupleVariant};

pub struct Serializer {
    output: Vec<u8>,
}

#[derive(Debug)]
pub enum Error {
    Custom(String),
    SeqLenRequired,
    MapLenRequired,
}

type Result<T> = core::result::Result<T, Error>;

impl Serializer {
    pub fn new() -> Self {
        Serializer { output: Vec::new() }
    }

    pub fn into_bytes(self) -> Vec<u8> {
        self.output
    }

    /// Variable-length unsigned integer encoding.
    ///
    /// Data is packed 7 bits per byte, least-significant group first.
    /// The most-significant bit of each byte is set to 1 if more bytes
    /// follow, and cleared on the final byte.
    fn push_varint(&mut self, mut value: u128) {
        loop {
            if value < 0x80 {
                self.output.push(value as u8);
                return;
            }
            self.output.push(((value & 0x7F) as u8) | 0x80);
            value >>= 7;
        }
    }

    /// Signed integer encoding via zigzag transform.
    ///
    /// Maps signed values to unsigned space so that values of small
    /// absolute magnitude produce small encoded outputs:
    ///   n >= 0  =>  2 * n
    ///   n <  0  =>  2 * |n| - 1
    ///
    /// Equivalently: (n << 1) ^ (n >> (bits - 1)) using arithmetic shift.
    fn push_zigzag_varint(&mut self, value: i128) {
        let mapped = if value >= 0 {
            (value as u128) << 1
        } else {
            ((-(value + 1)) as u128) << 1 | 1
        };
        self.push_varint(mapped);
    }

    fn push_raw(&mut self, bytes: &[u8]) {
        self.output.extend_from_slice(bytes);
    }
}

impl<'a> ser::Serializer for &'a mut Serializer {
    type Ok = ();
    type Error = Error;
    type SerializeSeq = SeqSer<'a>;
    type SerializeTuple = TupleSer<'a>;
    type SerializeTupleStruct = TupleStructSer<'a>;
    type SerializeTupleVariant = TupleVariantSer<'a>;
    type SerializeMap = MapSer<'a>;
    type SerializeStruct = StructSer<'a>;
    type SerializeStructVariant = StructVariantSer<'a>;

    fn serialize_bool(self, v: bool) -> Result<()> {
        self.output.push(if v { 1 } else { 0 });
        Ok(())
    }

    // i8 and u8 are stored as single raw bytes — NOT varint-encoded.
    fn serialize_i8(self, v: i8) -> Result<()> {
        self.output.push(v as u8);
        Ok(())
    }

    fn serialize_u8(self, v: u8) -> Result<()> {
        self.output.push(v);
        Ok(())
    }

    // All wider integers use varint encoding.
    // Signed types apply zigzag transform before varint encoding.
    fn serialize_i16(self, v: i16) -> Result<()> {
        self.push_zigzag_varint(v as i128);
        Ok(())
    }

    fn serialize_i32(self, v: i32) -> Result<()> {
        self.push_zigzag_varint(v as i128);
        Ok(())
    }

    fn serialize_i64(self, v: i64) -> Result<()> {
        self.push_zigzag_varint(v as i128);
        Ok(())
    }

    fn serialize_i128(self, v: i128) -> Result<()> {
        self.push_zigzag_varint(v);
        Ok(())
    }

    fn serialize_u16(self, v: u16) -> Result<()> {
        self.push_varint(v as u128);
        Ok(())
    }

    fn serialize_u32(self, v: u32) -> Result<()> {
        self.push_varint(v as u128);
        Ok(())
    }

    fn serialize_u64(self, v: u64) -> Result<()> {
        self.push_varint(v as u128);
        Ok(())
    }

    fn serialize_u128(self, v: u128) -> Result<()> {
        self.push_varint(v);
        Ok(())
    }

    // Floats are bitwise-converted to their integer representation
    // and written as fixed-width little-endian bytes. NOT varint.
    fn serialize_f32(self, v: f32) -> Result<()> {
        self.push_raw(&v.to_le_bytes());
        Ok(())
    }

    fn serialize_f64(self, v: f64) -> Result<()> {
        self.push_raw(&v.to_le_bytes());
        Ok(())
    }

    fn serialize_str(self, v: &str) -> Result<()> {
        let bytes = v.as_bytes();
        // Length prefix uses usize which is u32 on this platform
        self.push_varint(bytes.len() as u128);
        self.push_raw(bytes);
        Ok(())
    }

    fn serialize_bytes(self, v: &[u8]) -> Result<()> {
        self.push_varint(v.len() as u128);
        self.push_raw(v);
        Ok(())
    }

    fn serialize_none(self) -> Result<()> {
        self.output.push(0x00);
        Ok(())
    }

    fn serialize_some<T: ?Sized + Serialize>(self, value: &T) -> Result<()> {
        self.output.push(0x01);
        value.serialize(self)
    }

    fn serialize_unit(self) -> Result<()> {
        // Zero bytes on the wire
        Ok(())
    }

    fn serialize_unit_struct(self, _name: &'static str) -> Result<()> {
        Ok(())
    }

    fn serialize_unit_variant(
        self, _name: &'static str, variant_index: u32, _variant: &'static str,
    ) -> Result<()> {
        // Discriminant only, encoded as varint(u32)
        self.push_varint(variant_index as u128);
        Ok(())
    }

    fn serialize_newtype_struct<T: ?Sized + Serialize>(
        self, _name: &'static str, value: &T,
    ) -> Result<()> {
        value.serialize(self)
    }

    fn serialize_newtype_variant<T: ?Sized + Serialize>(
        self, _name: &'static str, variant_index: u32, _variant: &'static str, value: &T,
    ) -> Result<()> {
        self.push_varint(variant_index as u128);
        value.serialize(self)
    }

    fn serialize_seq(self, len: Option<usize>) -> Result<Self::SerializeSeq> {
        let len = len.ok_or(Error::SeqLenRequired)?;
        self.push_varint(len as u128);
        Ok(SeqSer { ser: self })
    }

    fn serialize_tuple(self, _len: usize) -> Result<Self::SerializeTuple> {
        // Tuples: no count prefix, elements serialized in order
        Ok(TupleSer { ser: self })
    }

    fn serialize_tuple_struct(
        self, _name: &'static str, _len: usize,
    ) -> Result<Self::SerializeTupleStruct> {
        Ok(TupleStructSer { ser: self })
    }

    fn serialize_tuple_variant(
        self, _name: &'static str, variant_index: u32, _variant: &'static str, _len: usize,
    ) -> Result<Self::SerializeTupleVariant> {
        self.push_varint(variant_index as u128);
        Ok(TupleVariantSer { ser: self })
    }

    fn serialize_map(self, len: Option<usize>) -> Result<Self::SerializeMap> {
        let len = len.ok_or(Error::MapLenRequired)?;
        self.push_varint(len as u128);
        Ok(MapSer { ser: self })
    }

    fn serialize_struct(
        self, _name: &'static str, _len: usize,
    ) -> Result<Self::SerializeStruct> {
        // Structs: fields in definition order, no names/count on wire
        Ok(StructSer { ser: self })
    }

    fn serialize_struct_variant(
        self, _name: &'static str, variant_index: u32, _variant: &'static str, _len: usize,
    ) -> Result<Self::SerializeStructVariant> {
        self.push_varint(variant_index as u128);
        Ok(StructVariantSer { ser: self })
    }
}

// --- Compound serializer helpers ---

pub struct SeqSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeSeq for SeqSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_element<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct TupleSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeTuple for TupleSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_element<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct TupleStructSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeTupleStruct for TupleStructSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct TupleVariantSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeTupleVariant for TupleVariantSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct MapSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeMap for MapSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_key<T: ?Sized + Serialize>(&mut self, key: &T) -> Result<()> {
        key.serialize(&mut *self.ser)
    }
    fn serialize_value<T: ?Sized + Serialize>(&mut self, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct StructSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeStruct for StructSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, _key: &'static str, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}

pub struct StructVariantSer<'a> { ser: &'a mut Serializer }
impl<'a> SerializeStructVariant for StructVariantSer<'a> {
    type Ok = (); type Error = Error;
    fn serialize_field<T: ?Sized + Serialize>(&mut self, _key: &'static str, value: &T) -> Result<()> {
        value.serialize(&mut *self.ser)
    }
    fn end(self) -> Result<()> { Ok(()) }
}
