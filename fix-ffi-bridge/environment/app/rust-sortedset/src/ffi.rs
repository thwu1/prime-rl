use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;

use crate::SortedSet;

/// Range query result with C-compatible layout.
#[repr(C)]
pub struct ZRangeResult {
    pub members: *mut *mut c_char,
    pub count: usize,
    pub scores: *mut f64,
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

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
pub unsafe extern "C" fn zset_clone(zs: *const SortedSet) -> *mut SortedSet {
    if zs.is_null() {
        return ptr::null_mut();
    }
    let zs = &*zs;
    let mut new_set = SortedSet::new();
    for (member, score) in zs.sorted_entries() {
        new_set.add(member, score);
    }
    Box::into_raw(Box::new(new_set))
}

// ---------------------------------------------------------------------------
// Mutating operations
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Read operations
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn zset_score(
    zs: *const SortedSet,
    member: *const c_char,
    _out_score: *mut f64,
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
        Some(_) => 1,
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

// ---------------------------------------------------------------------------
// Range queries
// ---------------------------------------------------------------------------

unsafe fn build_range_result(entries: Vec<(String, f64)>) -> *mut ZRangeResult {
    let count = entries.len();

    if count == 0 {
        let result = Box::new(ZRangeResult {
            members: ptr::null_mut(),
            count: 0,
            scores: ptr::null_mut(),
        });
        return Box::into_raw(result);
    }

    let mut member_ptrs: Vec<*mut c_char> = Vec::with_capacity(count);
    let mut scores_vec: Vec<f64> = Vec::with_capacity(count);

    for (member, score) in &entries {
        let cs = CString::new(member.as_str()).unwrap();
        member_ptrs.push(cs.as_ptr() as *mut c_char);
        scores_vec.push(*score);
    }

    let members_box = member_ptrs.into_boxed_slice();
    let members_ptr = Box::into_raw(members_box) as *mut *mut c_char;

    let scores_box = scores_vec.into_boxed_slice();
    let scores_ptr = Box::into_raw(scores_box) as *mut f64;

    let result = Box::new(ZRangeResult {
        members: members_ptr,
        count,
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
    let entries = zs.range_by_rank(start, if stop > 0 { stop - 1 } else { 0 });
    build_range_result(entries)
}

#[no_mangle]
pub unsafe extern "C" fn zset_range_free(result: *mut ZRangeResult) {
    if result.is_null() {
        return;
    }
    drop(Box::from_raw(result));
}

// ---------------------------------------------------------------------------
// Callback iteration
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn zset_foreach(
    zs: *const SortedSet,
    cb: Option<unsafe extern "C" fn(*const c_char, f64, *mut c_void) -> c_int>,
    _user_data: *mut c_void,
) -> usize {
    if zs.is_null() {
        return 0;
    }
    let cb = match cb {
        Some(f) => f,
        None => return 0,
    };
    let zs = &*zs;
    let entries = zs.sorted_entries();
    let mut visited: usize = 0;
    for (member, score) in entries {
        let cs = match CString::new(member) {
            Ok(cs) => cs,
            Err(_) => break,
        };
        visited += 1;
        let ret = cb(cs.as_ptr(), score, ptr::null_mut());
        if ret != 0 {
            break;
        }
    }
    visited
}
