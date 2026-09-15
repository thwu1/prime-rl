//! Protocol message types for embedded device communication.
//!
//! These types are serialized using the `postcard` crate
//! (https://crates.io/crates/postcard) with the postcard v1.x wire format,
//! and framed using COBS encoding (https://crates.io/crates/cobs).
//!
//! Frame layout on the wire (before COBS encoding):
//!   [key: 8 bytes, u64 little-endian] [seq_no: postcard-varint u32] [body: postcard-encoded]
//!
//! Frames are COBS-encoded and separated by 0x00 sentinel bytes.

use serde::{Serialize, Deserialize};

/// Temperature sensor reading from a sensor node.
///
/// RPC path: "sensor/temp"
/// Wire key (little-endian hex): 0be9259314da3be6
#[derive(Serialize, Deserialize, Debug)]
pub struct TempReading {
    pub sensor_id: u8,
    pub timestamp_ms: u32,
    pub celsius_x100: i16,
    pub valid: bool,
}

/// Motor control command issued to an actuator.
///
/// RPC path: "motor/set"
/// Wire key (little-endian hex): 5e3c66b2885fdaa8
#[derive(Serialize, Deserialize, Debug)]
pub struct MotorCommand {
    pub motor_id: u8,
    pub speed_rpm: i32,
    pub duration_ms: u32,
}

/// Device status report -- reported periodically by the firmware.
///
/// RPC path: "device/status"
/// Wire key: must be derived from path and canonical schema string
///           (see key derivation procedure in /app/protocol_notes.txt)
#[derive(Serialize, Deserialize, Debug)]
pub enum StatusReport {
    /// Device is idle, no active operations.
    Idle,
    /// Device is actively processing; payload is the current load metric.
    Active(u16),
    /// A fault condition has occurred.
    Fault {
        code: u16,
        description: String,
    },
    /// Sensor calibration offsets (x, y, z) in device-local coordinates.
    Calibrating(i16, i16, i16),
}

/// Batch of ADC sample values from a data acquisition channel.
///
/// RPC path: "data/batch"
/// Wire key: must be derived from path and canonical schema string
#[derive(Serialize, Deserialize, Debug)]
pub struct BatchSamples {
    pub batch_id: u16,
    pub channel: u8,
    pub samples: Vec<i16>,
}

/// Configuration key-value entry stored in device flash.
///
/// RPC path: "config/entry"
/// Wire key: must be derived from path and canonical schema string
#[derive(Serialize, Deserialize, Debug)]
pub struct ConfigEntry {
    pub key: String,
    pub value: Option<String>,
    pub priority: u8,
}

/// Diagnostic event from the system event log.
///
/// RPC path: "system/event"
/// Wire key: must be derived from path and canonical schema string
///
/// NOTE: The nested EventKind enum produces a complex canonical schema
/// string where enum variant boundaries and struct field boundaries share
/// the same comma delimiter. Correct derivation requires understanding
/// the variant-name casing convention described in protocol_notes.txt.
#[derive(Serialize, Deserialize, Debug)]
pub struct SystemEvent {
    pub timestamp_ms: u32,
    pub source_id: u8,
    pub event: EventKind,
}

/// System event type discriminator with mixed variant kinds.
///
/// This enum intentionally demonstrates all four serde variant kinds:
/// struct variant (Boot, MemoryWarning), newtype variant (Watchdog),
/// and unit variant (Shutdown).
#[derive(Serialize, Deserialize, Debug)]
pub enum EventKind {
    /// Firmware boot event with version and uptime.
    Boot {
        firmware_version: String,
        uptime_ms: u32,
    },
    /// Hardware watchdog reset counter.
    Watchdog(u16),
    /// Memory subsystem warning with allocator details.
    MemoryWarning {
        used_kb: u16,
        total_kb: u16,
        allocator: String,
    },
    /// Clean shutdown initiated.
    Shutdown,
}
