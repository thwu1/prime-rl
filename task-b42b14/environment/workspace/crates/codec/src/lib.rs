/// Compute a FNV-1a checksum over the given byte slice.
pub fn checksum(data: &[u8]) -> u64 {
    foundation::hash::fnv1a(data)
}

/// Verify a checksum matches the expected value.
pub fn verify_checksum(data: &[u8], expected: u64) -> bool {
    foundation::hash::verify(data, expected)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_checksum_deterministic() {
        let data = b"test data";
        assert_eq!(checksum(data), checksum(data));
    }

    #[test]
    fn test_checksum_different_inputs() {
        let a = b"hello";
        let b = b"world";
        assert_ne!(checksum(a), checksum(b));
    }

    #[test]
    fn test_verify() {
        let data = b"verify me";
        let hash = checksum(data);
        assert!(verify_checksum(data, hash));
        assert!(!verify_checksum(data, hash.wrapping_add(1)));
    }
}
