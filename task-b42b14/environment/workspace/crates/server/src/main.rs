mod build_info {
    include!(concat!(env!("OUT_DIR"), "/build_info.rs"));
}

fn main() {
    #[cfg(feature = "logging")]
    foundation::logging::log_info("Server starting");

    // Verify protocol magic matches runtime hash computation
    let runtime_magic = codec::checksum(b"server-protocol-v1");
    assert_eq!(
        runtime_magic,
        build_info::PROTOCOL_MAGIC,
        "protocol magic mismatch: runtime={:#018x} build={:#018x}",
        runtime_magic,
        build_info::PROTOCOL_MAGIC
    );
    println!("Protocol magic: {:#018x}", runtime_magic);

    // Envelope round-trip via binary encoding
    let envelope = foundation::serialize::Envelope::new(1, 42, vec![1, 2, 3, 4, 5]);
    let encoded = foundation::serialize::encode(&envelope);
    let decoded = foundation::serialize::decode(&encoded).expect("decode failed");
    assert_eq!(envelope, decoded);
    println!("Envelope OK");

    // Envelope round-trip via JSON
    let json = foundation::serialize::to_json(&envelope);
    let from_json = foundation::serialize::from_json(&json);
    assert_eq!(envelope, from_json);

    // Packet hash via codec
    let hash = codec::checksum(&encoded);
    println!("Packet hash: {hash}");

    // Validation
    let v = validator::MessageValidator::strict();
    v.validate(envelope.id, envelope.tag, &envelope.payload)
        .expect("validation failed");
    println!("Validation: {}", v.mode_string());

    // Transform round-trip with checksum wrapping
    let (wrap_hash, wrapped) = transform::wrap_with_checksum(&encoded);
    let (unwrap_hash, unwrapped) =
        transform::unwrap_with_checksum(&wrapped).expect("unwrap failed");
    assert_eq!(wrap_hash, unwrap_hash);
    assert_eq!(unwrapped, &encoded[..]);

    #[cfg(feature = "logging")]
    foundation::logging::log_info("Server finished");

    println!("All checks passed");
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_serialize_available() {
        assert!(foundation::has_feature("serialize"));
    }

    #[test]
    fn test_hash_available() {
        assert!(foundation::has_feature("hash"));
    }

    #[test]
    fn test_validate_available() {
        assert!(foundation::has_feature("validate"));
    }

    #[test]
    fn test_logging_propagated() {
        if cfg!(feature = "logging") {
            assert!(
                foundation::has_feature("logging"),
                "server logging feature is on but foundation logging is not"
            );
        }
    }

    #[test]
    fn test_roundtrip_binary() {
        let env = foundation::serialize::Envelope::new(1, 2, vec![3, 4, 5]);
        let encoded = foundation::serialize::encode(&env);
        let decoded = foundation::serialize::decode(&encoded).unwrap();
        assert_eq!(env, decoded);
    }

    #[test]
    fn test_roundtrip_json() {
        let env = foundation::serialize::Envelope::new(10, 20, vec![30, 40]);
        let json = foundation::serialize::to_json(&env);
        let back = foundation::serialize::from_json(&json);
        assert_eq!(env, back);
    }

    #[test]
    fn test_codec_checksum() {
        let data = b"hello world";
        let h = codec::checksum(data);
        assert_ne!(h, 0);
    }

    #[test]
    fn test_transform_roundtrip() {
        let data = b"test payload";
        let (hash, wrapped) = transform::wrap_with_checksum(data);
        let (hash2, unwrapped) = transform::unwrap_with_checksum(&wrapped).unwrap();
        assert_eq!(hash, hash2);
        assert_eq!(unwrapped, data);
    }

    #[test]
    fn test_validator_strict() {
        let v = validator::MessageValidator::strict();
        assert_eq!(v.mode_string(), "strict");
        assert!(v.validate(1, 1, b"ok").is_ok());
        assert!(v.validate(0, 1, b"bad").is_err());
    }
}
