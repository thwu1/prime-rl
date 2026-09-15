#!/bin/bash

# Deploy the complete schema
cp /solution/schema_complete.sql /app/schema.sql

# Deploy the store implementation
cp /solution/snapstore_impl.py /app/snapstore.py

# Deploy the pool serializer implementation
cp /solution/pool_serializer_impl.py /app/pool_serializer.py

# Deploy the shell scripts
cp /solution/compact_impl.sh /app/compact.sh
cp /solution/export_impl.sh /app/export.sh
chmod +x /app/compact.sh /app/export.sh

# Initialize the database
cd /app
rm -f /app/store.db
sqlite3 /app/store.db < /app/schema.sql

# Verify the solution works
python3 -c "
import sys, json, os
sys.path.insert(0, '/app')
from snapstore import SnapStore
from persistent_vector import PersistentVector
from pool_serializer import serialize_to_pools, deserialize_from_pools, transform_pool, compute_shared_diff

os.remove('/app/store.db')
store = SnapStore('/app/store.db')
store.init_db('/app/schema.sql')

# Test save/load round-trip
v1 = PersistentVector.from_list(['a','b','c','d','e','f'])
v2 = v1.set(0, 'X')
store.save_batch({'v1': v1, 'v2': v2})

loaded = store.load_batch(['v1', 'v2'])
assert list(loaded['v1']) == ['a','b','c','d','e','f']
assert list(loaded['v2']) == ['X','b','c','d','e','f']
assert loaded['v1'].root.children[1] is loaded['v2'].root.children[1], 'Sharing not restored'

# Test pool serializer round-trip
pool = serialize_to_pools([v1, v2])
[p1, p2] = deserialize_from_pools(pool)
assert list(p1) == ['a','b','c','d','e','f']
assert list(p2) == ['X','b','c','d','e','f']
assert p1.root.children[1] is p2.root.children[1], 'Pool sharing not restored'

# Test transform
transformed = transform_pool(pool, str.upper)
[t1, t2] = deserialize_from_pools(transformed)
assert list(t1) == ['A','B','C','D','E','F']
# Verify no mutation
[check1, check2] = deserialize_from_pools(pool)
assert list(check1) == ['a','b','c','d','e','f']

# Test compute_shared_diff
diff = compute_shared_diff(v1, v2)
assert (0, 'a', 'X') in diff['changed']
assert diff['nodes_visited'] >= 0

# Test SnapStore diff
db_diff = store.diff('v1', 'v2')
assert (0, 'a', 'X') in db_diff['changed']
assert db_diff['nodes_compared'] >= 0

# Test node deduplication
def count_nodes(node):
    if node is None: return 0
    if node.is_leaf: return 1
    return 1 + sum(count_nodes(c) for c in node.children)

naive = count_nodes(v1.root) + count_nodes(v2.root)
assert store.node_count() < naive, 'Deduplication not working'

print('All solution checks passed')
"
