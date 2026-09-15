Implement a Linux-compatible virtual memory area (VMA) manager in the Rust project at `/app/`. The project includes type definitions and method stubs in `src/lib.rs` and a complete JSON I/O layer in `src/main.rs`. Complete the implementation in `src/lib.rs` and build with `cargo build --release` to produce the binary at `/app/target/release/vma_mgr`.

The manager simulates a user-space virtual address space from `0x1000` to `0x7FFFFFFFFFFF`. All addresses and lengths are page-aligned (4096 bytes). The system maintains a set of non-overlapping VMAs, each defined by `[start, end)`, protection bits (read/write/execute), and mapping type (private/shared).

Implement five operations with semantics matching the Linux kernel's `mm/mmap.c`:

**mmap**: Create a mapping. With `MAP_FIXED`, implicitly unmap the target range first, then map. Without, find the lowest gap that can accommodate the requested length (bottom-up allocation from `0x1000`).

**munmap**: Remove all mappings overlapping `[addr, addr+len)`. VMAs partially covered must be split, retaining the non-overlapping portions. Unmapping unmapped pages silently succeeds.

**mprotect**: Change protection on `[addr, addr+len)`. The entire range must be continuously mapped; return an error if any page is unmapped. VMAs partially covered must be split at range boundaries.

**query**: Return the VMA containing a given address, or null if unmapped.

**dump**: Return all VMAs sorted by start address.

**Critical invariant**: After every mutating operation (`mmap`, `mprotect`), adjacent VMAs with identical protection and mapping type must be coalesced into a single VMA. This includes three-way merges when a new mapping bridges two compatible neighbors. The Linux kernel's `vma_merge()` handles numerous edge cases around boundary alignment and attribute matching — your implementation must as well.

The JSON protocol is defined by `src/main.rs`; read it to understand the input/output format.