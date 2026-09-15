// Excerpted from the Hubris RTOS build system (build/xtask/src/dist.rs)
// This implements the memory allocator that produces the firmware image layout.
//
// Copyright Oxide Computer Company
// SPDX-License-Identifier: MPL-2.0

use std::collections::{BTreeMap, BTreeSet};
use std::ops::Range;

// ---------------------------------------------------------------------------
// Memory allocation
// ---------------------------------------------------------------------------

/// Allocates address space from all memory regions for the kernel and all tasks.
///
/// The allocation strategy is constrained by the ARMv7-M MPU (Memory Protection
/// Unit). Each MPU region must be:
///   - Power-of-two in size
///   - Naturally aligned (base address is a multiple of the region size)
///
/// In other words, all the addresses in a single region must have some number
/// of top bits the same, and any combination of bottom bits.
///
/// The method we're using here is essentially the "deallocate" side of a
/// power-of-two buddy allocator, only simplified because we're using it to
/// allocate a series of known sizes.
///
/// The kernel is always allocated first at the base of each memory region
/// (the bootloader requires kernel text to appear immediately after it in ROM,
/// and placing the kernel first in RAM has useful benefits for the debugger).
///
/// Tasks are then allocated in configuration order. Configuration loading
/// sorts tasks by priority (ascending priority number, i.e. highest urgency
/// first) with alphabetical tie-breaking on task name.
pub fn allocate_image(
    config: &Config,
    chip: &ChipConfig,
) -> Result<AllocationResult> {
    let mut result = AllocationResult::default();

    for (region_name, region_def) in &chip.memory {
        let mut pos = region_def.address;
        let region_end = pos + region_def.size;

        // --- Kernel allocation ---
        // The kernel's required size for this region is rounded up to the
        // next power of two. That rounded value is also used as alignment.
        if let Some(&kern_req) = config.kernel.requires.get(region_name) {
            let sz = kern_req.next_power_of_two();
            pos = align_up(pos, sz);
            result.regions.entry(region_name.clone())
                .or_default()
                .insert("kernel".to_string(), Region {
                    start: pos,
                    size: sz,
                });
            pos += sz;
        }

        // --- Task allocations ---
        // Tasks are processed in priority order (Config::tasks_in_priority_order
        // returns tasks sorted by ascending priority number, with alphabetical
        // tie-breaking). For each task, the max-sizes entry for this region
        // is rounded up to the next power of two. The position pointer is
        // then advanced to the next address aligned to that power of two,
        // and the task is placed there.
        for (task_name, task_config) in config.tasks_in_priority_order() {
            if let Some(&max_size) = task_config.max_sizes.get(region_name) {
                let sz = max_size.next_power_of_two();
                pos = align_up(pos, sz);

                if pos + sz > region_end {
                    result.overflows.insert(region_name.clone());
                    // Continue computing remaining allocations even on overflow,
                    // so that the full layout is available for diagnostics.
                }

                result.regions.entry(region_name.clone())
                    .or_default()
                    .insert(task_name.to_string(), Region {
                        start: pos,
                        size: sz,
                    });
                pos += sz;
            }
        }
    }

    Ok(result)
}

/// Round address up to the given power-of-two alignment.
#[inline]
fn align_up(addr: u32, alignment: u32) -> u32 {
    debug_assert!(alignment.is_power_of_two());
    (addr + alignment - 1) & !(alignment - 1)
}

pub struct Region {
    pub start: u32,
    pub size: u32,
}

#[derive(Default)]
pub struct AllocationResult {
    /// region_name -> entity_name -> Region
    pub regions: BTreeMap<String, BTreeMap<String, Region>>,
    /// Set of region names where allocation exceeded available capacity
    pub overflows: BTreeSet<String>,
}

// ---------------------------------------------------------------------------
// Configuration types (from config.rs)
// ---------------------------------------------------------------------------

pub struct Config {
    pub name: String,
    pub kernel: KernelConfig,
    pub tasks: BTreeMap<String, TaskConfig>,
    // ...
}

pub struct KernelConfig {
    /// Memory requirements by region name (e.g. "flash" -> 32768)
    pub requires: BTreeMap<String, u32>,
    // ...
}

pub struct TaskConfig {
    pub priority: u8,
    pub max_sizes: BTreeMap<String, u32>,
    pub uses: Vec<String>,           // peripheral names
    pub task_slots: Vec<String>,     // IPC dependencies on other tasks
    pub notifications: Vec<String>,  // notification bit names
    pub interrupts: BTreeMap<String, String>, // IRQ name -> notification name
    // ...
}

impl Config {
    /// Returns tasks sorted by (priority ASC, name ASC).
    /// Priority 0 is the highest urgency; larger numbers are lower urgency.
    pub fn tasks_in_priority_order(&self) -> Vec<(&str, &TaskConfig)> {
        let mut tasks: Vec<_> = self.tasks.iter()
            .map(|(name, cfg)| (name.as_str(), cfg))
            .collect();
        tasks.sort_by(|a, b| {
            a.1.priority.cmp(&b.1.priority)
                .then_with(|| a.0.cmp(&b.0))
        });
        tasks
    }
}
