#!/usr/bin/env python3
"""Profiling workload for cProfile and gprof2dot call graph analysis.

Exercises key map operations to expose performance characteristics
in the generated call graph visualization.
"""
import sys
sys.path.insert(0, '/app')
from store.persistent_map import PersistentMap

# Build a large map
m = PersistentMap()
for i in range(5000):
    m = m.insert(i, i)

# Self-diff — should be O(1) with identity shortcut
for _ in range(50):
    m.diff(m)

# Diff with small change
m2 = m.insert(500, -1)
for _ in range(50):
    m.diff(m2)

# No-op inserts — should return identity
for _ in range(1000):
    m.insert(500, 500)

# Delete sequence to exercise compaction paths
m3 = m
for i in range(0, 200, 2):
    m3 = m3.delete(i)
