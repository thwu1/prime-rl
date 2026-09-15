#!/bin/bash
cd /app
PYTHONDONTWRITEBYTECODE=1 python3 -c "
import sys
sys.path.insert(0, '/app')
from store.persistent_map import PersistentMap
m = PersistentMap().insert('a', 1).insert('b', 2)
m2 = m.insert('a', 1)
sys.exit(0 if m is m2 else 1)
"
