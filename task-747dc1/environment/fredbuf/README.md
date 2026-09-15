# fredbuf — Persistent Text Buffer Library

A C++20 library providing a persistent (immutable) text buffer for text editor backends.

## Project Layout

- `docs/` — API specifications and design constraints
- `include/fredbuf/` — Public headers (to be implemented)
- `src/` — Source files (to be implemented)
- `test/test_main.cpp` — Smoke test binary (provided)

## Build

Create a `CMakeLists.txt` at this directory that produces:
- A static library target `fredbuf` (output: `libfredbuf.a`)
- An executable target `fredbuf_test` from `test/test_main.cpp`, linked against the library

```
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel
./fredbuf_test
```

Consult `docs/` for the complete API reference and behavioral requirements.
