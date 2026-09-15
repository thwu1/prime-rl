#!/usr/bin/env python3
"""Fix the three bugs in orchestrator.py by reading the file,
applying targeted patches, and writing the corrected version."""

with open("/app/orchestrator.py") as f:
    code = f.read()

# Bug 1: get_effective_tags inherits from ALL parents instead of first only.
# Cosmos's _should_include_node sets node.tags from node.depends_on[0] only.
old_tag_code = (
    '    if node.get("resource_type") == "test":\n'
    '        for parent_id in node.get("depends_on", {}).get("nodes", []):\n'
    '            if parent_id in all_nodes:\n'
    '                tags |= set(all_nodes[parent_id].get("tags", []))'
)
new_tag_code = (
    '    if node.get("resource_type") == "test":\n'
    '        parents = node.get("depends_on", {}).get("nodes", [])\n'
    '        if parents and parents[0] in all_nodes:\n'
    '            tags |= set(all_nodes[parents[0]].get("tags", []))'
)
code = code.replace(old_tag_code, new_tag_code)

# Bug 2: @ operator computes ancestors of roots only instead of
# ancestors of (roots | descendants). Cosmos's _select_nodes does:
#   descendants = set(); for root: get descendants
#   for node in root_nodes | descendants: get ancestors
old_at_code = (
    '        all_anc = set()\n'
    '        for n in roots:\n'
    '            all_anc |= get_ancestors(n, all_nodes)'
)
new_at_code = (
    '        all_anc = set()\n'
    '        for n in roots | all_desc:\n'
    '            all_anc |= get_ancestors(n, all_nodes)'
)
code = code.replace(old_at_code, new_at_code)

# Bug 3: Barrier mode iterates children of the test node (uid) instead
# of children of the test's first parent. Tests have no children, so
# barrier has no effect. Should iterate children_index.get(first_parent).
old_barrier = '                        for child_uid in children_index.get(uid, []):'
new_barrier = '                        for child_uid in children_index.get(first_parent, []):'
code = code.replace(old_barrier, new_barrier)

with open("/app/orchestrator.py", "w") as f:
    f.write(code)

print("Orchestrator bugs fixed.")
