#![allow(dead_code)]

// --- Functions ---
pub fn compute(x: i32, y: i32) -> i32 {
    x + y
}

pub fn removed_fn() -> bool {
    false
}

pub fn stable_fn() -> &'static str {
    "hello"
}

// --- Structs ---

/// Exhaustive struct with all-public fields (externally constructible).
pub struct Config {
    pub name: String,
    pub value: i32,
}

/// Non-exhaustive struct: adding fields is NOT a breaking change.
#[non_exhaustive]
pub struct Settings {
    pub debug: bool,
}

/// FFI-safe point type with repr(C).
#[repr(C)]
pub struct FfiPoint {
    pub x: f64,
    pub y: f64,
}

/// Struct with a private field: NOT externally constructible.
pub struct PrivateFieldStruct {
    pub label: String,
    _internal: u32,
}

/// Struct that will lose a public field.
pub struct Data {
    pub id: u64,
    pub payload: Vec<u8>,
}

// --- Enums ---

/// Exhaustive enum.
pub enum Color {
    Red,
    Green,
    Blue,
}

/// Non-exhaustive enum: adding variants is NOT a breaking change.
#[non_exhaustive]
pub enum LogLevel {
    Info,
    Warn,
    Error,
}

// --- Traits ---

pub trait Processor {
    fn process(&self) -> Vec<u8>;
    fn name(&self) -> &str;
}

pub trait Formatter {
    fn format(&self, input: &str) -> String;
}

// --- Constants ---
pub const MAX_SIZE: usize = 1024;
pub const KEEP_CONST: &str = "keep";

// --- Modules ---
pub mod utils {
    pub fn helper() -> i32 {
        42
    }
}
