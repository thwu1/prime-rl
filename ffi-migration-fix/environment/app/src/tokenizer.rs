/// A token extracted from text.
pub struct Token {
    pub text: String,
    pub position: u32,
}

/// Tokenize input text into lowercase alphanumeric tokens.
///
/// Splits on whitespace, lowercases each word, strips non-alphanumeric
/// characters, and filters out empty tokens.
pub fn tokenize(input: &str) -> Vec<Token> {
    input
        .split_whitespace()
        .enumerate()
        .map(|(pos, word)| {
            let normalized: String = word
                .to_lowercase()
                .chars()
                .filter(|c| c.is_alphanumeric())
                .collect();
            Token {
                text: normalized,
                position: pos as u32,
            }
        })
        .filter(|t| !t.text.is_empty())
        .collect()
}
