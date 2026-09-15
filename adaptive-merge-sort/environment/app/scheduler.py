"""
Merge scheduling algorithm.


Implement compute_schedule(run_lengths) that returns (cost, merge_tree).
"""


def compute_schedule(run_lengths):
    """Compute a near-optimal merge schedule for the given run lengths.

    Args:
        run_lengths: list of positive integers, length of each run

    Returns:
        (cost, merge_tree) where:
        - cost: total merge cost (each merge of two segments costs their
          combined length)
        - merge_tree: nested binary tree structure.
          Leaf = integer run index.
          Internal node = (left_subtree, right_subtree) tuple.
          Leaves must appear left-to-right in order: 0, 1, ..., n-1.

    Example:
        >>> compute_schedule([10, 20])
        (30, (0, 1))
        >>> compute_schedule([1, 1, 100])
        (104, ((0, 1), 2))
    """
    raise NotImplementedError("Implement your merge scheduling algorithm here")
