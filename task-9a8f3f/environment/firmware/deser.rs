//! Postcard deserializer
//!
//! Decodes the compact binary wire format back into Rust types.
//! The decoder enforces maximum varint lengths based on the target
//! type's bit width: ceil(type_bits / 7) bytes.

use serde::de::{self, Deserialize, Visitor};

pub struct Deserializer<'de> {
    input: &'de [u8],
    pos: usize,
}

#[derive(Debug)]
pub enum Error {
    UnexpectedEnd,
    VarintOverflow,
    VarintTooLong,
    InvalidBool(u8),
    InvalidUtf8,
    Custom(String),
}

type Result<T> = core::result::Result<T, Error>;

impl<'de> Deserializer<'de> {
    pub fn new(input: &'de [u8]) -> Self {
        Deserializer { input, pos: 0 }
    }

    pub fn bytes_consumed(&self) -> usize {
        self.pos
    }

    /// Decode a variable-length unsigned integer.
    ///
    /// `max_bytes` limits the number of encoded bytes accepted,
    /// preventing overlong encodings. For a type with N bits:
    ///   max_bytes = ceil(N / 7)
    ///
    /// Additionally, the decoded value must fit within the type's
    /// range (0..2^N). Values exceeding the range are rejected.
    fn pull_varint(&mut self, max_bytes: usize, max_value: u128) -> Result<u128> {
        let mut value: u128 = 0;
        let mut shift: u32 = 0;

        for _ in 0..max_bytes {
            if self.pos >= self.input.len() {
                return Err(Error::UnexpectedEnd);
            }
            let byte = self.input[self.pos];
            self.pos += 1;

            value |= ((byte & 0x7F) as u128) << shift;

            if byte & 0x80 == 0 {
                if value > max_value {
                    return Err(Error::VarintOverflow);
                }
                return Ok(value);
            }
            shift += 7;
        }

        Err(Error::VarintTooLong)
    }

    /// Decode a zigzag-encoded signed integer.
    ///
    /// Reverses the zigzag mapping:
    ///   even n  =>  n / 2
    ///   odd  n  =>  -(n / 2) - 1
    fn pull_zigzag_varint(&mut self, max_bytes: usize, max_unsigned: u128) -> Result<i128> {
        let raw = self.pull_varint(max_bytes, max_unsigned)?;
        Ok(if raw & 1 == 0 {
            (raw >> 1) as i128
        } else {
            -((raw >> 1) as i128) - 1
        })
    }

    fn pull_u8(&mut self) -> Result<u8> {
        if self.pos >= self.input.len() {
            return Err(Error::UnexpectedEnd);
        }
        let v = self.input[self.pos];
        self.pos += 1;
        Ok(v)
    }

    fn pull_f32(&mut self) -> Result<f32> {
        if self.pos + 4 > self.input.len() {
            return Err(Error::UnexpectedEnd);
        }
        let bytes: [u8; 4] = self.input[self.pos..self.pos + 4].try_into().unwrap();
        self.pos += 4;
        Ok(f32::from_le_bytes(bytes))
    }

    fn pull_f64(&mut self) -> Result<f64> {
        if self.pos + 8 > self.input.len() {
            return Err(Error::UnexpectedEnd);
        }
        let bytes: [u8; 8] = self.input[self.pos..self.pos + 8].try_into().unwrap();
        self.pos += 8;
        Ok(f64::from_le_bytes(bytes))
    }

    // usize on the target platform is 32 bits, so lengths use u32 varint
    fn pull_length(&mut self) -> Result<usize> {
        self.pull_varint(5, u32::MAX as u128).map(|v| v as usize)
    }

    fn pull_str(&mut self) -> Result<&'de str> {
        let len = self.pull_length()?;
        if self.pos + len > self.input.len() {
            return Err(Error::UnexpectedEnd);
        }
        let s = core::str::from_utf8(&self.input[self.pos..self.pos + len])
            .map_err(|_| Error::InvalidUtf8)?;
        self.pos += len;
        Ok(s)
    }

    fn pull_bytes(&mut self) -> Result<&'de [u8]> {
        let len = self.pull_length()?;
        if self.pos + len > self.input.len() {
            return Err(Error::UnexpectedEnd);
        }
        let b = &self.input[self.pos..self.pos + len];
        self.pos += len;
        Ok(b)
    }

    fn pull_bool(&mut self) -> Result<bool> {
        let v = self.pull_u8()?;
        match v {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(Error::InvalidBool(v)),
        }
    }

    // Enum discriminants use u32 varint (max 5 bytes)
    fn pull_discriminant(&mut self) -> Result<u32> {
        self.pull_varint(5, u32::MAX as u128).map(|v| v as u32)
    }
}
