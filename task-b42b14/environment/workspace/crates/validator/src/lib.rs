use foundation::validate::{ValidationConfig, validate_envelope};

/// High-level message validator wrapping foundation's validation logic.
pub struct MessageValidator {
    config: ValidationConfig,
}

impl MessageValidator {
    pub fn new() -> Self {
        Self {
            config: ValidationConfig::default(),
        }
    }

    pub fn strict() -> Self {
        let config = ValidationConfig {
            strict_mode: true,
            require_nonzero_tag: true,
            ..ValidationConfig::default()
        };
        Self { config }
    }

    pub fn validate(&self, id: u64, tag: u32, payload: &[u8]) -> Result<(), String> {
        validate_envelope(id, tag, payload, &self.config)
    }

    pub fn mode_string(&self) -> &'static str {
        if self.config.strict_mode {
            "strict"
        } else {
            "permissive"
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strict_rejects_zero_id() {
        let v = MessageValidator::strict();
        assert!(v.validate(0, 1, b"test").is_err());
    }

    #[test]
    fn test_strict_rejects_zero_tag() {
        let v = MessageValidator::strict();
        assert!(v.validate(1, 0, b"test").is_err());
    }

    #[test]
    fn test_strict_accepts_valid() {
        let v = MessageValidator::strict();
        assert!(v.validate(1, 1, b"test").is_ok());
    }

    #[test]
    fn test_mode_string() {
        assert_eq!(MessageValidator::strict().mode_string(), "strict");
        assert_eq!(MessageValidator::new().mode_string(), "strict");
    }
}
