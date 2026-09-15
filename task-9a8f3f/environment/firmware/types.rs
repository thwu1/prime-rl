//! Device protocol type definitions
//!
//! These types define the message schema used for serial communication
//! between sensor nodes and the gateway controller.

use serde::{Serialize, Deserialize};
use std::collections::BTreeMap;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Point {
    pub x: f32,
    pub y: f32,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum Color {
    Red,
    Green,
    Blue,
    Custom(u8, u8, u8),
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SensorReading {
    pub timestamp: u32,
    pub sensor_id: u16,
    pub value: f32,
    pub flags: u8,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum DeviceStatus {
    Idle,
    Active(u8),
    Error {
        code: u16,
        message: String,
    },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TelemetryPacket {
    pub sequence: u32,
    pub readings: Vec<SensorReading>,
    pub status: DeviceStatus,
    pub label: Option<String>,
    #[serde(with = "serde_bytes")]
    pub raw_data: Vec<u8>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub enum Command {
    Ping,
    SetConfig {
        interval_ms: u32,
        sensors: Vec<u16>,
        threshold: f64,
        label: Option<String>,
    },
    GetReadings(Vec<u16>),
    BatchUpdate(u32, Vec<Point>, bool),
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct MetadataMap {
    pub entries: BTreeMap<String, i32>,
    pub version: u16,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct NestedTuple(pub u8, pub u16, pub Option<bool>);
