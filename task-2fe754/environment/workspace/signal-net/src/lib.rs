use signal_core::io;
use signal_core::serialization::WireMessage;
use signal_core::testing::TestFixture;
use signal_core::types::SignalMessage;

pub struct NetworkTransport {
    buffer: Vec<u8>,
}

impl NetworkTransport {
    pub fn new() -> Self {
        Self { buffer: Vec::new() }
    }

    pub fn send(&mut self, msg: &SignalMessage) -> Result<(), std::io::Error> {
        io::write_message(&mut self.buffer, msg)
    }

    pub fn serialize_message(msg: SignalMessage) -> String {
        let wire: WireMessage = msg.into();
        serde_json::to_string(&wire).unwrap_or_default()
    }
}

/// Validate that a batch of messages contains no duplicate IDs.
/// Uses TestFixture to track seen IDs.
pub fn validate_batch(msgs: &[SignalMessage]) -> bool {
    let mut fixture = TestFixture::new();
    for msg in msgs {
        fixture.add(*msg);
    }
    fixture.count() == msgs.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_send() {
        let mut transport = NetworkTransport::new();
        let msg = SignalMessage::new(1, 5);
        transport.send(&msg).unwrap();
        assert!(!transport.buffer.is_empty());
    }

    #[test]
    fn test_serialize() {
        let msg = SignalMessage::new(42, 7);
        let json = NetworkTransport::serialize_message(msg);
        assert!(json.contains("42"));
    }

    #[test]
    fn test_validate_batch_unique() {
        let msgs = vec![
            SignalMessage::new(1, 5),
            SignalMessage::new(2, 3),
            SignalMessage::new(3, 1),
        ];
        assert!(validate_batch(&msgs));
    }

    #[test]
    fn test_validate_batch_duplicates() {
        let msgs = vec![
            SignalMessage::new(1, 5),
            SignalMessage::new(1, 3),
        ];
        assert!(!validate_batch(&msgs));
    }
}
