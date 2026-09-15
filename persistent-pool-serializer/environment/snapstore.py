
"""
Persistent Vector Snapshot Store

Persists PersistentVector instances into a SQLite database while preserving
structural sharing: tree nodes common to multiple vector versions are stored
exactly once.

The store must ensure that:
- Saving two vectors that share subtrees does not duplicate shared nodes
- Loading vectors restores actual Python object sharing (same Node instance
  for shared subtrees, verifiable via the ``is`` operator)
- Diffs between snapshots exploit shared structure for efficiency

Database location: passed to constructor
Schema: loaded via init_db() from a SQL file
"""

import sqlite3
import json
from persistent_vector import Node, PersistentVector, BITS, WIDTH, MASK


class SnapStore:
    def __init__(self, db_path):
        """Initialize the store with the given database path."""
        raise NotImplementedError

    def init_db(self, schema_path):
        """Initialize the database using the SQL schema file.
        Must handle the case where tables already exist."""
        raise NotImplementedError

    def save(self, name, vector):
        """Save a PersistentVector as a named snapshot.
        If a snapshot with this name exists, it is overwritten."""
        raise NotImplementedError

    def save_batch(self, named_vectors):
        """Save multiple named vectors in a single transaction.
        Structural sharing between the vectors must be preserved in storage.
        named_vectors: dict of {name: PersistentVector}"""
        raise NotImplementedError

    def load(self, name):
        """Load and return the PersistentVector for the given snapshot name.
        Raises KeyError if the snapshot doesn't exist."""
        raise NotImplementedError

    def load_batch(self, names):
        """Load multiple snapshots, restoring structural sharing between them.
        Nodes shared across loaded vectors must be the same Python object.
        Returns: dict of {name: PersistentVector}"""
        raise NotImplementedError

    def diff(self, name_a, name_b):
        """Compute element-wise differences between two snapshots.
        Must exploit structural sharing to skip identical subtrees.
        Returns dict: {
            'changed': [(index, old_val, new_val), ...],
            'added': [(index, val), ...],
            'removed': [(index, val), ...],
            'nodes_compared': int  -- tree nodes actually examined
        }"""
        raise NotImplementedError

    def delete(self, name):
        """Remove a snapshot. Does not remove orphaned nodes."""
        raise NotImplementedError

    def list_snapshots(self):
        """Return sorted list of all snapshot names."""
        raise NotImplementedError

    def node_count(self):
        """Return total number of nodes currently stored."""
        raise NotImplementedError
