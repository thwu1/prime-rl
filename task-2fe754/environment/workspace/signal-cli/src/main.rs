use signal_core::io;
use signal_core::types::SignalMessage;
use signal_storage::FileStore;

fn main() {
    let msg = SignalMessage::new(42, 7);

    let formatted = io::format_message(&msg);
    println!("{}", formatted);

    let store = FileStore::new("/tmp/signals.txt");
    store.save(&msg).expect("failed to save");

    let loaded = store.load().expect("failed to load");
    println!("Loaded {} messages", loaded.len());
}
