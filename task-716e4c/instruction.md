walloc is a memory allocator (`malloc`/`free`) written for WebAssembly targets. The original source is at `/app/walloc_original.c`. It relies on WebAssembly-specific primitives and cannot compile or run on a native Linux system.

Your task is to create `/app/walloc_native.c` — a native Linux port of walloc that implements the full API declared in `/app/walloc_native.h`. The port must faithfully preserve walloc's allocation behavior while adding lifecycle management (`walloc_init`/`walloc_destroy`), `walloc_realloc`, `walloc_calloc`, heap statistics (`walloc_get_stats`), and heap integrity checking (`walloc_validate_heap`).

Study the original source and the header file carefully — the header documents the expected semantics for each function, including edge cases. Your implementation must compile cleanly as a shared library:

```
gcc -shared -fPIC -O2 -I/app -o libwalloc.so walloc_native.c
```