//! Safe wrapper API for the searchidx library.
//!
//! This module should provide an idiomatic, safe Rust interface
//! over the mixed C/Rust FFI layer.

use std::ffi::CString;
use std::os::raw::c_char;
use crate::ffi::SearchResult;

extern "C" {
    fn searchidx_index_document(text: *const c_char) -> u32;
    fn searchidx_search(query: *const c_char, result_count: *mut u32) -> *mut SearchResult;
    fn searchidx_reset_index();
}

/// A search index backed by the C inverted index.
pub struct SearchIndex;

impl SearchIndex {
    pub fn new() -> Self {
        unsafe { searchidx_reset_index(); }
        SearchIndex
    }

    pub fn index_document(&self, text: &str) -> u32 {
        let c_text = CString::new(text).unwrap();
        unsafe { searchidx_index_document(c_text.as_ptr()) }
    }

    pub fn search(&self, query: &str) -> Vec<(u32, f32)> {
        let c_query = CString::new(query).unwrap();
        let mut count: u32 = 0;
        let ptr = unsafe { searchidx_search(c_query.as_ptr(), &mut count) };
        if ptr.is_null() {
            return Vec::new();
        }
        let mut results = Vec::new();
        for i in 0..count as usize {
            unsafe {
                let r = &*ptr.add(i);
                results.push((r.doc_id, r.score));
            }
        }
        // Deallocate the C result array through Rust's allocator
        unsafe {
            let slice = std::ptr::slice_from_raw_parts_mut(ptr, count as usize);
            drop(Box::from_raw(slice));
        }
        results
    }
}
