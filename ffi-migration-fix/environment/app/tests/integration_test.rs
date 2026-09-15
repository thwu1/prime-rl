//
// Integration tests for the searchidx FFI library.
// Tests verify the FFI bridge layer AND the safe wrapper API.

use searchidx::ffi::{SearchIdxToken, SearchResult};
use searchidx::ffi::{searchidx_tokenize, searchidx_free_tokens};
use searchidx::wrapper::{SearchIndex, OwnedSearchResult, SearchError};
use std::ffi::{c_char, CStr, CString};
use std::mem;

// C functions (implemented in index.c, compiled via build.rs)
#[link(name = "searchidx_c")]
extern "C" {
    fn searchidx_index_document(text: *const c_char) -> u32;
    fn searchidx_search(query: *const c_char, result_count: *mut u32) -> *mut SearchResult;
    fn searchidx_free_results(results: *mut SearchResult);
    fn searchidx_reset_index();
}

// ==================== FFI Layout Tests ====================

#[test]
fn test_token_layout() {
    // Must match C: typedef struct { char text[128]; uint32_t position; } SearchIdxToken;
    assert_eq!(mem::size_of::<SearchIdxToken>(), 132, "SearchIdxToken size must be 132 bytes");
    unsafe {
        let token = mem::zeroed::<SearchIdxToken>();
        let base = &token as *const _ as usize;
        let text_off = &token.text as *const _ as usize - base;
        let pos_off = &token.position as *const _ as usize - base;
        assert_eq!(text_off, 0, "text field must be at offset 0");
        assert_eq!(pos_off, 128, "position field must be at offset 128");
    }
}

#[test]
fn test_result_layout() {
    // Must match C: typedef struct { uint32_t doc_id; float score; } SearchResult;
    assert_eq!(mem::size_of::<SearchResult>(), 8, "SearchResult size must be 8 bytes");
    unsafe {
        let result = mem::zeroed::<SearchResult>();
        let base = &result as *const _ as usize;
        let docid_off = &result.doc_id as *const _ as usize - base;
        let score_off = &result.score as *const _ as usize - base;
        assert_eq!(docid_off, 0, "doc_id field must be at offset 0");
        assert_eq!(score_off, 4, "score field must be at offset 4");
    }
}

// ==================== FFI Tokenizer Tests ====================

#[test]
fn test_tokenize_basic() {
    let input = CString::new("Hello World").unwrap();
    let mut count: u32 = 0;
    unsafe {
        let tokens = searchidx_tokenize(input.as_ptr(), &mut count);
        assert!(!tokens.is_null(), "tokenize returned null for valid input");
        assert_eq!(count, 2, "expected 2 tokens");

        let t0 = &*tokens;
        let text0 = CStr::from_ptr(t0.text.as_ptr()).to_str().unwrap();
        assert_eq!(text0, "hello");
        assert_eq!(t0.position, 0);

        let t1 = &*tokens.add(1);
        let text1 = CStr::from_ptr(t1.text.as_ptr()).to_str().unwrap();
        assert_eq!(text1, "world");
        assert_eq!(t1.position, 1);

        searchidx_free_tokens(tokens, count);
    }
}

#[test]
fn test_tokenize_with_punctuation() {
    let input = CString::new("Hello, World! How's it going?").unwrap();
    let mut count: u32 = 0;
    unsafe {
        let tokens = searchidx_tokenize(input.as_ptr(), &mut count);
        assert!(!tokens.is_null());
        assert_eq!(count, 5);

        let t0 = &*tokens;
        let text0 = CStr::from_ptr(t0.text.as_ptr()).to_str().unwrap();
        assert_eq!(text0, "hello");

        let t4 = &*tokens.add(4);
        let text4 = CStr::from_ptr(t4.text.as_ptr()).to_str().unwrap();
        assert_eq!(text4, "going");

        searchidx_free_tokens(tokens, count);
    }
}

#[test]
fn test_tokenize_empty() {
    let input = CString::new("").unwrap();
    let mut count: u32 = 0;
    unsafe {
        let tokens = searchidx_tokenize(input.as_ptr(), &mut count);
        assert!(tokens.is_null());
        assert_eq!(count, 0);
    }
}

#[test]
fn test_tokenize_null_input() {
    let mut count: u32 = 0;
    unsafe {
        let tokens = searchidx_tokenize(std::ptr::null(), &mut count);
        assert!(tokens.is_null(), "null input should return null");
        assert_eq!(count, 0, "null input should set count to 0");
    }
}

// ==================== Direct C Index Tests ====================

#[test]
fn test_index_single_document() {
    unsafe {
        searchidx_reset_index();

        let doc = CString::new("the quick brown fox").unwrap();
        let doc_id = searchidx_index_document(doc.as_ptr());
        assert!(doc_id > 0, "document ID should be positive");
    }
}

