//! Virtual Memory Area Manager
//!
//! Implement a Linux-compatible VMA manager following the semantics
//! described in the task instructions.

use std::fmt;

pub const PAGE_SIZE: u64 = 4096;
pub const MMAP_MIN_ADDR: u64 = 0x1000;
pub const MMAP_MAX_ADDR: u64 = 0x7FFFFFFFFFFF;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Protection {
    pub read: bool,
    pub write: bool,
    pub exec: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MapType {
    Private,
    Shared,
}

#[derive(Debug)]
pub enum VmaError {
    /// Address or length not page-aligned.
    InvalidAlignment,
    /// Length is zero or otherwise invalid.
    InvalidLength,
    /// No space found for the requested mapping.
    NoSpace,
    /// The range is not fully mapped (for mprotect).
    NotMapped,
}

impl fmt::Display for VmaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            VmaError::InvalidAlignment => write!(f, "invalid_alignment"),
            VmaError::InvalidLength => write!(f, "invalid_length"),
            VmaError::NoSpace => write!(f, "no_space"),
            VmaError::NotMapped => write!(f, "not_mapped"),
        }
    }
}

/// Describes a virtual memory area.
#[derive(Debug, Clone)]
pub struct VmaInfo {
    /// Start address (inclusive), page-aligned.
    pub start: u64,
    /// End address (exclusive), page-aligned.
    pub end: u64,
    /// Memory protection bits.
    pub prot: Protection,
    /// Mapping type.
    pub map_type: MapType,
}

/// The VMA manager.
///
/// Maintains a set of non-overlapping VMAs in the virtual address space
/// [MMAP_MIN_ADDR, MMAP_MAX_ADDR).
pub struct VmaManager {
    // TODO: define your internal state
}

impl VmaManager {
    /// Create a new, empty VMA manager.
    pub fn new() -> Self {
        todo!("Implement VmaManager::new")
    }

    /// Create a new mapping.
    ///
    /// If `fixed` is true, `addr` must be Some and page-aligned.
    /// The target range [addr, addr+len) is implicitly unmapped before mapping.
    ///
    /// If `fixed` is false, find the lowest gap that fits `len` bytes,
    /// starting from MMAP_MIN_ADDR (bottom-up allocation).
    ///
    /// After mapping, merge adjacent VMAs with identical attributes.
    ///
    /// Errors: InvalidAlignment, InvalidLength, NoSpace.
    pub fn mmap(
        &mut self,
        addr: Option<u64>,
        len: u64,
        prot: Protection,
        map_type: MapType,
        fixed: bool,
    ) -> Result<u64, VmaError> {
        todo!("Implement mmap")
    }

    /// Remove all mappings in [addr, addr+len).
    ///
    /// VMAs partially covered are split, retaining non-overlapping portions.
    /// Unmapping already-unmapped pages silently succeeds.
    ///
    /// Errors: InvalidAlignment, InvalidLength.
    pub fn munmap(&mut self, addr: u64, len: u64) -> Result<(), VmaError> {
        todo!("Implement munmap")
    }

    /// Change protection on [addr, addr+len).
    ///
    /// The entire range must be continuously mapped; return NotMapped if any
    /// page in the range is unmapped. VMAs partially covered are split.
    /// After updating, merge adjacent VMAs with identical attributes.
    ///
    /// Errors: InvalidAlignment, InvalidLength, NotMapped.
    pub fn mprotect(&mut self, addr: u64, len: u64, prot: Protection) -> Result<(), VmaError> {
        todo!("Implement mprotect")
    }

    /// Return the VMA containing `addr`, or None if unmapped.
    pub fn query(&self, addr: u64) -> Option<VmaInfo> {
        todo!("Implement query")
    }

    /// Return all VMAs sorted by start address.
    pub fn dump(&self) -> Vec<VmaInfo> {
        todo!("Implement dump")
    }
}
