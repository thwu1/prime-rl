"""Fix the ChunkwiseMask.k_full_range_for_q_tile range computation bug.

The bug: k_start uses q_block_min and k_end uses q_block_max. This gives
the UNION of per-query key ranges (too wide). For the fully-unmasked range,
we need the INTERSECTION:
  - k_start = largest lower bound across all queries = (q_block_max - bc) * cs
  - k_end = smallest upper bound across all queries = (q_block_min + 1) * cs

The fix: swap which block index is used for each bound.
"""

with open('/app/masks.py', 'r') as f:
    content = f.read()

# Replace the buggy lines in k_full_range_for_q_tile
old_k_start = 'k_start = max(0, (q_block_min - self.back_chunks) * self.chunk_size)'
new_k_start = 'k_start = max(0, (q_block_max - self.back_chunks) * self.chunk_size)'

old_k_end = 'k_end = min((q_block_max + 1) * self.chunk_size, seq_len)'
new_k_end = 'k_end = min((q_block_min + 1) * self.chunk_size, seq_len)'

assert old_k_start in content, f"Could not find buggy k_start line"
assert old_k_end in content, f"Could not find buggy k_end line"

content = content.replace(old_k_start, new_k_start)
content = content.replace(old_k_end, new_k_end)

with open('/app/masks.py', 'w') as f:
    f.write(content)

# Verify the fix
with open('/app/masks.py', 'r') as f:
    fixed = f.read()

assert new_k_start in fixed, "k_start fix not applied"
assert new_k_end in fixed, "k_end fix not applied"
assert old_k_start not in fixed, "old k_start still present"
assert old_k_end not in fixed, "old k_end still present"

print("Fixed masks.py: corrected ChunkwiseMask k_full_range_for_q_tile bounds")
