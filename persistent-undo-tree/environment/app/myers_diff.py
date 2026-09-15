
"""Myers diff algorithm for computing the shortest edit script.

Based on "An O(ND) Difference Algorithm and Its Variations" by Eugene W. Myers (1986).

Given two strings a and b, produces a minimal list of operations:
    ('equal',  char)  -- character is unchanged
    ('delete', char)  -- character was removed from a
    ('insert', char)  -- character was added from b

The edit script, when applied sequentially, transforms a into b.
"""

from typing import List, Tuple


def myers_diff(a: str, b: str) -> List[Tuple[str, str]]:
    """Compute the shortest edit script to transform string a into string b.

    Returns a list of (operation, character) tuples where operation is
    one of 'equal', 'delete', or 'insert'. The script is minimal: it
    uses the fewest possible insert and delete operations.

    The algorithm runs in O((N+M)D) time where N=len(a), M=len(b),
    and D is the edit distance.
    """
    raise NotImplementedError("myers_diff not yet implemented")
