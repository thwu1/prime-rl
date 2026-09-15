use serde::{Serialize, Deserialize};
use alloc::string::String;
use alloc::vec::Vec;

/// Root telemetry message envelope.
/// Variant order determines discriminant values used on the wire.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum Message {
    SensorReading {
        sensor_id: u16,
        timestamp: u32,
        values: Vec<f32>,
        status: Option<StatusCode>,
    },
    ConfigUpdate {
        param_id: u16,
        value: ConfigValue,
    },
    Heartbeat {
        uptime_ms: u64,
        free_mem: u32,
    },
    Alert {
        level: AlertLevel,
        source: String,
        code: u32,
    },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum StatusCode {
    Ok,
    Warning { code: u8 },
    Error { code: u16 },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum ConfigValue {
    Int { value: i32 },
    Float { value: f32 },
    Str { value: String },
    Bool { value: bool },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum AlertLevel {
    Info,
    Warn,
    Critical,
}
