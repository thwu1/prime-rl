#!/usr/bin/env python3
"""
Write the complete fixed FFI bridge implementation for the Rust sorted set.

Also restores lib.rs to its original state to ensure the SortedSet struct
has the correct structure and trait implementations, in case a prior agent
run modified it.

This fixes all 7 bugs in the shipped ffi.rs:
1. Thread safety: wraps SortedSet in Mutex<SortedSet> via a Handle struct
2. ABI layout: corrects ZRangeResult field order to match C header (count, members, scores)
3. Memory ownership: uses CString::into_raw() instead of as_ptr() to prevent dangling pointers
4. API contract (score): writes score value through out_score pointer
5. Resource management: zset_range_free properly deallocates CStrings + boxed slices
6. API contract (foreach): forwards actual user_data to callback instead of null
7. Range logic: removes erroneous stop-1 in zset_range_by_rank
"""

# Restore lib.rs to its original state
LIB_CODE = r'''mod ffi;

use std::collections::BTreeMap;

#[derive(Clone)]
pub struct SortedSet {
    members: BTreeMap<String, f64>,
}

impl SortedSet {
    pub fn new() -> Self {
        SortedSet {
            members: BTreeMap::new(),
        }
    }

    /// Add or update a member. Returns true if newly added, false if updated.
    pub fn add(&mut self, member: &str, score: f64) -> bool {
        self.members.insert(member.to_string(), score).is_none()
    }

    /// Remove a member. Returns true if it existed.
    pub fn remove(&mut self, member: &str) -> bool {
        self.members.remove(member).is_some()
    }

    /// Get the score of a member.
    pub fn score(&self, member: &str) -> Option<f64> {
        self.members.get(member).copied()
    }

    /// Number of members.
    pub fn card(&self) -> usize {
        self.members.len()
    }

    /// Get entries sorted by (score ascending, member name ascending).
    pub fn sorted_entries(&self) -> Vec<(&str, f64)> {
        let mut entries: Vec<_> = self
            .members
            .iter()
            .map(|(k, &v)| (k.as_str(), v))
            .collect();
        entries.sort_by(|a, b| {
            a.1.partial_cmp(&b.1)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.0.cmp(b.0))
        });
        entries
    }

    /// Get 0-based rank of a member in score-ascending order.
    pub fn rank(&self, member: &str) -> Option<usize> {
        let entries = self.sorted_entries();
        entries.iter().position(|(k, _)| *k == member)
    }

    /// Get all entries with min <= score <= max, in ascending score order.
    pub fn range_by_score(&self, min: f64, max: f64) -> Vec<(String, f64)> {
        let entries = self.sorted_entries();
        entries
            .into_iter()
            .filter(|(_, score)| *score >= min && *score <= max)
            .map(|(k, v)| (k.to_string(), v))
            .collect()
    }

    /// Get entries at rank positions [start, stop] (inclusive on both ends).
    pub fn range_by_rank(&self, start: usize, stop: usize) -> Vec<(String, f64)> {
        let entries = self.sorted_entries();
        if start >= entries.len() {
            return vec![];
        }
        let end = std::cmp::min(stop + 1, entries.len());
        entries[start..end]
            .iter()
            .map(|(k, v)| (k.to_string(), *v))
            .collect()
    }
}
'''

