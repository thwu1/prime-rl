/// Unique identifier for network packets.
pub struct PacketId(u64);

impl PacketId {
    pub fn new(id: u64) -> Self {
        PacketId(id)
    }

    pub fn value(&self) -> u64 {
        self.0
    }
}

#[cfg(feature = "serialize")]
pub mod serialize {
    use serde::{Deserialize, Serialize};

    #[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
    pub struct Envelope {
        pub id: u64,
        pub tag: u32,
        pub payload: Vec<u8>,
    }

    impl Envelope {
        pub fn new(id: u64, tag: u32, payload: Vec<u8>) -> Self {
            Self { id, tag, payload }
        }
    }

    /// Serialize an envelope to JSON.
    pub fn to_json(envelope: &Envelope) -> String {
        serde_json::to_string(envelope).unwrap()
    }

    /// Deserialize an envelope from JSON.
    pub fn from_json(s: &str) -> Envelope {
        serde_json::from_str(s).unwrap()
    }

    /// Encode an envelope into a byte buffer: id(8 LE) + tag(4 LE) + payload.
    pub fn encode(envelope: &Envelope) -> Vec<u8> {
        let mut buf = Vec::with_capacity(12 + envelope.payload.len());
        buf.extend_from_slice(&envelope.id.to_le_bytes());
        buf.extend_from_slice(&envelope.tag.to_le_bytes());
        buf.extend_from_slice(&envelope.payload);
        buf
    }

    /// Decode bytes back into an envelope.
    pub fn decode(data: &[u8]) -> Option<Envelope> {
        if data.len() < 12 {
            return None;
        }
        let id = u64::from_le_bytes(data[0..8].try_into().ok()?);
        let tag = u32::from_le_bytes(data[8..12].try_into().ok()?);
        let payload = data[12..].to_vec();
        Some(Envelope { id, tag, payload })
    }
}

#[cfg(feature = "hash")]
pub mod hash {
    /// FNV-1a 64-bit hash.
    pub fn fnv1a(data: &[u8]) -> u64 {
        let mut h: u64 = 0xcbf29ce484222325;
        for &b in data {
            h ^= b as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
        h
    }

    pub fn verify(data: &[u8], expected: u64) -> bool {
        fnv1a(data) == expected
    }
}

#[cfg(feature = "validate")]
pub mod validate {
    /// Validation configuration for protocol messages.
    #[derive(Debug, Clone)]
    pub struct ValidationConfig {
        pub max_payload_size: usize,
        pub require_nonzero_tag: bool,
        pub strict_mode: bool,
    }

    impl Default for ValidationConfig {
        fn default() -> Self {
            Self {
                max_payload_size: 65536,
                require_nonzero_tag: true,
                strict_mode: true,
            }
        }
    }

    /// Validate envelope fields against the given configuration.
    pub fn validate_envelope(
        id: u64,
        tag: u32,
        payload: &[u8],
        config: &ValidationConfig,
    ) -> Result<(), String> {
        if config.strict_mode && config.require_nonzero_tag && tag == 0 {
            return Err("tag must be nonzero in strict mode".into());
        }
        if payload.len() > config.max_payload_size {
            return Err(format!(
                "payload too large: {} > {}",
                payload.len(),
                config.max_payload_size
            ));
        }
        if config.strict_mode && id == 0 {
            return Err("id must be nonzero in strict mode".into());
        }
        Ok(())
    }
}

#[cfg(feature = "logging")]
pub mod logging {
    pub fn log_info(msg: &str) {
        log::info!("{}", msg);
    }

    pub fn log_error(msg: &str) {
        log::error!("{}", msg);
    }
}

/// Runtime feature introspection.
pub fn has_feature(name: &str) -> bool {
    match name {
        "serialize" => cfg!(feature = "serialize"),
        "hash" => cfg!(feature = "hash"),
        "validate" => cfg!(feature = "validate"),
        "logging" => cfg!(feature = "logging"),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_packet_id() {
        let id = PacketId::new(42);
        assert_eq!(id.value(), 42);
    }
}
