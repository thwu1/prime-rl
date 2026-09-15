#!/usr/bin/env python3
"""
Fix FFI bridge bugs and prepare lib.rs for the wrapper module.

Applies targeted corrections to:
  1. build.rs: missing include path for C header
  2. ffi.rs: SearchIdxToken struct field order mismatch with C header
  3. ffi.rs: SearchResult struct field order mismatch with C header
  4. ffi.rs: missing null pointer check in searchidx_tokenize
  5. ffi.rs: missing searchidx_free_tokens deallocation function
  6. lib.rs: missing pub mod wrapper declaration
"""

import re


def fix_build_rs():
    """Add missing .include('include') to build.rs so cc can find searchidx.h."""
    path = "/app/build.rs"
    with open(path) as f:
        content = f.read()

    if '.include("include")' in content:
        print("build.rs: include path already present, skipping")
        return

    content = content.replace(
        '.file("src/c/index.c")',
        '.file("src/c/index.c")\n        .include("include")',
    )

    with open(path, "w") as f:
        f.write(content)
    print("build.rs: added .include(\"include\")")


def fix_lib_rs():
    """Add missing pub mod wrapper to lib.rs."""
    path = "/app/src/lib.rs"
    with open(path) as f:
        content = f.read()

    if "pub mod wrapper" in content:
        print("lib.rs: pub mod wrapper already present, skipping")
        return

    content = content.rstrip() + "\npub mod wrapper;\n"

    with open(path, "w") as f:
        f.write(content)
    print("lib.rs: added pub mod wrapper")


def fix_ffi_rs():
    """Fix struct layouts, null pointer handling, and add free function."""
    path = "/app/src/ffi.rs"
    with open(path) as f:
        content = f.read()

    # Fix SearchIdxToken: ensure text comes before position (matching C header)
    content = re.sub(
        r"(#\[repr\(C\)\]\s*pub struct SearchIdxToken\s*\{)[^}]+(})",
        r"""\1
    pub text: [c_char; 128],
    pub position: u32,
\2""",
        content,
    )

    # Fix SearchResult: ensure doc_id comes before score (matching C header)
    content = re.sub(
        r"(#\[repr\(C\)\]\s*pub struct SearchResult\s*\{)[^}]+(})",
        r"""\1
    pub doc_id: u32,
    pub score: f32,
\2""",
        content,
    )

    # Fix null pointer check: add guard before CStr::from_ptr
    if "input.is_null()" not in content:
        content = content.replace(
            "let c_str = CStr::from_ptr(input);",
            """if input.is_null() {
        *token_count = 0;
        return ptr::null_mut();
    }
    let c_str = CStr::from_ptr(input);""",
        )
        print("ffi.rs: added null pointer check")

    # Add searchidx_free_tokens if missing
    if "fn searchidx_free_tokens" not in content:
        content += """
/// Free a token array previously allocated by `searchidx_tokenize`.
///
/// Reconstructs the `Box<[SearchIdxToken]>` from the raw pointer and count,
/// then drops it to release the memory back to Rust's allocator.
#[no_mangle]
pub unsafe extern "C" fn searchidx_free_tokens(tokens: *mut SearchIdxToken, count: u32) {
    if tokens.is_null() {
        return;
    }
    let slice = std::ptr::slice_from_raw_parts_mut(tokens, count as usize);
    let _ = Box::from_raw(slice);
}
"""
        print("ffi.rs: added searchidx_free_tokens function")

    with open(path, "w") as f:
        f.write(content)
    print("ffi.rs: all fixes applied")


if __name__ == "__main__":
    fix_build_rs()
    fix_lib_rs()
    fix_ffi_rs()
    print("\nAll fixes applied successfully.")
