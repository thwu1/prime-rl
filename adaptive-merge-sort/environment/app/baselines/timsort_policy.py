"""
Simplified TimSort-like merge policy using a stack with invariant checks.

Maintains stack invariants similar to TimSort:
  - For top 3 entries A, B, C: A > B + C and B > C
When invariants are violated, merge the appropriate pair.

"""


def compute_schedule(run_lengths):
    """TimSort-like stack-based merge policy."""
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    stack = []  # entries: (tree, length)
    total_cost = 0

    def merge_top_two():
        nonlocal total_cost
        b_tree, b_len = stack.pop()
        a_tree, a_len = stack.pop()
        merged_len = a_len + b_len
        total_cost += merged_len
        stack.append(((a_tree, b_tree), merged_len))

    for i in range(n):
        stack.append((i, run_lengths[i]))

        while len(stack) >= 3:
            a_tree, a_len = stack[-3]
            b_tree, b_len = stack[-2]
            c_tree, c_len = stack[-1]

            if a_len <= b_len + c_len:
                if a_len < c_len:
                    # Merge A and B
                    entry_c = stack.pop()
                    merge_top_two()
                    stack.append(entry_c)
                else:
                    # Merge B and C
                    merge_top_two()
            elif b_len <= c_len:
                merge_top_two()
            else:
                break

    while len(stack) >= 2:
        merge_top_two()

    return (total_cost, stack[0][0])
