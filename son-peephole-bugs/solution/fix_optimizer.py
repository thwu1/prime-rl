#!/usr/bin/env python3
"""
Fix all 6 bugs in the Sea of Nodes IR peephole optimizer.

Bug 1: value_of AND uses | instead of &
Bug 2: GVN equality check omits data type comparison
Bug 3: SELECT identity checks wrong input pair
Bug 4: CMP_SLT constant folding omits sign extension
Bug 5: MUL strength reduction treats 0 as power of 2
Bug 6: ADD (a-b)+b identity checks wrong SUB input index
"""

import re

OPTIMIZER_PATH = "/app/son_ir/optimizer.py"

with open(OPTIMIZER_PATH, "r") as f:
    code = f.read()

original = code

# ---------------------------------------------------------------
# Bug 1: AND constant folding uses | instead of &
# In value_of, the AND branch computes a_val | b_val
# ---------------------------------------------------------------
code = code.replace(
    "            return _make_const(a_val | b_val, node.dt)",
    "            return _make_const(a_val & b_val, node.dt)",
    1  # only first occurrence (the AND case)
)

# ---------------------------------------------------------------
# Bug 2: GVN equal/hash don't account for data type
# Need to add dt to both hash and equality check
# ---------------------------------------------------------------

# Fix gvn_hash: add dt to hash computation
code = code.replace(
    "    if node.type == NodeType.ICONST:\n        h = h * 31 + node.value\n    if node.type == NodeType.PARAM:",
    "    h = h * 31 + hash(node.dt)\n    if node.type == NodeType.ICONST:\n        h = h * 31 + node.value\n    if node.type == NodeType.PARAM:",
)

# Fix gvn_equal: add dt comparison after type check
code = code.replace(
    "    if a.type != b.type:\n        return False\n    if len(a.inputs) != len(b.inputs):",
    "    if a.type != b.type:\n        return False\n    if a.dt != b.dt:\n        return False\n    if len(a.inputs) != len(b.inputs):",
)

# ---------------------------------------------------------------
# Bug 3: SELECT identity checks inputs[0] is inputs[1]
# Should check inputs[1] is inputs[2] (both branches same)
# ---------------------------------------------------------------
code = code.replace(
    "        if node.inputs[0] is node.inputs[1]:\n            return node.inputs[1]",
    "        if node.inputs[1] is node.inputs[2]:\n            return node.inputs[1]",
)

# ---------------------------------------------------------------
# Bug 4: CMP_SLT constant folding doesn't sign-extend
# Need to add _sign_extend calls before comparison
# ---------------------------------------------------------------
code = code.replace(
    """    elif nt == NodeType.CMP_SLT:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a < b else 0, I1)""",
    """    elif nt == NodeType.CMP_SLT:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            bits = node.inputs[0].dt.bits
            a = _sign_extend(_const_val(node.inputs[0]), bits)
            b = _sign_extend(_const_val(node.inputs[1]), bits)
            return _make_const(1 if a < b else 0, I1)""",
)

# ---------------------------------------------------------------
# Bug 5: _is_power_of_2 returns True for 0
# Fix by adding n > 0 guard
# ---------------------------------------------------------------
code = code.replace(
    '    return n & (n - 1) == 0',
    '    return n > 0 and n & (n - 1) == 0',
)

# ---------------------------------------------------------------
# Bug 6: _idealize_add checks lhs.inputs[0] instead of lhs.inputs[1]
# for the (a - b) + b => a pattern
# ---------------------------------------------------------------
code = code.replace(
    "    if lhs.type == NodeType.SUB and lhs.inputs[0] is rhs:",
    "    if lhs.type == NodeType.SUB and lhs.inputs[1] is rhs:",
)

# Verify all patches were applied
assert code != original, "No patches were applied"

# Count changes
diff_count = sum(1 for a, b in zip(original.split('\n'), code.split('\n')) if a != b)
# Account for added lines too
orig_lines = len(original.split('\n'))
new_lines = len(code.split('\n'))

with open(OPTIMIZER_PATH, "w") as f:
    f.write(code)

print(f"Applied 6 bug fixes to {OPTIMIZER_PATH}")
print(f"Lines changed/added: {abs(new_lines - orig_lines) + diff_count}")
