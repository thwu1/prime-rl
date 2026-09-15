#!/usr/bin/env python3
"""
Fix the four bugs in /app/dbt_select.py by applying targeted patches.

Bug 1: @ operator traces ancestors of roots only instead of (roots | descendants).
Bug 2: Comma-separated selectors are unioned instead of intersected.
Bug 3: get_ancestors has an off-by-one error (starts BFS at depth 1 instead of 0).
Bug 4: Test nodes inherit tags from ALL parents instead of first parent only.
"""

with open("/app/dbt_select.py", "r") as f:
    code = f.read()

# Bug 1: @ operator must trace ancestors of (roots | all_desc), not just roots
old_at = (
    "        all_anc = set()\n"
    "        for r in roots:\n"
    "            all_anc |= get_ancestors(r, all_nodes)"
)
new_at = (
    "        combined = roots | all_desc\n"
    "        all_anc = set()\n"
    "        for n in combined:\n"
    "            all_anc |= get_ancestors(n, all_nodes)"
)
code = code.replace(old_at, new_at)

# Bug 2: Comma-separated parts must be intersected (&=), not unioned (|=)
code = code.replace(
    "            result |= part_result",
    "            result &= part_result",
)

# Bug 3: BFS in get_ancestors must start at depth 0, not 1
code = code.replace(
    "    frontier = [(node_id, 1)]",
    "    frontier = [(node_id, 0)]",
)

# Bug 4: Test tag inheritance from first parent only, not all parents
old_tag = (
    "        for parent_id in parents:\n"
    "            if parent_id in all_nodes:\n"
    '                tags |= set(all_nodes[parent_id].get("tags", []))'
)
new_tag = (
    "        if parents and parents[0] in all_nodes:\n"
    '            tags |= set(all_nodes[parents[0]].get("tags", []))'
)
code = code.replace(old_tag, new_tag)

with open("/app/dbt_select.py", "w") as f:
    f.write(code)

print("All 4 bugs fixed in /app/dbt_select.py")
