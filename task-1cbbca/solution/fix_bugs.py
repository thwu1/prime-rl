#!/usr/bin/env python3
"""
Fix 4 correctness bugs in the lock-free SPSC bipartite buffer.

Bug A (WriteAcquire): Missing capacity guard when read_idx == 0.
      Without it, writing N elements makes write_idx == N == 0 == read_idx,
      so a full buffer looks empty.
      Fix: subtract 1 from end_space when r == 0.

Bug B (WriteRelease): After a wrapped write (data placed at position 0),
      the code advances write_idx from the OLD position instead of from 0.
      Fix: store(count) instead of store(old_w + count).

Bug C (ReadAcquire): When the writer has wrapped (w < r), the readable
      span is computed as N - r (the physical tail) instead of inv - r
      (the valid tail up to the invalidation boundary).
      Fix: use inv - r.

Bug D (ReadAcquire): When readable == 0 (reader has reached the
      invalidation boundary), the code returns {nullptr, 0} as if the
      buffer were empty.  It should wrap the reader to position 0 and
      return the data the writer placed at the beginning.
      Fix: add wrap-to-beginning fallback.
"""

import os
import sys

HPP = "/app/include/bipartite_buf.hpp"

if not os.path.isfile(HPP):
    print(f"ERROR: {HPP} not found", file=sys.stderr)
    print("Files in /app:", file=sys.stderr)
    for root, dirs, files in os.walk("/app"):
        for f in files:
            print(f"  {os.path.join(root, f)}", file=sys.stderr)
    sys.exit(1)

with open(HPP, "r") as f:
    src = f.read()

# -- Bug A ------------------------------------------------------------------
# Insert capacity guard after "size_t end_space = N - w;"
old_a = "            size_t end_space = N - w;\n\n            if (count <= end_space) {"
new_a = (
    "            size_t end_space = N - w;\n"
    "            if (r == 0 && end_space > 0) end_space--;\n"
    "\n"
    "            if (count <= end_space) {"
)
assert old_a in src, "Bug A: pattern not found"
src = src.replace(old_a, new_a, 1)

# -- Bug B ------------------------------------------------------------------
# In WriteRelease's wrapped branch, replace old_w + count with just count.
old_b = (
    "        if (_write_wrapped) {\n"
    "            const size_t w = _write_idx.load(std::memory_order_relaxed);\n"
    "            _write_idx.store(w + count, std::memory_order_release);\n"
    "            _write_wrapped = false;"
)
new_b = (
    "        if (_write_wrapped) {\n"
    "            _write_idx.store(count, std::memory_order_release);\n"
    "            _write_wrapped = false;"
)
assert old_b in src, "Bug B: pattern not found"
src = src.replace(old_b, new_b, 1)

# -- Bug C ------------------------------------------------------------------
# Use invalidation index (inv) instead of buffer size (N) for readable span.
old_c = "            size_t readable = N - r;"
new_c = "            size_t readable = inv - r;"
assert old_c in src, "Bug C: pattern not found"
src = src.replace(old_c, new_c, 1)

# -- Bug D ------------------------------------------------------------------
# When readable == 0, wrap reader to position 0 instead of returning empty.
old_d = (
    "            if (readable == 0) {\n"
    "                return {nullptr, 0};\n"
    "            }"
)
new_d = (
    "            if (readable == 0) {\n"
    "                _read_idx.store(0, std::memory_order_release);\n"
    "                _invalidate_idx.store(N, std::memory_order_release);\n"
    "                if (w == 0) return {nullptr, 0};\n"
    "                _read_acquired_sz = w;\n"
    "                return {&_data[0], _read_acquired_sz};\n"
    "            }"
)
assert old_d in src, "Bug D: pattern not found"
src = src.replace(old_d, new_d, 1)

# -- Write back -------------------------------------------------------------
with open(HPP, "w") as f:
    f.write(src)

print("All 4 bugs fixed in bipartite_buf.hpp:")
print("  A: Added capacity guard when r == 0 (full/empty ambiguity)")
print("  B: Fixed write index after wrap (count, not old_w + count)")
print("  C: Use invalidation index for readable span (inv - r, not N - r)")
print("  D: Wrap reader to pos 0 at invalidation boundary")
