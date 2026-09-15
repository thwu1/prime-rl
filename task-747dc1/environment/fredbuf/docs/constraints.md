# Design Constraints

## Persistence

The piece table must be **persistent** in the functional-programming sense:
every mutation (insert, erase) produces a logically new data structure.
Previous versions must remain valid and readable. This is what enables
the undo tree to store and revisit arbitrary historical states — each
history node holds a reference to its version of the buffer.

## Complexity

Insert and erase operations must execute in O(log k) time where k is the
number of pieces, not O(k). Naive approaches such as scanning or rebuilding
a flat list on every edit will not satisfy this. The internal data structure
used to organize pieces must maintain balance under arbitrary insert/erase
sequences.

## Memory

Since multiple historical versions may share structure, the implementation
must use a shared-ownership model for internal nodes so that unreferenced
structure is reclaimed automatically.

## Build Requirements

- C++20 standard required
- CMake minimum version 3.20
- The static library target must be named `fredbuf`
- The test executable target must be named `fredbuf_test`
- Source files under `src/`, public headers under `include/fredbuf/`
- `test/test_main.cpp` is provided and must not be modified
