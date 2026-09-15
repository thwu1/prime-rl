#!/usr/bin/env python3
"""Generate binary page store file at /app/pages.bin."""

import struct

baselines = [
    (1,  'orders',      0,    'Order record slot - initially empty'),
    (2,  'orders',      0,    'Order record slot - initially empty'),
    (3,  'orders',      0,    'Order record slot - initially empty'),
    (5,  'products',    100,  'Product stock count - item Alpha'),
    (6,  'products',    200,  'Product stock count - item Beta'),
    (7,  'order_items', 0,    'Order line item slot - initially empty'),
    (8,  'order_items', 0,    'Order line item slot - initially empty'),
    (9,  'products',    50,   'Product price - item Alpha'),
    (10, 'inv_index',   1000, 'Inventory B+ tree index node'),
    (11, 'products',    300,  'Product stock count - item Gamma'),
    (12, 'inv_index',   2000, 'Inventory B+ tree index node'),
    (13, 'products',    500,  'Product stock count - item Delta'),
    (14, 'products',    400,  'Product stock count - item Epsilon'),
]

with open('/app/pages.bin', 'wb') as f:
    # Header: magic (4) + version (2) + count (2) = 8 bytes
    f.write(b'PGST')
    f.write(struct.pack('<H', 1))
    f.write(struct.pack('<H', len(baselines)))

    # Each entry: page_id (4) + value (4) + table_name (32) + description (64) = 104 bytes
    for page_id, table_name, init_val, desc in baselines:
        f.write(struct.pack('<I', page_id))
        f.write(struct.pack('<i', init_val))
        f.write(table_name.encode('ascii').ljust(32, b'\x00'))
        f.write(desc.encode('ascii').ljust(64, b'\x00'))

print("Binary page store created at /app/pages.bin")
