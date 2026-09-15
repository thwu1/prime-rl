//! Safe wrapper API for the searchidx library.
//!
//! Provides an idiomatic, safe Rust interface over the mixed C/Rust FFI layer.
//! All unsafe FFI calls are encapsulated behind safe public methods.


use std::ffi::{CString, NulError, c_char};
use crate::ffi::SearchResult;

extern "C" {
    fn searchidx_index_document(text: *const c_char) -> u32;
    fn searchidx_search(query: *const c_char, result_count: *mut u32) -> *mut SearchResult;
    fn searchidx_free_results(results: *mut SearchResult);
    fn searchidx_reset_index();
}

/// Errors that can occur during search index operations.
#[derive(Debug)]
pub enum SearchError {
    /// The input string contains an interior null byte, making it
    /// incompatible with C string representation.
    InteriorNull(NulError),
}

impl std::fmt::Display for SearchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SearchError::InteriorNull(e) => write!(f, "interior null byte: {}", e),
        }
    }
}

impl std::error::Error for SearchError {}

impl From<NulError> for SearchError {
    fn from(e: NulError) -> Self {
        SearchError::InteriorNull(e)
    }
}

/// An owned copy of a search result, independent of C-allocated memory.
pub struct OwnedSearchResult {
    pub doc_id: u32,
    pub score: f32,
}

/// Safe wrapper around the C search index.
///
/// The underlying C library uses global mutable state. This wrapper provides
/// a safe interface that handles memory management, string encoding, and
/// error conversion at the FFI boundary.
pub struct SearchIndex;

impl SearchIndex {
    /// Create a new search index, resetting any existing state.
    pub fn new() -> Self {
        unsafe { searchidx_reset_index(); }
        SearchIndex
    }

    /// Index a document and return its unique document ID.
    ///
    /// Returns `Err(SearchError::InteriorNull)` if the text contains
    /// an embedded null byte.
    pub fn index_document(&self, text: &str) -> Result<u32, SearchError> {
        let c_text = CString::new(text)?;
        let doc_id = unsafe { searchidx_index_document(c_text.as_ptr()) };
        Ok(doc_id)
    }

    /// Search for documents matching the query.
    ///
    /// Returns owned copies of the results. The C-allocated result array
    /// is freed before returning to avoid memory leaks.
    pub fn search(&self, query: &str) -> Result<Vec<OwnedSearchResult>, SearchError> {
        let c_query = CString::new(query)?;
        let mut count: u32 = 0;
        let ptr = unsafe { searchidx_search(c_query.as_ptr(), &mut count) };

        if ptr.is_null() || count == 0 {
            if !ptr.is_null() {
                unsafe { searchidx_free_results(ptr); }
            }
            return Ok(Vec::new());
        }

        let mut results = Vec::with_capacity(count as usize);
        for i in 0..count as usize {
            unsafe {
                let r = &*ptr.add(i);
                results.push(OwnedSearchResult {
                    doc_id: r.doc_id,
                    score: r.score,
                });
            }
        }

        // Free the C-allocated result array now that we've copied the data
        unsafe { searchidx_free_results(ptr); }
        Ok(results)
    }

    /// Search and return results sorted by relevance (highest score first).
    pub fn search_sorted(&self, query: &str) -> Result<Vec<OwnedSearchResult>, SearchError> {
        let mut results = self.search(query)?;
        results.sort_by(|a, b| {
            b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal)
        });
        Ok(results)
    }

    /// Reset the index, clearing all indexed documents.
    pub fn reset(&self) {
        unsafe { searchidx_reset_index(); }
    }
}
