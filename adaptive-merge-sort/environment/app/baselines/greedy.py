"""
Greedy merge strategy: always merge the adjacent pair with smallest combined length.

Fast for small n but O(n^2) overall, and not always near-optimal.

"""


def compute_schedule(run_lengths):
    """Greedy: always merge the two adjacent runs with smallest combined length."""
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    nodes = list(range(n))
    lengths = list(run_lengths)
    total_cost = 0

    while len(nodes) > 1:
        best_i = 0
        best_sum = lengths[0] + lengths[1]
        for i in range(1, len(lengths) - 1):
            s = lengths[i] + lengths[i + 1]
            if s < best_sum:
                best_sum = s
                best_i = i

        total_cost += best_sum
        new_node = (nodes[best_i], nodes[best_i + 1])
        nodes[best_i] = new_node
        lengths[best_i] = best_sum
        del nodes[best_i + 1]
        del lengths[best_i + 1]

    return (total_cost, nodes[0])
