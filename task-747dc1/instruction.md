A text editor project at `/app/fredbuf/` needs a C++20 library that provides a persistent (immutable) text buffer with branching undo and text diffing. The project directory contains specification documents, design constraints, and a smoke test that together define the required API and behavioral contracts. Explore its contents to understand the full requirements before implementing.

The library has three components:

1. A text buffer supporting insert and erase by character offset, where every mutation produces a new version without invalidating prior versions.

2. A branching undo/redo history that preserves old redo paths when editing after an undo, forming a tree of navigable edit states.

3. A line-level diff function between any two text snapshots, producing structured hunks.

The CMake build must produce a static library `libfredbuf.a` and a test executable `fredbuf_test` from the provided smoke test. All public headers belong under `include/fredbuf/`, implementations under `src/`.

The implementation must handle workloads of hundreds of sequential operations without quadratic time or space blowup.