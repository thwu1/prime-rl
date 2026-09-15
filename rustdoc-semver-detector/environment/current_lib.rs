#![allow(dead_code)]

// --- Functions ---

// BREAKING: parameter count changed (2 -> 3)
pub fn compute(x: i32, y: i32, z: i32) -> i32 {
    x + y + z
}

// BREAKING: function removed entirely
// pub fn removed_fn() -> bool { ... }

// Unchanged
pub fn stable_fn() -> &'static str {
    "hello"
}

// New function (not breaking)
pub fn new_fn() -> bool {
    true
}

// --- Structs ---

// BREAKING: new pub field added to exhaustive struct
pub struct Config {
    pub name: String,
    pub value: i32,
    pub timeout: u64,
}

// NOT breaking: field added to non-exhaustive struct
#[non_exhaustive]
pub struct Settings {
    pub debug: bool,
    pub verbose: bool,
}

// BREAKING: repr(C) removed
pub struct FfiPoint {
    pub x: f64,
    pub y: f64,
}

// NOT breaking: struct has private field, not externally constructible
pub struct PrivateFieldStruct {
    pub label: String,
    pub extra: bool,
    _internal: u32,
}

// BREAKING: public field 'payload' removed
pub struct Data {
    pub id: u64,
}

// --- Enums ---

// BREAKING: Blue variant removed (Yellow added, but that's fine)
pub enum Color {
    Red,
    Green,
    Yellow,
}

// NOT breaking: variant added to non-exhaustive enum
#[non_exhaustive]
pub enum LogLevel {
    Info,
    Warn,
    Error,
    Debug,
}

// --- Traits ---

// BREAKING: required method 'version' added (no default body)
pub trait Processor {
    fn process(&self) -> Vec<u8>;
    fn name(&self) -> &str;
    fn version(&self) -> u32;
}

// Unchanged
pub trait Formatter {
    fn format(&self, input: &str) -> String;
}

// --- Constants ---
// BREAKING: MAX_SIZE removed
pub const KEEP_CONST: &str = "keep";

// --- Modules ---
pub mod utils {
    pub fn helper() -> i32 {
        42
    }
}
