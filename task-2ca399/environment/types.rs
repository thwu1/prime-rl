//! Telemetry message definitions for the SN-3000 sensor node firmware.
//!
//! Messages are serialized with `postcard` v1.0 and framed using COBS
//! encoding (0x00 sentinel). A CRC32 integrity footer is appended to
//! each serialized message (as a little-endian u32) before COBS encoding.
//!
//! Outbound frames are stored in a `bbqueue`-style BipBuffer ring buffer
//! until the host drains them over the debug link.

use serde::{Serialize, Deserialize};

/// Primary telemetry message envelope.
/// Serialized as a postcard tagged enum (varint discriminant followed by
/// struct fields in declaration order).
#[derive(Serialize, Deserialize, Debug)]
pub enum TelemetryMessage {
    /// Periodic keepalive, emitted every 60 s.
    Heartbeat {
        /// Monotonic sequence counter.
        sequence: u32,
        /// Milliseconds since boot.
        uptime_ms: u64,
        /// CPU die temperature in degrees Celsius.
        cpu_temp_c: i16,
    },

    /// Raw ADC sensor acquisition batch.
    SensorData {
        /// ADC channel index (0-7).
        channel: u8,
        /// Acquisition timestamp in microseconds — uses fixed-width LE
        /// encoding to guarantee constant frame size for DMA alignment.
        #[serde(with = "postcard::fixint::le")]
        timestamp_us: u32,
        /// Signed 16-bit ADC samples.
        samples: Vec<i16>,
    },

    /// Diagnostic log entry forwarded from the on-device logger.
    DiagnosticLog {
        level: LogLevel,
        module_path: String,
        message: String,
        error_code: Option<u16>,
    },

    /// Acknowledgement of an over-the-air configuration change request.
    ConfigAck {
        request_id: u32,
        accepted: bool,
        effective_rate_hz: f32,
        active_channels: Vec<u8>,
    },
}

/// Log severity, ordered lowest to highest.
#[derive(Serialize, Deserialize, Debug, Clone, Copy)]
pub enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}
