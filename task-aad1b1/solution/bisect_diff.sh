#!/bin/bash
cd /app
PYTHONDONTWRITEBYTECODE=1 python3 -c "
import sys
sys.path.insert(0, '/app')
from store.persistent_map import PersistentMap

class CK:
    def __init__(self, name, h):
        self._name = name
        self._hash = h
    def __hash__(self): return self._hash
    def __eq__(self, other): return isinstance(other, CK) and self._name == other._name

k1 = CK('a', 100)
k2 = CK('b', 100)
m1 = PersistentMap().insert(k1, 1).insert(k2, 2)
m2 = PersistentMap().insert(k1, 99).insert(k2, 2)
diff = m1.diff(m2)
sys.exit(0 if k1 in diff and k2 not in diff else 1)
"
