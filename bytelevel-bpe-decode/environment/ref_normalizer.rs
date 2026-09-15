// Excerpted from huggingface/tokenizers — tokenizer-core/src/normalizers/byte_level.rs
//
// ByteLevel normalizer: transforms token content by mapping each UTF-8 byte
// through the bytes_char() table. Used when added tokens have normalized=true.

use crate::processors::byte_level::bytes_char;
use crate::tokenizer::{NormalizedString, Normalizer, Result};
use ahash::{AHashMap, AHashSet};
use std::sync::LazyLock;

#[derive(Clone, Debug)]
pub struct ByteLevel;

static BYTES_CHAR: LazyLock<AHashMap<u8, char>> = LazyLock::new(bytes_char);

impl ByteLevel {
    pub fn new() -> Self {
        Self {}
    }

    pub fn alphabet() -> AHashSet<char> {
        BYTES_CHAR.values().copied().collect()
    }
}

impl Normalizer for ByteLevel {
    /// Normalize the string by converting each UTF-8 byte of each character
    /// to its corresponding mapped unicode character via bytes_char().
    fn normalize(&self, normalized: &mut NormalizedString) -> Result<()> {
        if !normalized.is_empty() {
            let s = normalized.get();
            let mut transformations: Vec<(char, isize)> = Vec::with_capacity(s.len());
            for (i, cur_char) in s.char_indices() {
                let size = cur_char.len_utf8();
                transformations.extend(
                    s.as_bytes()[i..i + size]
                        .iter()
                        .enumerate()
                        .map(|(i, b)| (BYTES_CHAR[b], isize::from(i > 0))),
                );
            }
            normalized.transform(transformations, 0);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_byte_level_normalize() {
        let original = "Hello 我今天能为你做什么";
        let normalized = "HelloĠæĪĳä»Ĭå¤©èĥ½ä¸ºä½łåģļä»Ģä¹Ī";
        assert_ne!(original, normalized);
        let mut n = NormalizedString::from(original);
        let byte_level = ByteLevel::new();
        byte_level.normalize(&mut n).unwrap();
        assert_eq!(&n.get(), &normalized);
    }
}
