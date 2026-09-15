#!/usr/bin/env python3
"""Apply all fixes and produce the defect classification report.

"""

import json
import os
import shutil

# Ensure app files are present from staging backup
if not os.path.exists("/app/mapops.py"):
    for fname in os.listdir("/task_setup"):
        src = os.path.join("/task_setup", fname)
        dst = os.path.join("/app", fname)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    print("[0] Restored app files from /task_setup")

# ---- Fix 1: Create CrossHair plugin for OrderedSet and SortedMapping ----

PLUGIN_SOURCE = '''\
"""CrossHair plugin for symbolic analysis of OrderedSet and SortedMapping."""

from typing import List, Tuple

import crosshair
from orderedset import OrderedSet
from sortedmap import SortedMapping


def _make_symbolic_ordered_set(factory: crosshair.SymbolicFactory) -> OrderedSet:
    """Create a symbolic OrderedSet via its constructor (handles sort + dedup)."""
    elements = factory(List[int])
    return OrderedSet(elements)


def _make_symbolic_sorted_mapping(factory: crosshair.SymbolicFactory) -> SortedMapping:
    """Create a symbolic SortedMapping via its constructor (handles sort + dedup)."""
    pairs = factory(List[Tuple[int, int]])
    return SortedMapping(pairs)


crosshair.register_type(OrderedSet, _make_symbolic_ordered_set)
crosshair.register_type(SortedMapping, _make_symbolic_sorted_mapping)
'''

with open("/app/ch_plugin.py", "w") as f:
    f.write(PLUGIN_SOURCE)
print("[1] Created /app/ch_plugin.py with registrations for OrderedSet and SortedMapping")

# ---- Fixes 2-4: Fix setops.py ----

with open("/app/setops.py", "r") as f:
    content = f.read()

# Fix 2: intersect contract — == min is too strong, change to <= min
content = content.replace(
    "post: __return__.size() == min(s1.size(), s2.size())",
    "post: __return__.size() <= min(s1.size(), s2.size())",
)
print("[2] Fixed intersect contract: == min -> <= min")

# Fix 3: symmetric_difference — when equal elements found, advance both pointers
old_sym_diff = "        else:\n            i += 1\n    while i < len(list1):"
new_sym_diff = "        else:\n            i += 1\n            j += 1\n    while i < len(list1):"
content = content.replace(old_sym_diff, new_sym_diff)
print("[3] Fixed symmetric_difference: advance both pointers on equal elements")

# Fix 4: range_count — remove spurious + 1
content = content.replace(
    "return right - left + 1",
    "return right - left",
)
print("[4] Fixed range_count: removed off-by-one")

with open("/app/setops.py", "w") as f:
    f.write(content)

# ---- Fixes 5-10: Fix mapops.py ----

with open("/app/mapops.py", "r") as f:
    content = f.read()

# Fix 5: merge_mappings — replace instead of sum for duplicate keys
content = content.replace(
    "    for k, v in m2.items():\n        result.put(k, v)\n    return result",
    "    for k, v in m2.items():\n        existing = result.get(k)\n        if existing is not None:\n            result.put(k, existing + v)\n        else:\n            result.put(k, v)\n    return result",
)
print("[5] Fixed merge_mappings: sum values for duplicate keys instead of replacing")

# Fix 6: range_lookup contract — strict < to inclusive <=
content = content.replace(
    "post: all(__return__.contains_key(k) for k in m.keys() if lo < k < hi)",
    "post: all(__return__.contains_key(k) for k in m.keys() if lo <= k <= hi)",
)
print("[6] Fixed range_lookup completeness postcondition: strict to inclusive bounds")

# Fix 7: range_lookup implementation — bisect_left -> bisect_right for upper bound
content = content.replace(
    "right = bisect.bisect_left(m._keys, hi)",
    "right = bisect.bisect_right(m._keys, hi)",
)
print("[7] Fixed range_lookup implementation: bisect_left -> bisect_right for upper bound")

