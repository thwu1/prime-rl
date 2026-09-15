The project at `/app/` contains a C library for a memory pool allocator. The public API is declared in `/app/include/allocator.h` and the implementation stubs are in `/app/src/allocator.c`.

Implement all API functions and complete the Meson build configuration at `/app/meson.build` so that building the project produces a working `liballocator.so`.

The allocator must operate entirely within caller-provided memory regions — no calls to system allocation functions (`malloc`, `free`, `calloc`, `realloc`) are permitted inside the library.

A GNU linker version script is provided at `/app/allocator.map`. The Meson build must integrate it so that only the declared public API symbols are exported from the shared library.

The final library must run without errors under Valgrind.

Read the header files for the complete behavioral contract of each function.