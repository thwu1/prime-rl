use signal_core::io;
use signal_core::types::SignalMessage;

pub struct FileStore {
    path: String,
}

impl FileStore {
    pub fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
        }
    }

    pub fn save(&self, msg: &SignalMessage) -> Result<(), std::io::Error> {
        let formatted = io::format_message(msg);
        std::fs::write(&self.path, formatted)
    }

    pub fn load(&self) -> Result<Vec<SignalMessage>, std::io::Error> {
        let content = std::fs::read_to_string(&self.path)?;
        Ok(io::read_messages(&content))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_roundtrip() {
        let path = "/tmp/signal_storage_test.txt";
        let store = FileStore::new(path);
        let msg = SignalMessage::new(99, 3);
        store.save(&msg).unwrap();
        let loaded = store.load().unwrap();
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded[0].id, 99);
        assert_eq!(loaded[0].priority, 3);
    }
}
