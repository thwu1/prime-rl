"""
Fix all 5 bugs in the mini autodiff framework.

"""

import re

with open('/app/autodiff.py', 'r') as f:
    content = f.read()

# ---------------------------------------------------------------
# Bug 1: Division VJP rule is missing y^2 in denominator.
# The quotient rule for z = x/y gives dz/dy = -x/y^2.
# The code has:  return (ct / y, -ct * x / y)
# Should be:     return (ct / y, -ct * x / (y * y))
# ---------------------------------------------------------------
content = content.replace(
    'return (ct / y, -ct * x / y)',
    'return (ct / y, -ct * x / (y * y))'
)

# ---------------------------------------------------------------
# Bug 2: Multiplication VJP rule has swapped cotangents.
# For z = x * y: dz/dx = y, dz/dy = x.
# The code has:  return (ct * x, ct * y)
# Should be:     return (ct * y, ct * x)
# ---------------------------------------------------------------
content = content.replace(
    'return (ct * x, ct * y)',
    'return (ct * y, ct * x)'
)

# ---------------------------------------------------------------
# Bug 3: Exponential VJP rule is not registered.
# For z = exp(x): dz/dx = exp(x).
# Need to add:  vjp_rules[exp_p] = lambda ct, iv, ov: (ct * math.exp(iv[0]),)
# Insert it right before the vjp_log definition.
# ---------------------------------------------------------------
content = content.replace(
    'def vjp_log(ct, input_vals, output_val):',
    """def vjp_exp(ct, input_vals, output_val):
    x, = input_vals
    return (ct * math.exp(x),)

vjp_rules[exp_p] = vjp_exp


def vjp_log(ct, input_vals, output_val):"""
)

# ---------------------------------------------------------------
# Bug 4: Subtraction JVP rule has wrong sign on tangent.
# For z = x - y: dz tangent = x_dot - y_dot.
# The code has:  tangents[0] + tangents[1]
# Should be:     tangents[0] - tangents[1]
# We match the full sub rule lambda to avoid changing the add rule.
# ---------------------------------------------------------------
content = content.replace(
    "primals[0] - primals[1],\n    tangents[0] + tangents[1]",
    "primals[0] - primals[1],\n    tangents[0] - tangents[1]"
)

# ---------------------------------------------------------------
# Bug 5: Backward pass overwrites gradient instead of accumulating.
# When a variable is used multiple times, all gradient contributions
# must be summed. The code has:
#     grads[inp.id] = ict
# in the branch where inp.id is already in grads. Should be:
#     grads[inp.id] = grads[inp.id] + ict
# ---------------------------------------------------------------
# Replace only the first occurrence (the if-branch), not the else-branch.
# The if-branch is distinguished by being inside "if inp.id in grads:".
old_backward = """            if inp.id in grads:
                grads[inp.id] = ict
            else:
                grads[inp.id] = ict"""
new_backward = """            if inp.id in grads:
                grads[inp.id] = grads[inp.id] + ict
            else:
                grads[inp.id] = ict"""
content = content.replace(old_backward, new_backward)

with open('/app/autodiff.py', 'w') as f:
    f.write(content)

print("All 5 bugs fixed successfully.")
