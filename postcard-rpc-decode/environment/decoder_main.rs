mod types;

use std::fs;
use types::*;

fn main() {
    let data = fs::read("/app/capture.bin").expect("Failed to read capture.bin");

    // Split the binary stream on 0x00 sentinel bytes to get COBS-encoded frames.
    // Each frame must be COBS-decoded, then the 8-byte LE key and varint seq_no
    // header parsed, followed by postcard deserialization of the message body.
    //
    // Use postcard::from_bytes::<T>() for deserialization and
    // postcard::to_vec::<T>() for re-encoding to verify round-trip correctness.
    //
    // Dispatch decoded body bytes by key to the appropriate message type:
    //   TempReading, MotorCommand, StatusReport, BatchSamples,
    //   ConfigEntry, SystemEvent
    //
    // Output each decoded frame as a JSON line to stdout:
    //   {"type": "TempReading", "seq_no": 1, "data": {...}}
    //
    // Output errors for invalid frames:
    //   {"type": "error", "frame_index": N, "error": "description"}

    eprintln!("Decoder not yet implemented -- complete src/main.rs");
    std::process::exit(1);
}
