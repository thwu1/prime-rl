
use std::collections::BTreeMap;
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
    InvalidAlignment,
    InvalidLength,
    NoSpace,
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

#[derive(Debug, Clone)]
pub struct VmaInfo {
    pub start: u64,
    pub end: u64,
    pub prot: Protection,
    pub map_type: MapType,
}

pub struct VmaManager {
    vmas: BTreeMap<u64, VmaInfo>,
}

impl VmaManager {
    pub fn new() -> Self {
        VmaManager {
            vmas: BTreeMap::new(),
        }
    }

    fn is_aligned(val: u64) -> bool {
        val % PAGE_SIZE == 0
    }

    fn validate_range(addr: u64, len: u64) -> Result<(), VmaError> {
        if len == 0 {
            return Err(VmaError::InvalidLength);
        }
        if !Self::is_aligned(addr) || !Self::is_aligned(len) {
            return Err(VmaError::InvalidAlignment);
        }
        Ok(())
    }

    /// Find the lowest gap that can hold `len` bytes (bottom-up).
    fn find_gap(&self, len: u64) -> Option<u64> {
        let mut candidate = MMAP_MIN_ADDR;
        for vma in self.vmas.values() {
            if candidate + len <= vma.start {
                return Some(candidate);
            }
            if vma.end > candidate {
                candidate = vma.end;
            }
        }
        if candidate + len <= MMAP_MAX_ADDR {
            Some(candidate)
        } else {
            None
        }
    }

    /// Remove all mappings in [addr, addr+len), splitting partially covered VMAs.
    fn unmap_range(&mut self, addr: u64, len: u64) {
        let end = addr + len;
        let mut to_remove = Vec::new();
        let mut to_add = Vec::new();

        for (&start, vma) in self.vmas.iter() {
            // No overlap
            if vma.end <= addr || start >= end {
                continue;
            }
            to_remove.push(start);

            // Keep prefix before the unmap range
            if start < addr {
                to_add.push(VmaInfo {
                    start,
                    end: addr,
                    prot: vma.prot,
                    map_type: vma.map_type,
                });
            }
            // Keep suffix after the unmap range
            if vma.end > end {
                to_add.push(VmaInfo {
                    start: end,
                    end: vma.end,
                    prot: vma.prot,
                    map_type: vma.map_type,
                });
            }
        }

        for key in to_remove {
            self.vmas.remove(&key);
        }
        for vma in to_add {
            self.vmas.insert(vma.start, vma);
        }
    }

    /// Merge all adjacent VMAs with identical (prot, map_type).
    fn merge_adjacent(&mut self) {
        let entries: Vec<VmaInfo> = self.vmas.values().cloned().collect();
        if entries.is_empty() {
            return;
        }
        self.vmas.clear();
        let mut merged: Vec<VmaInfo> = Vec::new();
        for vma in entries {
            if let Some(last) = merged.last_mut() {
                if last.end == vma.start
                    && last.prot == vma.prot
                    && last.map_type == vma.map_type
                {
                    last.end = vma.end;
                    continue;
                }
            }
            merged.push(vma);
        }
        for vma in merged {
            self.vmas.insert(vma.start, vma);
        }
    }

    /// Check that [addr, end) is fully and continuously mapped.
    fn is_fully_mapped(&self, addr: u64, end: u64) -> bool {
        let mut pos = addr;
        for vma in self.vmas.values() {
            if vma.end <= pos {
                continue;
            }
            if vma.start > pos {
                return false;
            }
            pos = vma.end;
            if pos >= end {
                return true;
            }
        }
        false
    }

    pub fn mmap(
        &mut self,
        addr: Option<u64>,
        len: u64,
        prot: Protection,
        map_type: MapType,
        fixed: bool,
    ) -> Result<u64, VmaError> {
        if len == 0 {
            return Err(VmaError::InvalidLength);
        }
        if !Self::is_aligned(len) {
            return Err(VmaError::InvalidAlignment);
        }

        let base = if fixed {
            let a = addr.ok_or(VmaError::InvalidAlignment)?;
            if !Self::is_aligned(a) {
                return Err(VmaError::InvalidAlignment);
            }
            if a < MMAP_MIN_ADDR || a.checked_add(len).map_or(true, |e| e > MMAP_MAX_ADDR) {
                return Err(VmaError::NoSpace);
            }
            // Implicitly unmap the target range
            self.unmap_range(a, len);
            a
        } else {
            self.find_gap(len).ok_or(VmaError::NoSpace)?
        };

        self.vmas.insert(
            base,
            VmaInfo {
                start: base,
                end: base + len,
                prot,
                map_type,
            },
        );
        self.merge_adjacent();
        Ok(base)
    }

    pub fn munmap(&mut self, addr: u64, len: u64) -> Result<(), VmaError> {
        Self::validate_range(addr, len)?;
        self.unmap_range(addr, len);
        Ok(())
    }

    pub fn mprotect(&mut self, addr: u64, len: u64, prot: Protection) -> Result<(), VmaError> {
        Self::validate_range(addr, len)?;
        let end = addr + len;

        if !self.is_fully_mapped(addr, end) {
            return Err(VmaError::NotMapped);
        }

        let mut to_remove = Vec::new();
        let mut to_add = Vec::new();

        for (&start, vma) in self.vmas.iter() {
            // Skip non-overlapping VMAs
            if vma.end <= addr || start >= end {
                continue;
            }
            to_remove.push(start);

            // Prefix: part before the mprotect range keeps original prot
            if start < addr {
                to_add.push(VmaInfo {
                    start,
                    end: addr,
                    prot: vma.prot,
                    map_type: vma.map_type,
                });
            }

            // Overlapping portion gets new protection
            let overlap_start = start.max(addr);
            let overlap_end = vma.end.min(end);
            to_add.push(VmaInfo {
                start: overlap_start,
                end: overlap_end,
                prot,
                map_type: vma.map_type,
            });

            // Suffix: part after the mprotect range keeps original prot
            if vma.end > end {
                to_add.push(VmaInfo {
                    start: end,
                    end: vma.end,
                    prot: vma.prot,
                    map_type: vma.map_type,
                });
            }
        }

        for key in to_remove {
            self.vmas.remove(&key);
        }
        for vma in to_add {
            self.vmas.insert(vma.start, vma);
        }
        self.merge_adjacent();
        Ok(())
    }

    pub fn query(&self, addr: u64) -> Option<VmaInfo> {
        for vma in self.vmas.values() {
            if vma.start <= addr && addr < vma.end {
                return Some(vma.clone());
            }
        }
        None
    }

    pub fn dump(&self) -> Vec<VmaInfo> {
        self.vmas.values().cloned().collect()
    }
}
