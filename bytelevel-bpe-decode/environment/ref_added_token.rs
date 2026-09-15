// Excerpted from huggingface/tokenizers — tokenizer-core/src/tokenizer/added_vocabulary.rs
//
// Defines the AddedToken type and its role in the tokenizer pipeline.

use serde::{Deserialize, Serialize};

/// Represent a token added by the user on top of the existing Model vocabulary.
/// AddedToken can be configured to specify the behavior they should have in
/// various situations like:
///   - Whether they should only match single words
///   - Whether to include any whitespace on its left or right
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AddedToken {
    /// The content of the added token (original, as provided by the user)
    pub content: String,
    /// Whether this token must be a single word or can break words
    pub single_word: bool,
    /// Whether this token should strip whitespaces on its left
    pub lstrip: bool,
    /// Whether this token should strip whitespaces on its right
    pub rstrip: bool,
    /// Whether this token should be normalized
    pub normalized: bool,
    /// Whether this token is special
    pub special: bool,
}

impl AddedToken {
    /// Build this token from the given content, specifying if it is intended
    /// to be a special token. Special tokens are not normalized by default.
    pub fn from<S: Into<String>>(content: S, special: bool) -> Self {
        Self {
            content: content.into(),
            normalized: !special,
            special,
            ..Default::default()
        }
    }

    /// Specify whether this token should be normalized and match against its
    /// normalized version in the input text.
    #[must_use]
    pub fn normalized(mut self, normalized: bool) -> Self {
        self.normalized = normalized;
        self
    }

    /// Specify whether this token is special, meaning if it should be skipped
    /// when decoding
    #[must_use]
    pub fn special(mut self, special: bool) -> Self {
        self.special = special;
        self
    }
}

impl Default for AddedToken {
    fn default() -> Self {
        Self {
            content: String::new(),
            single_word: false,
            lstrip: false,
            rstrip: false,
            normalized: true,
            special: false,
        }
    }
}
