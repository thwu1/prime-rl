#!/usr/bin/env python3
"""
Fix all five FFI bridge bugs in ffi.rs:

1. ZRangeResult struct field order: must match C header (count, members, scores)
2. CString dangling pointer: use into_raw() instead of as_ptr()
3. zset_range_free: implement actual memory deallocation
4. zset_score: write the score value to the out_score pointer
5. zset_range_by_rank: pass stop directly (no off-by-one subtraction)
"""

FIXED_FFI = r'''use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::ptr;

use crate::SortedSet;

#[repr(C)]
pub struct ZRangeResult {
    pub count: usize,
    pub members: *mut *mut c_char,
    pub scores: *mut f64,
}

#[no_mangle]
pub extern "C" fn zset_new() -> *mut SortedSet {
    Box::into_raw(Box::new(SortedSet::new()))
}

#[no_mangle]
pub unsafe extern "C" fn zset_free(zs: *mut SortedSet) {
    if !zs.is_null() {
        drop(Box::from_raw(zs));
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_add(
    zs: *mut SortedSet,
    member: *const c_char,
    score: f64,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return -1;
    }
    let zs = &mut *zs;
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };
    if zs.add(member, score) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_remove(
    zs: *mut SortedSet,
    member: *const c_char,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return -1;
    }
    let zs = &mut *zs;
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };
    if zs.remove(member) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn zset_score(
    zs: *const SortedSet,
    member: *const c_char,
    out_score: *mut f64,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return 0;
    }
    let zs = &*zs;
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };
    match zs.score(member) {
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
pub unsafe extern "C" fn zset_card(zs: *const SortedSet) -> usize {
    if zs.is_null() {
        return 0;
    }
    (&*zs).card()
}

#[no_mangle]
pub unsafe extern "C" fn zset_rank(
    zs: *const SortedSet,
    member: *const c_char,
    out_rank: *mut usize,
) -> i32 {
    if zs.is_null() || member.is_null() {
        return 0;
    }
    let zs = &*zs;
    let member = match CStr::from_ptr(member).to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };
    match zs.rank(member) {
        Some(rank) => {
            if !out_rank.is_null() {
                *out_rank = rank;
            }
            1
        }
        None => 0,
    }
}

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
        member_ptrs.push(cs.into_raw());
        scores_vec.push(*score);
    }

    let members_box = member_ptrs.into_boxed_slice();
    let members_raw = Box::into_raw(members_box);
    let members_ptr = members_raw as *mut *mut c_char;

    let scores_box = scores_vec.into_boxed_slice();
    let scores_raw = Box::into_raw(scores_box);
    let scores_ptr = scores_raw as *mut f64;

    let result = Box::new(ZRangeResult {
        count,
        members: members_ptr,
        scores: scores_ptr,
    });

    Box::into_raw(result)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_by_score(
    zs: *const SortedSet,
    min: f64,
    max: f64,
) -> *mut ZRangeResult {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let zs = &*zs;
    let entries = zs.range_by_score(min, max);
    build_range_result(entries)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_by_rank(
    zs: *const SortedSet,
    start: usize,
    stop: usize,
) -> *mut ZRangeResult {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let zs = &*zs;
    let entries = zs.range_by_rank(start, stop);
    build_range_result(entries)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_free(result: *mut ZRangeResult) {
    if result.is_null() {
        return;
    }
    let result = Box::from_raw(result);
    let count = result.count;
    let members = result.members;
    let scores = result.scores;
    if count > 0 {
        if !members.is_null() {
            for i in 0..count {
                let ptr = *members.add(i);
                if !ptr.is_null() {
                    drop(CString::from_raw(ptr));
                }
            }
            drop(Box::from_raw(
                std::ptr::slice_from_raw_parts_mut(members, count),
            ));
        }
        if !scores.is_null() {
            drop(Box::from_raw(
                std::ptr::slice_from_raw_parts_mut(scores, count),
            ));
        }
    }
}
'''

with open("/app/rust-sortedset/src/ffi.rs", "w") as f:
    f.write(FIXED_FFI)

print("Fixed all 5 FFI bridge bugs in ffi.rs")
