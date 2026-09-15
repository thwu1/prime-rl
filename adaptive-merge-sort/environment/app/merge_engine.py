"""
Merge tree cost computation and validation utilities.

"""


def compute_tree_cost(tree, run_lengths):
    """Compute total merge cost from a merge tree (iterative)."""
    if tree is None or isinstance(tree, int):
        return 0
    # Post-order traversal using explicit stack
    # Stack entries: node, with a flag indicating if children have been processed
    size_map = {}
    cost = 0
    stack = [(tree, False)]
    while stack:
        node, processed = stack.pop()
        if isinstance(node, int):
            size_map[id(node)] = run_lengths[node]
            continue
        if processed:
            left, right = node
            left_size = size_map.get(id(left), run_lengths[left] if isinstance(left, int) else 0)
            right_size = size_map.get(id(right), run_lengths[right] if isinstance(right, int) else 0)
            merged = left_size + right_size
            cost += merged
            size_map[id(node)] = merged
        else:
            stack.append((node, True))
            stack.append((node[1], False))
            stack.append((node[0], False))
    return cost


def tree_leaves(tree):
    """Collect leaf indices in left-to-right order (iterative)."""
    if tree is None:
        return []
    if isinstance(tree, int):
        return [tree]
    leaves = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, int):
            leaves.append(node)
        else:
            stack.append(node[1])
            stack.append(node[0])
    return leaves


def validate_tree(tree, n):
    """Check that tree is a valid binary merge tree for n runs."""
    if n == 0:
        return tree is None
    if n == 1:
        return tree == 0
    leaves = tree_leaves(tree)
    return leaves == list(range(n))
