Build a high-performance compositor visibility and damage-tracking engine at `/app/`. The engine serves a CPU-bound desktop compositor: it must determine which rectangular screen regions each z-ordered window owns, track pixel-ownership changes between frames for incremental redraws, and process compositor commands via a text protocol — all without GPU acceleration.

The environment provides:
- `/app/invariants.md` — mathematical properties the engine must satisfy
- `/app/Makefile` — builds `libregion.so` from `region.c` (you design the C source and its internal API)
- `/app/protocol.md` — the compositor's stdin/stdout wire protocol
- `/app/scenarios/` — example compositor sessions

## Deliverables

- `/app/region.c` — C shared library implementing geometry and visible-region operations. You design the data structures, function signatures, and algorithms; the provided Makefile compiles `region.c` into `libregion.so`. Create a `/app/region.h` header if you wish.
- `/app/engine.py` — Python module that loads `/app/libregion.so` via ctypes and exports:
  - `rect_subtract(base, occluder)` — base and occluder are `(x, y, w, h)` tuples; returns a list of `(x, y, w, h)` remainder rectangles
  - `compute_visible_regions(screen_w, screen_h, windows)` — windows is a list of `(id, x, y, w, h, z)` tuples; returns a dict mapping each owner (integer window id or the string `"bg"`) to a list of `(x, y, w, h)` visible rectangles
  - `merge_regions(rects)` — takes a list of `(x, y, w, h)` tuples; returns a list with co-linear adjacent rectangles merged
  - `compute_dirty_regions(old_regions, new_regions, screen_w, screen_h)` — takes two region dicts (as returned by `compute_visible_regions`) plus screen dimensions; returns a list of `(x, y, w, h)` dirty rectangles
- `/app/compositor.py` — executable script reading commands from stdin, writing frame data to stdout per `/app/protocol.md`

The engine must handle 500 overlapping windows on a 3840 × 2160 screen within the performance budget enforced by the test suite. Geometry operations must be accelerated in compiled C. Naive algorithms that degrade superlinearly per window may not scale; the C library architecture must account for efficient spatial computation across hundreds of windows.

All correctness invariants, behavioral requirements, and performance targets are defined by the test suite and `/app/invariants.md`.