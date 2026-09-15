/// Wrap data with a checksum prefix: [hash:8 LE] ++ [data].
pub fn wrap_with_checksum(data: &[u8]) -> (u64, Vec<u8>) {
    let hash = codec::checksum(data);
    let mut out = Vec::with_capacity(8 + data.len());
    out.extend_from_slice(&hash.to_le_bytes());
    out.extend_from_slice(data);
    (hash, out)
}

/// Verify and unwrap checksummed data.
pub fn unwrap_with_checksum(data: &[u8]) -> Result<(u64, &[u8]), &'static str> {
    if data.len() < 8 {
        return Err("data too short for checksum");
    }
    let stored_hash = u64::from_le_bytes(data[0..8].try_into().unwrap());
    let payload = &data[8..];
    let computed = codec::checksum(payload);
    if stored_hash != computed {
        return Err("checksum mismatch");
    }
    Ok((stored_hash, payload))
}

#[cfg(feature = "json")]
pub mod json {
    use foundation::serialize::{Envelope, from_json, to_json};

    pub fn envelope_to_json(id: u64, tag: u32, payload: Vec<u8>) -> String {
        let env = Envelope::new(id, tag, payload);
        to_json(&env)
    }

    pub fn json_to_envelope(s: &str) -> Envelope {
        from_json(s)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_wrap_unwrap_roundtrip() {
        let data = b"hello world";
        let (hash, wrapped) = wrap_with_checksum(data);
        let (hash2, unwrapped) = unwrap_with_checksum(&wrapped).unwrap();
        assert_eq!(hash, hash2);
        assert_eq!(unwrapped, data);
    }

    #[test]
    fn test_checksum_mismatch() {
        let mut wrapped = vec![0u8; 16];
        wrapped[8..].copy_from_slice(b"testdata");
        assert!(unwrap_with_checksum(&wrapped).is_err());
    }
}
