#![cfg_attr(not(feature = "std"), no_std)]

#[cfg(feature = "alloc")]
extern crate alloc;

pub mod types {
    #[derive(Debug, Clone, Copy)]
    pub struct SignalMessage {
        pub id: u64,
        pub priority: u8,
    }

    impl SignalMessage {
        pub const fn new(id: u64, priority: u8) -> Self {
            Self { id, priority }
        }
    }

    #[cfg(feature = "alloc")]
    pub fn batch_messages(count: usize) -> alloc::vec::Vec<SignalMessage> {
        (0..count as u64)
            .map(|i| SignalMessage::new(i, 0))
            .collect()
    }
}

#[cfg(feature = "std")]
pub mod io {
    use super::types::SignalMessage;

    pub fn write_message<W: std::io::Write>(
        w: &mut W,
        msg: &SignalMessage,
    ) -> std::io::Result<()> {
        writeln!(w, "{}:{}", msg.id, msg.priority)
    }

    pub fn read_messages(input: &str) -> Vec<SignalMessage> {
        input
            .lines()
            .filter_map(|line| {
                let mut parts = line.split(':');
                let id = parts.next()?.parse().ok()?;
                let priority = parts.next()?.parse().ok()?;
                Some(SignalMessage::new(id, priority))
            })
            .collect()
    }

    pub fn format_message(msg: &SignalMessage) -> String {
        format!("Signal[{}] priority={}", msg.id, msg.priority)
    }
}

#[cfg(feature = "serde-support")]
pub mod serialization {
    use super::types::SignalMessage;
    use serde::{Deserialize, Serialize};

    #[derive(Serialize, Deserialize, Debug)]
    pub struct WireMessage {
        pub id: u64,
        pub priority: u8,
    }

    impl From<SignalMessage> for WireMessage {
        fn from(msg: SignalMessage) -> Self {
            Self {
                id: msg.id,
                priority: msg.priority,
            }
        }
    }
}

#[cfg(feature = "test-utils")]
pub mod testing {
    use std::collections::HashMap;

    use super::types::SignalMessage;

    pub struct TestFixture {
        messages: HashMap<u64, SignalMessage>,
    }

    impl TestFixture {
        pub fn new() -> Self {
            Self {
                messages: HashMap::new(),
            }
        }

        pub fn add(&mut self, msg: SignalMessage) {
            self.messages.insert(msg.id, msg);
        }

        pub fn get(&self, id: u64) -> Option<&SignalMessage> {
            self.messages.get(&id)
        }

        pub fn count(&self) -> usize {
            self.messages.len()
        }
    }
}
