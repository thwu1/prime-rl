`/app/` contains a hybrid C/Python KV cache block manager inspired by the PagedAttention algorithm for LLM serving. A C shared library (`blockpool.c`, `blockpool.h`) implements the low-level block pool with reference-counted allocation and per-block token storage. Python (`block_manager.py`) wraps it via `ctypes` and implements higher-level logic: block tables, prefix caching with content-addressed deduplication, GPU/CPU block swapping, copy-on-write for beam search, and LIFO preemption scheduling.

The implementation is broken across multiple layers — the build system, C code, FFI bindings, and Python logic all contain bugs. Three Python methods are left as unimplemented stubs. The full specification is at `/app/spec.md`.

Fix all issues so that `libblockpool.so` builds correctly, the C library is free of memory leaks, and the corrected implementation passes the test suite at `/tests/test_state.py`.

Do not change method signatures, the C API, or class structure.