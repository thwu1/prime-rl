#!/bin/bash

pip3 install sqlglot==25.0.0 duckdb==1.1.0 -q

cp /solution/dist_agg_impl.py /app/dist_agg.py

# Verify the solution works by running it
python3 -c "
import sys, duckdb, json
sys.path.insert(0, '/app')
from dist_agg import decompose_query

config = json.load(open('/app/config.json'))
shards = config['shard_tables']

conn = duckdb.connect(config['database'])

# Test basic COUNT
test_sql = 'SELECT COUNT(*) AS total FROM sales'
result = decompose_query(test_sql, shards)
parts = []
for st in shards:
    parts.append('(' + result['shard_query_template'].format(shard_table=st) + ')')
union_sql = ' UNION ALL '.join(parts)
conn.execute(f'CREATE OR REPLACE TEMPORARY TABLE shard_results AS {union_sql}')
conn.execute(result['merge_query'])
decomp = conn.fetchone()[0]
conn.execute(test_sql)
orig = conn.fetchone()[0]
assert decomp == orig, f'COUNT(*) failed: {decomp} != {orig}'
print(f'COUNT(*) verified: {orig}')

# Test COUNT(DISTINCT)
test_sql2 = 'SELECT COUNT(DISTINCT product) AS n FROM sales'
result2 = decompose_query(test_sql2, shards)
parts2 = []
for st in shards:
    parts2.append('(' + result2['shard_query_template'].format(shard_table=st) + ')')
conn.execute(f'CREATE OR REPLACE TEMPORARY TABLE shard_results AS {\" UNION ALL \".join(parts2)}')
conn.execute(result2['merge_query'])
decomp2 = conn.fetchone()[0]
conn.execute(test_sql2)
orig2 = conn.fetchone()[0]
assert decomp2 == orig2, f'COUNT(DISTINCT) failed: {decomp2} != {orig2}'
print(f'COUNT(DISTINCT product) verified: {orig2}')

# Test COVAR_POP
import math
test_sql3 = 'SELECT COVAR_POP(price, quantity) AS cov FROM sales'
result3 = decompose_query(test_sql3, shards)
parts3 = []
for st in shards:
    parts3.append('(' + result3['shard_query_template'].format(shard_table=st) + ')')
conn.execute(f'CREATE OR REPLACE TEMPORARY TABLE shard_results AS {\" UNION ALL \".join(parts3)}')
conn.execute(result3['merge_query'])
decomp3 = conn.fetchone()[0]
conn.execute(test_sql3)
orig3 = conn.fetchone()[0]
assert math.isclose(float(decomp3), float(orig3), rel_tol=1e-6), f'COVAR_POP failed: {decomp3} != {orig3}'
print(f'COVAR_POP(price, quantity) verified: {orig3:.4f}')

conn.close()
print('All solution verifications passed')
"