# Fix 8: sum_values_in_range — sums keys instead of values
content = content.replace(
    "total += m._keys[i]",
    "total += m._values[i]",
)
print("[8] Fixed sum_values_in_range: sum values, not keys")

# Fix 9: Add postconditions to keys_with_value_in
content = content.replace(
    '    """\n    Return the set of keys whose values are members of the given value set.\n\n    pre: True\n    """',
    '    """\n    Return the set of keys whose values are members of the given value set.\n\n    pre: True\n    post: all(m.contains_key(k) for k in __return__.to_list())\n    post: all(values.contains(m.get(k)) for k in __return__.to_list())\n    post: all(__return__.contains(k) for k in m.keys() if values.contains(m.get(k)))\n    """',
)
print("[9] Added postconditions to keys_with_value_in")

# Fix 10: Add postconditions to key_of_max_value
content = content.replace(
    '    """\n    Return the key with the largest value. For ties, return the smallest key.\n\n    pre: m.size() > 0\n    """',
    '    """\n    Return the key with the largest value. For ties, return the smallest key.\n\n    pre: m.size() > 0\n    post: m.contains_key(__return__)\n    post: all(m.get(k) <= m.get(__return__) for k in m.keys())\n    post: all(k >= __return__ for k in m.keys() if m.get(k) == m.get(__return__))\n    """',
)
print("[10] Added postconditions to key_of_max_value")

with open("/app/mapops.py", "w") as f:
    f.write(content)

# ---- Fix 11: Fix setops_v2.py ----

with open("/app/setops_v2.py", "r") as f:
    content = f.read()

content = content.replace(
    "if idx <= len(s2._data) and s2._data[idx] == val:",
    "if idx < len(s2._data) and s2._data[idx] == val:",
)

with open("/app/setops_v2.py", "w") as f:
    f.write(content)
print("[11] Fixed setops_v2 intersect: bounds check <= -> <")

# ---- Fix 12: Fix mapops_v2.py ----

with open("/app/mapops_v2.py", "r") as f:
    content = f.read()

content = content.replace(
    "while idx < len(m._keys) and m._keys[idx] < hi:",
    "while idx < len(m._keys) and m._keys[idx] <= hi:",
)

with open("/app/mapops_v2.py", "w") as f:
    f.write(content)
print("[12] Fixed mapops_v2 range_lookup: strict < -> <= for upper bound")

# ---- Produce defect classification report ----

defect_report = {
    "defects": [
        {
            "module": "setops",
            "function": "intersect",
            "category": "contract_error",
        },
        {
            "module": "setops",
            "function": "symmetric_difference",
            "category": "implementation_bug",
        },
        {
            "module": "setops",
            "function": "range_count",
            "category": "implementation_bug",
        },
        {
            "module": "mapops",
            "function": "merge_mappings",
            "category": "implementation_bug",
        },
        {
            "module": "mapops",
            "function": "range_lookup",
            "category": "weak_specification",
        },
        {
            "module": "mapops",
            "function": "range_lookup",
            "category": "implementation_bug",
        },
        {
            "module": "mapops",
            "function": "sum_values_in_range",
            "category": "implementation_bug",
        },
        {
            "module": "mapops",
            "function": "keys_with_value_in",
            "category": "missing_specification",
        },
        {
            "module": "mapops",
            "function": "key_of_max_value",
            "category": "missing_specification",
        },
        {
            "module": "setops_v2",
            "function": "intersect",
            "category": "implementation_bug",
        },
        {
            "module": "mapops_v2",
            "function": "range_lookup",
            "category": "implementation_bug",
        },
    ]
}

with open("/app/defect_report.json", "w") as f:
    json.dump(defect_report, f, indent=2)
print("[13] Produced defect classification report at /app/defect_report.json")

print("\nAll fixes applied and defect report generated successfully.")