FFI_CODE = r'''use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;
use std::sync::Mutex;

use crate::SortedSet;

/// Thread-safe handle wrapping the sorted set with a mutex.
struct Handle {
    inner: Mutex<SortedSet>,
}

/// Range query result with C-compatible layout.
/// Field order must match the C header: count, members, scores.
#[repr(C)]
pub struct ZRangeResult {
    pub count: usize,
    pub members: *mut *mut c_char,
    pub scores: *mut f64,
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn zset_new() -> *mut Handle {
    Box::into_raw(Box::new(Handle {
        inner: Mutex::new(SortedSet::new()),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn zset_free(zs: *mut Handle) {
    if !zs.is_null() {
        drop(Box::from_raw(zs));
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_clone(zs: *const Handle) -> *mut Handle {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    // Reconstruct by iterating all entries instead of relying on Clone trait,
    // to be robust against the agent removing #[derive(Clone)] from lib.rs
    let mut new_set = SortedSet::new();
    for (member, score) in guard.sorted_entries() {
        new_set.add(member, score);
    }
    drop(guard);
    Box::into_raw(Box::new(Handle {
        inner: Mutex::new(new_set),
    }))
}

// ---------------------------------------------------------------------------
// Mutating operations
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn zset_add(
    zs: *mut Handle,
    member: *const c_char,
    score: f64,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return -1;
    }
    let handle = &*zs;
    let mut guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };
    if guard.add(member, score) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_remove(
    zs: *mut Handle,
    member: *const c_char,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return -1;
    }
    let handle = &*zs;
    let mut guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };
    if guard.remove(member) {
        1
    } else {
        0
    }
}

// ---------------------------------------------------------------------------
// Read operations
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn zset_score(
    zs: *const Handle,
    member: *const c_char,
    out_score: *mut f64,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return 0;
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };
    match guard.score(member) {
        Some(score) => {
            if !out_score.is_null() {
                *out_score = score;
            }
            1
        }
        None => 0,
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_card(zs: *const Handle) -> usize {
    if zs.is_null() {
        return 0;
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    guard.card()
}

#[no_mangle]
pub unsafe extern "C" fn zset_rank(
    zs: *const Handle,
    member: *const c_char,
    out_rank: *mut usize,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return 0;
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };
    match guard.rank(member) {
        Some(rank) => {
            if !out_rank.is_null() {
                *out_rank = rank;
            }
            1
        }
        None => 0,
    }
}

// ---------------------------------------------------------------------------
// Range queries
// ---------------------------------------------------------------------------

unsafe fn build_range_result(entries: Vec<(String, f64)>) -> *mut ZRangeResult {
    let count = entries.len();

    if count == 0 {
        let result = Box::new(ZRangeResult {
            count: 0,
            members: ptr::null_mut(),
            scores: ptr::null_mut(),
        });
        return Box::into_raw(result);
    }

    let mut member_ptrs: Vec<*mut c_char> = Vec::with_capacity(count);
    let mut scores_vec: Vec<f64> = Vec::with_capacity(count);

    for (member, score) in &entries {
        let cs = CString::new(member.as_str()).unwrap();
        // into_raw transfers ownership — must be reclaimed with from_raw in free
        member_ptrs.push(cs.into_raw());
        scores_vec.push(*score);
    }

    let members_box = member_ptrs.into_boxed_slice();
    let members_ptr = Box::into_raw(members_box) as *mut *mut c_char;

    let scores_box = scores_vec.into_boxed_slice();
    let scores_ptr = Box::into_raw(scores_box) as *mut f64;

    let result = Box::new(ZRangeResult {
        count,
        members: members_ptr,
        scores: scores_ptr,
    });

    Box::into_raw(result)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_by_score(
    zs: *const Handle,
    min: f64,
    max: f64,
) -> *mut ZRangeResult {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let entries = guard.range_by_score(min, max);
    build_range_result(entries)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_by_rank(
    zs: *const Handle,
    start: usize,
    stop: usize,
) -> *mut ZRangeResult {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let entries = guard.range_by_rank(start, stop);
    build_range_result(entries)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_free(result: *mut ZRangeResult) {
    if result.is_null() {
        return;
    }
    let result = Box::from_raw(result);
    let count = result.count;
    if count > 0 {
        if !result.members.is_null() {
            for i in 0..count {
                let ptr = *result.members.add(i);
                if !ptr.is_null() {
                    // Reclaim CString allocated with into_raw
                    drop(CString::from_raw(ptr));
                }
            }
            // Reclaim the boxed slice of member pointers
            drop(Box::from_raw(
                std::ptr::slice_from_raw_parts_mut(result.members, count),
            ));
        }
        if !result.scores.is_null() {
            // Reclaim the boxed slice of scores
            drop(Box::from_raw(
                std::ptr::slice_from_raw_parts_mut(result.scores, count),
            ));
        }
    }
}

// ---------------------------------------------------------------------------
// Callback iteration
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn zset_foreach(
    zs: *const Handle,
    cb: Option<unsafe extern "C" fn(*const c_char, f64, *mut c_void) -> c_int>,
    user_data: *mut c_void,
) -> usize {
    if zs.is_null() {
        return 0;
    }
    let cb = match cb {
        Some(f) => f,
        None => return 0,
    };
    let handle = &*zs;
    let guard = match handle.inner.lock() {
        Ok(g) => g,
        Err(e) => e.into_inner(),
    };
    let entries = guard.sorted_entries();
    let mut visited: usize = 0;
    for (member, score) in entries {
        // Create a temporary CString for the callback
        let cs = match CString::new(member) {
            Ok(cs) => cs,
            Err(_) => break,
        };
        visited += 1;
        let ret = cb(cs.as_ptr(), score, user_data);
        if ret != 0 {
            break;
        }
    }
    visited
}
'''

with open("/app/rust-sortedset/src/lib.rs", "w") as f:
    f.write(LIB_CODE)
print("Restored lib.rs with correct structure")

with open("/app/rust-sortedset/src/ffi.rs", "w") as f:
    f.write(FFI_CODE)
print("Wrote complete fixed FFI bridge to /app/rust-sortedset/src/ffi.rs")
