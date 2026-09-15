// Excerpted from huggingface/tokenizers — tokenizer-core/src/processors/byte_level.rs
//
// The ByteLevel processor handles conversion between UTF-8 text and
// byte-level token representations used by GPT-2-family tokenizers.

use ahash::{AHashMap, AHashSet};
use std::sync::LazyLock;

/// Converts bytes to unicode characters.
/// See https://github.com/openai/gpt-2/blob/master/src/encoder.py#L9
pub(crate) fn bytes_char() -> AHashMap<u8, char> {
    let mut bs: Vec<u8> = vec![];
    bs.extend(b'!'..=b'~');
    bs.extend(b'\xA1'..=b'\xAC');
    bs.extend(b'\xAE'..=b'\xFF');

    let mut cs: Vec<u32> = bs.iter().map(|i| *i as u32).collect();
    let mut n = 0;

    for b in 0..=255u8 {
        if !bs.contains(&b) {
            bs.push(b);
            cs.push(u32::pow(2, 8) + n);
            n += 1;
        }
    }

    // Safety: cs contains all values from bs (between 0 and 255),
    // and some values of value 2^8 + n, where n is between 0 and 255.
    // Both ranges are valid UTF-32 values.
    bs.into_iter()
        .zip(cs)
        .map(|(f, t)| (f, unsafe { std::char::from_u32_unchecked(t) }))
        .collect()
}

static BYTES_CHAR: LazyLock<AHashMap<u8, char>> = LazyLock::new(bytes_char);
static CHAR_BYTES: LazyLock<AHashMap<char, u8>> =
    LazyLock::new(|| bytes_char().into_iter().map(|(c, b)| (b, c)).collect());

#[derive(Copy, Clone, Debug, PartialEq, Eq)]
/// Provides all the necessary steps to handle the BPE tokenization at the
/// byte-level. Takes care of all the required processing steps to transform
/// a UTF-8 string as needed before and after the BPE model does its job.
pub struct ByteLevel {
    /// Whether to add a leading space to the first word.
    pub add_prefix_space: bool,
    /// Whether the post processing step should trim offsets.
    pub trim_offsets: bool,
    /// Whether to use the standard GPT2 regex for whitespace splitting.
    pub use_regex: bool,
}

/// As a `PreTokenizer`, `ByteLevel` is in charge of transforming all the
/// unicode characters into their byte-level counterpart. It also splits the
/// input according to the configured regex.
impl PreTokenizer for ByteLevel {
    fn pre_tokenize(&self, pretokenized: &mut PreTokenizedString) -> Result<()> {
        let re_ref: &SysRegex = &RE;
        pretokenized.split(|_, mut normalized| {
            if self.add_prefix_space && !normalized.get().starts_with(' ') {
                normalized.prepend(" ");
            }
            if self.use_regex {
                normalized.split(re_ref, SplitDelimiterBehavior::Isolated)
            } else {
                Ok(vec![normalized])
            }
        })?;
        pretokenized.normalize(|normalized| {
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
            Ok(())
        })
    }
}

/// As a `Decoder`, `ByteLevel` is in charge of converting any byte-level
/// characters to their unicode counterpart, before merging everything back
/// into a single String. This decoder will consume the tokens and merge them
/// in one step to alleviate the fact that single token decoded might be a
/// byte not representable as a String.
impl Decoder for ByteLevel {
    fn decode_chain(&self, tokens: Vec<String>) -> Result<Vec<String>> {
        // ...
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pre_tokenization() {
        let bytelevel = ByteLevel::default().add_prefix_space(false);
        let mut pretokenized: PreTokenizedString =
            "Hello my friend, how is your day going?".into();
        bytelevel.pre_tokenize(&mut pretokenized).unwrap();
        assert_eq!(
            pretokenized
                .get_splits(OffsetReferential::Original, OffsetType::Byte)
                .into_iter()
                .map(|(s, o, _)| (s, o))
                .collect::<Vec<_>>(),
            vec![
                ("Hello", (0, 5)),
                ("Ġmy", (5, 8)),
                ("Ġfriend", (8, 15)),
                (",", (15, 16)),
                ("Ġhow", (16, 20)),
                ("Ġis", (20, 23)),
                ("Ġyour", (23, 28)),
                ("Ġday", (28, 32)),
                ("Ġgoing", (32, 38)),
                ("?", (38, 39))
            ]
        );
    }

    #[test]
    fn handling_of_newlines() {
        let mut pretokenized =
            PreTokenizedString::from("Hello there\nHello there");
        let bytelevel = ByteLevel::default().add_prefix_space(false);
        bytelevel.pre_tokenize(&mut pretokenized).unwrap();
        assert_eq!(
            pretokenized
                .get_splits(OffsetReferential::Original, OffsetType::Byte)
                .into_iter()
                .map(|(s, o, _)| (s, o))
                .collect::<Vec<_>>(),
            vec![
                ("Hello", (0, 5)),
                ("Ġthere", (5, 11)),
                ("Ċ", (11, 12)),
                ("Hello", (12, 17)),
                ("Ġthere", (17, 23))
            ]
        );
    }

    #[test]
    fn decoding() {
        let bytelevel = ByteLevel::default().add_prefix_space(false);
        assert_eq!(
            bytelevel
                .decode_chain(
                    vec![
                        "Hello", "Ġmy", "Ġfriend", ",", "Ġhow",
                        "Ġis", "Ġyour", "Ġday", "Ġgoing", "?"
                    ]
                    .into_iter()
                    .map(|s| s.into())
                    .collect::<Vec<String>>()
                )
                .unwrap(),
            vec!["Hello my friend, how is your day going?"]
        );
    }

    #[test]
    fn decode_unknown_characters() {
        let byte_level = ByteLevel::default();
        assert_eq!(
            byte_level
                .decode_chain(vec![
                    "Hello".into(),
                    "Ġthere".into(),
                    "Ġdear".into(),
                    "Ġfriend!".into(),
                    "Ġ".into(),
                    "[PA D]".into()
                ])
                .unwrap(),
            vec!["Hello there dear friend! [PA D]"]
        );
    }

    #[test]
    fn offsets_when_char_split_up() {
        let input = "i⭢j";
        let mut pretokenized = PreTokenizedString::from(input);
        let bytelevel = ByteLevel::default().add_prefix_space(false);
        bytelevel.pre_tokenize(&mut pretokenized).unwrap();
        // "i⭢j" → ["i", "âŃ¢", "j"]
        // The 3-byte UTF-8 character ⭢ is split into 3 mapped chars
        assert_eq!(
            pretokenized
                .get_splits(OffsetReferential::Original, OffsetType::Byte)
                .into_iter()
                .map(|(s, o, _)| (s, o))
                .collect::<Vec<_>>(),
            vec![("i", (0, 1)), ("âŃ¢", (1, 4)), ("j", (4, 5))]
        );
    }
}
