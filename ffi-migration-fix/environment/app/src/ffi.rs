use std::ffi::{c_char, CStr};
use std::ptr;

use crate::tokenizer;

/// FFI-safe token type. Must match `SearchIdxToken` in searchidx.h.
#[repr(C)]
pub struct SearchIdxToken {
    pub position: u32,
    pub text: [c_char; 128],
}

/// FFI-safe search result. Must match `SearchResult` in searchidx.h.
#[repr(C)]
pub struct SearchResult {
    pub score: f32,
    pub doc_id: u32,
}

/// Tokenize input text, returning a heap-allocated array of tokens.
///
/// The caller is responsible for freeing the returned array.
#[no_mangle]
pub unsafe extern "C" fn searchidx_tokenize(
    input: *const c_char,
    token_count: *mut u32,
) -> *mut SearchIdxToken {
    let c_str = CStr::from_ptr(input);
    let input_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => {
            *token_count = 0;
            return ptr::null_mut();
        }
    };

    let tokens = tokenizer::tokenize(input_str);
    let count = tokens.len();

    if count == 0 {
        *token_count = 0;
        return ptr::null_mut();
    }

    let mut ffi_tokens: Vec<SearchIdxToken> = Vec::with_capacity(count);

    for token in &tokens {
        let mut ffi_token = SearchIdxToken {
            text: [0; 128],
            position: token.position,
        };

        let bytes = token.text.as_bytes();
        let copy_len = bytes.len().min(127);
        ptr::copy_nonoverlapping(
            bytes.as_ptr(),
            ffi_token.text.as_mut_ptr() as *mut u8,
            copy_len,
        );

        ffi_tokens.push(ffi_token);
    }

    *token_count = count as u32;

    let boxed_slice = ffi_tokens.into_boxed_slice();
    Box::into_raw(boxed_slice) as *mut SearchIdxToken
}
