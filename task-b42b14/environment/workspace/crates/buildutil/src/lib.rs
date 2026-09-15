use foundation::serialize::{Envelope, encode};
use foundation::validate::{ValidationConfig, validate_envelope};

/// Generate a build-time header string from a crate name and version.
pub fn generate_header(name: &str, version: u32) -> String {
    let config = ValidationConfig::default();
    let env = Envelope::new(version as u64, 1, name.as_bytes().to_vec());
    validate_envelope(env.id, env.tag, &env.payload, &config).expect("invalid header envelope");
    let encoded = encode(&env);
    format!("Generated: {} bytes for {}", encoded.len(), name)
}

/// Return a string summarizing the default validation configuration.
pub fn validate_config_string() -> String {
    let config = ValidationConfig::default();
    format!(
        "strict={},max_payload={}",
        config.strict_mode, config.max_payload_size
    )
}
