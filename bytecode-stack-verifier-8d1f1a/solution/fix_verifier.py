#!/usr/bin/env python3
"""
Fix the five defects in /app/src/verifier.c so it matches the
opcode specification in opcode_def.h.

"""

SRC = "/app/src/verifier.c"

with open(SRC, "r") as f:
    code = f.read()

# ---- Bug 1: set_loc n_push must be 1 (keeps value on stack), not 0 ----
code = code.replace(
    '"set_loc",       3,  1,  0',
    '"set_loc",       3,  1,  1',
    1,
)

# ---- Bug 2: call pops callee + args (arg_count + 1), not just args ----
code = code.replace(
    'return arg_count;',
    'return arg_count + 1;',
    1,
)

# ---- Bug 3: conditional branches must propagate to fall-through path ----
code = code.replace(
    'propagate(vs, target, new_depth);\n            break;\n        }\n\n        /* ---- unconditional jump ---- */',
    'propagate(vs, target, new_depth);\n            propagate(vs, pc + sz, new_depth);\n            break;\n        }\n\n        /* ---- unconditional jump ---- */',
    1,
)

# ---- Bug 4: goto must propagate depth to target, not just bounds-check ----
code = code.replace(
    """if (target < 0 || target >= (int)vs->code_len) {
                add_error(vs, "goto target %d out of bounds", target);
            }
            break;""",
    'propagate(vs, target, new_depth);\n            break;',
    1,
)

# ---- Bug 5: catch handler entry depth is new_depth + 1 (exception pushed) ----
code = code.replace(
    'propagate(vs, handler, new_depth);',
    'propagate(vs, handler, new_depth + 1);',
    1,
)

with open(SRC, "w") as f:
    f.write(code)

print("verifier.c patched successfully")
