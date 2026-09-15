"""Add '# pragma: no mutate' annotations for equivalent mutations M10 and M11."""

# M10: scheduling.py — critical_path_length
# The mutation es > earliest_start[v] -> es >= earliest_start[v] is equivalent
# because when es == earliest_start[v], the assignment earliest_start[v] = es
# is a no-op (the value doesn't change).
with open("/app/intervallib/scheduling.py") as f:
    content = f.read()

content = content.replace(
    "            if es > earliest_start[v]:",
    "            if es > earliest_start[v]:  # pragma: no mutate  # >= is equivalent: assignment is a no-op when es == earliest_start[v]",
)

with open("/app/intervallib/scheduling.py", "w") as f:
    f.write(content)

# M11: solver.py — propagate_precedence
# The mutation dp[1] > ds[1] -> dp[1] >= ds[1] is equivalent because:
# 1. When dp[1] == ds[1], dp[1] = ds[1] is a no-op (value unchanged)
# 2. Setting changed = True causes one extra iteration, but since no domain
#    actually changed, the next iteration finds nothing to change and breaks.
# 3. The final output domains are identical for all inputs.
with open("/app/intervallib/solver.py") as f:
    content = f.read()

content = content.replace(
    "            if dp[1] > ds[1]:",
    "            if dp[1] > ds[1]:  # pragma: no mutate  # >= is equivalent: no-op assignment when equal; extra iteration has no effect on output",
)

with open("/app/intervallib/solver.py", "w") as f:
    f.write(content)
