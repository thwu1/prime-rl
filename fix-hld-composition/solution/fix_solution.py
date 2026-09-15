
"""
Fix the four bugs in /app/solution.cpp.

Bug 1 (Affine::after): The b-coefficient formula uses other.b instead of b (this->b).
  Wrong:   mod_val(mod_val(a * other.b) + other.b)
  Correct: mod_val(mod_val(a * other.b) + b)

Bug 2 (init mapping): Functions are placed at raw node index i instead of
  the HLD Euler tour position euler_pos[i].
  Wrong:   init[i] = Affine(a, b);
  Correct: init[tree.euler_pos[i]] = Affine(a, b);

Bug 3 (u-side query direction): When traversing upward from u to LCA, the
  code uses query_fwd (which composes in ancestor-to-descendant DFS order).
  Since we are going UP (descendant-to-ancestor), we need query_rev.
  Applies to both the chain-jump loop and the remaining segment.

Bug 4 (off-by-one in remaining u-side range): The remaining segment on the
  same chain as z should exclude z (handled separately as lca_fn). The range
  should start at euler_pos[z]+1, not euler_pos[z].
"""

import re
import sys
import os

source_path = "/app/solution.cpp"

if not os.path.exists(source_path):
    # Try backup location
    backup_path = "/opt/initial_app/solution.cpp"
    if os.path.exists(backup_path):
        import shutil
        shutil.copy2(backup_path, source_path)
    else:
        print(f"ERROR: Cannot find solution.cpp at {source_path} or {backup_path}", file=sys.stderr)
        sys.exit(1)

with open(source_path, "r") as f:
    code = f.read()

# Bug 1: Fix Affine::after() b-coefficient
code = code.replace(
    "mod_val(mod_val(a * other.b) + other.b)",
    "mod_val(mod_val(a * other.b) + b)",
)

# Bug 2: Fix initial function mapping to use euler_pos
code = code.replace(
    "init[i] = Affine(a, b);",
    "init[tree.euler_pos[i]] = Affine(a, b);",
)

# Bug 3 + Bug 4: Fix u-side chain-jump query to use query_rev
code = code.replace(
    "Affine seg_result = seg.query_fwd(euler_pos[head_node[cu]], euler_pos[cu]);",
    "Affine seg_result = seg.query_rev(euler_pos[head_node[cu]], euler_pos[cu]);",
    1,  # only the first occurrence (u-side chain jump)
)

# Bug 3 + Bug 4: Fix u-side remaining segment: query_rev and euler_pos[z]+1
code = code.replace(
    "Affine seg_result = seg.query_fwd(euler_pos[z], euler_pos[cu]);",
    "Affine seg_result = seg.query_rev(euler_pos[z] + 1, euler_pos[cu]);",
)

with open(source_path, "w") as f:
    f.write(code)

print("All four bugs fixed in solution.cpp")