#[test]
fn test_search_single_term() {
    unsafe {
        searchidx_reset_index();

        let doc1 = CString::new("the quick brown fox").unwrap();
        let doc2 = CString::new("the lazy brown dog").unwrap();

        let id1 = searchidx_index_document(doc1.as_ptr());
        let id2 = searchidx_index_document(doc2.as_ptr());

        let query = CString::new("brown").unwrap();
        let mut result_count: u32 = 0;
        let results = searchidx_search(query.as_ptr(), &mut result_count);

        assert_eq!(result_count, 2, "expected 2 results for 'brown'");
        assert!(!results.is_null());

        let r0 = &*results;
        let r1 = &*results.add(1);

        let mut doc_ids = vec![r0.doc_id, r1.doc_id];
        doc_ids.sort();
        assert_eq!(doc_ids, vec![id1, id2], "both documents should match");

        assert!(r0.score > 0.0, "score should be positive");
        assert!(r1.score > 0.0, "score should be positive");

        searchidx_free_results(results);
    }
}

#[test]
fn test_search_no_match() {
    unsafe {
        searchidx_reset_index();

        let doc = CString::new("hello world").unwrap();
        searchidx_index_document(doc.as_ptr());

        let query = CString::new("nonexistent").unwrap();
        let mut result_count: u32 = 0;
        let results = searchidx_search(query.as_ptr(), &mut result_count);

        assert_eq!(result_count, 0, "no results expected");
        assert!(results.is_null(), "null expected for empty results");
    }
}

// ==================== Safe Wrapper API Tests ====================

#[test]
fn test_wrapper_index_and_search() {
    let index = SearchIndex::new();
    let id1 = index.index_document("the quick brown fox").unwrap();
    let id2 = index.index_document("the lazy brown dog").unwrap();
    assert!(id1 > 0);
    assert!(id2 > 0);
    assert_ne!(id1, id2);

    let results = index.search("brown").unwrap();
    assert_eq!(results.len(), 2);
    let mut doc_ids: Vec<u32> = results.iter().map(|r| r.doc_id).collect();
    doc_ids.sort();
    assert_eq!(doc_ids, vec![id1, id2]);
    for r in &results {
        assert!(r.score > 0.0);
    }
}

#[test]
fn test_wrapper_interior_null_error() {
    let index = SearchIndex::new();
    // Interior null in index_document must return error, not panic
    let result = index.index_document("hello\0world");
    assert!(result.is_err());
    match result.unwrap_err() {
        SearchError::InteriorNull(_) => {}
        other => panic!("expected InteriorNull, got {:?}", other),
    }

    // Interior null in search must also return error
    let result = index.search("hello\0world");
    assert!(result.is_err());
}

#[test]
fn test_wrapper_search_sorted_by_relevance() {
    let index = SearchIndex::new();
    // "rust" appears 3 times in doc 1, giving score 3.0
    let id1 = index.index_document("rust rust rust").unwrap();
    // "rust" appears 1 time in doc 2, giving score 1.0
    let id2 = index.index_document("rust programming").unwrap();

    let results = index.search_sorted("rust").unwrap();
    assert_eq!(results.len(), 2);
    // Higher score first
    assert_eq!(results[0].doc_id, id1, "doc with score 3.0 should come first");
    assert!(results[0].score > results[1].score, "results must be sorted descending by score");
    assert_eq!(results[1].doc_id, id2);
}

#[test]
fn test_wrapper_reset_clears_index() {
    let index = SearchIndex::new();
    index.index_document("hello world").unwrap();

    let results = index.search("hello").unwrap();
    assert_eq!(results.len(), 1);

    index.reset();

    let results = index.search("hello").unwrap();
    assert!(results.is_empty(), "index should be empty after reset");
}

#[test]
fn test_wrapper_empty_search_results() {
    let index = SearchIndex::new();
    index.index_document("hello world").unwrap();

    let results = index.search("nonexistent").unwrap();
    assert!(results.is_empty());
}

#[test]
fn test_wrapper_selective_search() {
    let index = SearchIndex::new();
    let id1 = index.index_document("rust systems programming").unwrap();
    let _id2 = index.index_document("python data science").unwrap();
    let id3 = index.index_document("rust and python together").unwrap();

    // Only docs containing "rust" should appear
    let results = index.search("rust").unwrap();
    assert_eq!(results.len(), 2);
    let mut ids: Vec<u32> = results.iter().map(|r| r.doc_id).collect();
    ids.sort();
    assert_eq!(ids, vec![id1, id3]);
}

#[test]
fn test_wrapper_multiple_unique_ids() {
    let index = SearchIndex::new();
    let id1 = index.index_document("first document").unwrap();
    let id2 = index.index_document("second document").unwrap();
    let id3 = index.index_document("third document").unwrap();

    assert!(id1 > 0);
    assert!(id2 > 0);
    assert!(id3 > 0);
    assert_ne!(id1, id2);
    assert_ne!(id2, id3);
    assert_ne!(id1, id3);
}
