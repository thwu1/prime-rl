use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TempReading {
    pub sensor_id: u8,
    pub timestamp_ms: u32,
    pub celsius_x100: i16,
    pub valid: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct MotorCommand {
    pub motor_id: u8,
    pub speed_rpm: i32,
    pub duration_ms: u32,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum StatusReport {
    Idle,
    Active(u16),
    Fault {
        code: u16,
        description: String,
    },
    Calibrating(i16, i16, i16),
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct BatchSamples {
    pub batch_id: u16,
    pub channel: u8,
    pub samples: Vec<i16>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ConfigEntry {
    pub key: String,
    pub value: Option<String>,
    pub priority: u8,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SystemEvent {
    pub timestamp_ms: u32,
    pub source_id: u8,
    pub event: EventKind,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum EventKind {
    Boot {
        firmware_version: String,
        uptime_ms: u32,
    },
    Watchdog(u16),
    MemoryWarning {
        used_kb: u16,
        total_kb: u16,
        allocator: String,
    },
    Shutdown,
}
