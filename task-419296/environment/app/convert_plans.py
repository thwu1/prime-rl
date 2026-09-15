#!/usr/bin/env python3
"""Convert .txt EXPLAIN ANALYZE files to .planpb binary format.

Run once during Docker image build; the .txt originals are deleted afterward.
"""

import gzip
import json
import os
import struct

MAGIC = b'TPLN'
VERSION = 1
PLANS_DIR = '/app/plans'

PLAN_METADATA = {
    'case1_lock_contention.txt': {
        'query': "select * from orders where order_id = 50421 and region = 'US-WEST'",
        'database': 'ecommerce',
        'total_time': '3.20s',
        'plan_digest': 'plan_d1e2f3a4b5c6',
        'query_digest': 'a3f8c21d9e7b4a6f',
    },
    'case2_concurrency.txt': {
        'query': "select * from inventory where sku like '98712%'",
        'database': 'ecommerce',
        'total_time': '0.01s',
        'plan_digest': 'plan_a1b2c3d4e5f6',
        'query_digest': 'd9e8f7a6b5c4d3e2',
    },
    'case3_max.txt': {
        'query': 'select max(created_at) from events limit 1',
        'database': 'ecommerce',
        'total_time': '0.01s',
        'plan_digest': 'plan_s1t2u3v4w5x6',
        'query_digest': 'f8a7b6c5d4e3f2a1',
    },
    'case3_min.txt': {
        'query': 'select min(created_at) from events limit 1',
        'database': 'ecommerce',
        'total_time': '9.65s',
        'plan_digest': 'plan_y1z2a3b4c5d6',
        'query_digest': 'a1b7c6d5e4f3a2b1',
    },
    'case4_complex_join.txt': {
        'query': (
            "select o.order_id, o.total, c.name from orders o "
            "join customers c on o.customer_id = c.id "
            "where o.created_at > '2024-01-01' and c.tier = 'premium'"
        ),
        'database': 'ecommerce',
        'total_time': '0.29s',
        'plan_digest': 'plan_q1r2s3t4u5v6',
        'query_digest': 'c3d4e5f6a7b8c9d0',
    },
}


def convert(txt_path, planpb_path, metadata):
    with open(txt_path) as f:
        plan_text = f.read()
    hdr = gzip.compress(json.dumps(metadata).encode())
    body = gzip.compress(plan_text.encode())
    with open(planpb_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', VERSION))
        f.write(struct.pack('<I', len(hdr)))
        f.write(hdr)
        f.write(struct.pack('<I', len(body)))
        f.write(body)


for name, meta in PLAN_METADATA.items():
    src = os.path.join(PLANS_DIR, name)
    dst = os.path.join(PLANS_DIR, name.replace('.txt', '.planpb'))
    if os.path.exists(src):
        convert(src, dst, meta)
        print(f'  {name} -> {os.path.basename(dst)}')

print('Plan conversion complete.')
