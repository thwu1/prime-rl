
"""
Pool-based serialization for PersistentVector.

Implements serialization that preserves structural sharing between
multiple persistent vectors by deduplicating shared tree nodes into
a shared pool.

Pool format (JSON-compatible dict):
{
    "B": <int>,                     # BITS parameter of the tree
    "leaves": [                     # Leaf node pool
        [<node_id>, [<values...>]],
        ...
    ],
    "inners": [                     # Inner node pool
        [<node_id>, {"children": [<child_node_ids...>]}],
        ...
    ],
    "vectors": [                    # Vector descriptors (one per input vector)
        {
            "root": <node_id or null>,   # ID of root node, null if tree is empty
            "tail": [<values...>],       # Tail buffer values
            "size": <int>,               # Total element count
            "shift": <int>               # Tree depth indicator
        },
        ...
    ]
}

Key invariants:
- Shared tree nodes across multiple vectors must appear only once in the pool
  with a consistent node_id.
- Deserialization must restore sharing: nodes with the same pool ID must map
  to the same Python object (verifiable via the ``is`` operator).
- Node IDs are non-negative integers, unique across leaves and inners.
- Child IDs in inner nodes reference either leaf or inner node IDs.
"""

from persistent_vector import Node, PersistentVector, BITS, WIDTH, MASK


def serialize_to_pools(vectors):
    """
    Serialize multiple PersistentVectors into pool format preserving sharing.

    Shared tree nodes across vectors must appear exactly once in the pool
    with a unique integer node ID.

    Args:
        vectors: list of PersistentVector instances

    Returns:
        dict matching the pool format specification in the module docstring
    """
    raise NotImplementedError("Implement pool-based serialization")


def deserialize_from_pools(pool_data):
    """
    Reconstruct PersistentVectors from pool data, re-establishing sharing.

    Each unique node_id must map to exactly one Python Node object.
    Vectors referencing the same node_id must share the same Node object.

    Args:
        pool_data: dict in pool format (as produced by serialize_to_pools)

    Returns:
        list of PersistentVector instances with structural sharing restored
    """
    raise NotImplementedError("Implement pool-based deserialization")


def transform_pool(pool_data, transform_fn):
    """
    Apply a transformation to all leaf values and tail values in the pool,
    preserving tree structure. Must NOT mutate the original pool_data.

    Args:
        pool_data: dict in pool format
        transform_fn: callable(value) -> transformed_value

    Returns:
        new dict in pool format with transformed leaf and tail values
    """
    raise NotImplementedError("Implement pool transformation")


def compute_shared_diff(vec_a, vec_b):
    """
    Compute element-wise differences between two PersistentVectors,
    exploiting structural sharing for efficiency.

    Args:
        vec_a: PersistentVector (the "old" version)
        vec_b: PersistentVector (the "new" version)

    Returns:
        dict with:
            "changed": [(index, old_value, new_value), ...]
            "added": [(index, value), ...] for elements only in vec_b
            "removed": [(index, value), ...] for elements only in vec_a
            "nodes_visited": int count of tree nodes actually traversed
    """
    raise NotImplementedError("Implement structural-sharing-aware diff")
