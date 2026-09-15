use signal_core::io;
use signal_core::types::SignalMessage;

fn main() {
    let msg = SignalMessage::new(0, 0);
    let formatted = io::format_message(&msg);
    println!("cargo:rustc-env=DEFAULT_MSG_FMT={}", formatted);
    println!("cargo:rerun-if-changed=build.rs");
}
