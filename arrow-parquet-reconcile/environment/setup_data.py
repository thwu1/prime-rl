#!/usr/bin/env python3
"""Generate heterogeneous Parquet staging data with schema evolution, duplicates, and quality issues."""
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import os
import decimal

STAGING = '/app/staging'
os.makedirs(STAGING, exist_ok=True)

CATEGORIES = ['retail', 'grocery', 'electronics', 'food', 'transport', 'utilities']
STATUSES = ['completed', 'pending', 'failed']
REGIONS = ['US-East', 'US-West', 'EU-West', 'EU-East', 'APAC']
CHANNELS = ['web', 'mobile', 'api']


def pick(rng, options, n):
    return [options[i] for i in rng.randint(0, len(options), n)]


# ============================================================
# EPOCH 1: Basic schema
#   event_id: int32
#   timestamp: timestamp[ms] (no timezone)
#   amount: float32
#   user_id: int32
#   category: string
#   status: string
# ============================================================

# File 1: batch_2024_01_a.parquet — 500 rows, clean
rng = np.random.RandomState(1001)
n = 500
table = pa.table({
    'event_id': pa.array(np.arange(10000, 10000 + n, dtype=np.int32), type=pa.int32()),
    'timestamp': pa.array(
        pd.date_range('2024-01-01', periods=n, freq='30min'),
        type=pa.timestamp('ms')),
    'amount': pa.array(
        rng.uniform(5.0, 500.0, n).round(2).astype(np.float32),
        type=pa.float32()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int32), type=pa.int32()),
    'category': pa.array(pick(rng, CATEGORIES, n), type=pa.string()),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_01_a.parquet'),
               version='1.0', compression='snappy')

# File 2: batch_2024_01_b.parquet — 500 rows (will be superseded by v2 retry)
rng = np.random.RandomState(1002)
n = 500
table = pa.table({
    'event_id': pa.array(np.arange(10500, 10500 + n, dtype=np.int32), type=pa.int32()),
    'timestamp': pa.array(
        pd.date_range('2024-01-15', periods=n, freq='30min'),
        type=pa.timestamp('ms')),
    'amount': pa.array(
        rng.uniform(5.0, 500.0, n).round(2).astype(np.float32),
        type=pa.float32()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int32), type=pa.int32()),
    'category': pa.array(pick(rng, CATEGORIES, n), type=pa.string()),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_01_b.parquet'),
               version='1.0', compression='snappy')

# File 3: batch_2024_01_b_v2.parquet — 520 rows, retry of file 2
#   IDs 10500-11019: overlaps 500 IDs from file 2, adds 20 new
#   Different RNG seed → different amounts for overlapping IDs
rng = np.random.RandomState(1003)
n = 520
table = pa.table({
    'event_id': pa.array(np.arange(10500, 10500 + n, dtype=np.int32), type=pa.int32()),
    'timestamp': pa.array(
        pd.date_range('2024-01-15', periods=n, freq='30min'),
        type=pa.timestamp('ms')),
    'amount': pa.array(
        rng.uniform(5.0, 500.0, n).round(2).astype(np.float32),
        type=pa.float32()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int32), type=pa.int32()),
    'category': pa.array(pick(rng, CATEGORIES, n), type=pa.string()),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_01_b_v2.parquet'),
               version='1.0', compression='snappy')

# ============================================================
# EPOCH 2: Expanded schema
#   event_id: int64
#   timestamp: timestamp[us] (no timezone)
#   amount: float64
#   user_id: int64
#   category: dictionary<string>
#   status: string
#   region: string          (NEW)
#   channel: string         (NEW)
# ============================================================

# File 4: batch_2024_02_a.parquet — 600 rows, 5 null event_ids
rng = np.random.RandomState(1004)
n = 600
ids = np.arange(20000, 20000 + n, dtype=np.int64)
null_mask = np.zeros(n, dtype=bool)
for idx in [10, 100, 200, 300, 400]:
    null_mask[idx] = True
table = pa.table({
    'event_id': pa.array(ids, type=pa.int64(), mask=null_mask),
    'timestamp': pa.array(
        pd.date_range('2024-02-01', periods=n, freq='30min'),
        type=pa.timestamp('us')),
    'amount': pa.array(rng.uniform(5.0, 500.0, n).round(2), type=pa.float64()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int64), type=pa.int64()),
    'category': pa.array(pick(rng, CATEGORIES, n)).dictionary_encode(),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
    'region': pa.array(pick(rng, REGIONS, n), type=pa.string()),
    'channel': pa.array(pick(rng, CHANNELS, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_02_a.parquet'),
               version='2.6', compression='snappy')

# File 5: batch_2024_02_b.parquet — 600 rows, clean
rng = np.random.RandomState(1005)
n = 600
table = pa.table({
    'event_id': pa.array(np.arange(20600, 20600 + n, dtype=np.int64), type=pa.int64()),
    'timestamp': pa.array(
        pd.date_range('2024-02-15', periods=n, freq='30min'),
        type=pa.timestamp('us')),
    'amount': pa.array(rng.uniform(5.0, 500.0, n).round(2), type=pa.float64()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int64), type=pa.int64()),
    'category': pa.array(pick(rng, CATEGORIES, n)).dictionary_encode(),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
    'region': pa.array(pick(rng, REGIONS, n), type=pa.string()),
    'channel': pa.array(pick(rng, CHANNELS, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_02_b.parquet'),
               version='2.6', compression='snappy')

# File 6: batch_2024_03_a.parquet — 500 rows, 3 negative amounts
rng = np.random.RandomState(1006)
n = 500
amounts = rng.uniform(5.0, 500.0, n).round(2)
amounts[50] = -10.50
amounts[150] = -25.00
amounts[250] = -0.99
table = pa.table({
    'event_id': pa.array(np.arange(30000, 30000 + n, dtype=np.int64), type=pa.int64()),
    'timestamp': pa.array(
        pd.date_range('2024-03-01', periods=n, freq='30min'),
        type=pa.timestamp('us')),
    'amount': pa.array(amounts, type=pa.float64()),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int64), type=pa.int64()),
    'category': pa.array(pick(rng, CATEGORIES, n)).dictionary_encode(),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
    'region': pa.array(pick(rng, REGIONS, n), type=pa.string()),
    'channel': pa.array(pick(rng, CHANNELS, n), type=pa.string()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_03_a.parquet'),
               version='2.6', compression='snappy')

# ============================================================
# EPOCH 3: Full schema
#   event_id: int64
#   timestamp: timestamp[us, tz=UTC]
#   amount: decimal128(12, 2)
#   user_id: int64
#   category: string
#   status: string
#   region: string
#   channel: string
#   risk_score: float64    (NEW)
# ============================================================

# File 7: batch_2024_03_b.parquet — 500 rows (will be superseded by v2 retry)
rng = np.random.RandomState(1007)
n = 500
amounts = rng.uniform(5.0, 500.0, n).round(2)
table = pa.table({
    'event_id': pa.array(np.arange(30500, 30500 + n, dtype=np.int64), type=pa.int64()),
    'timestamp': pa.array(
        pd.date_range('2024-03-15', periods=n, freq='30min', tz='UTC'),
        type=pa.timestamp('us', tz='UTC')),
    'amount': pa.array(
        [decimal.Decimal(f'{a:.2f}') for a in amounts],
        type=pa.decimal128(12, 2)),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int64), type=pa.int64()),
    'category': pa.array(pick(rng, CATEGORIES, n), type=pa.string()),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
    'region': pa.array(pick(rng, REGIONS, n), type=pa.string()),
    'channel': pa.array(pick(rng, CHANNELS, n), type=pa.string()),
    'risk_score': pa.array(rng.uniform(0.0, 1.0, n).round(4), type=pa.float64()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_03_b.parquet'),
               version='2.6', compression='zstd')

# File 8: batch_2024_03_b_v2.parquet — 530 rows, retry of file 7
#   IDs 30500-31029: overlaps 500 IDs from file 7, adds 30 new
#   2 rows (indices 510, 520) have future timestamps in 2025
rng = np.random.RandomState(1008)
n = 530
amounts = rng.uniform(5.0, 500.0, n).round(2)
timestamps = pd.date_range('2024-03-15', periods=n, freq='30min', tz='UTC').to_list()
timestamps[510] = pd.Timestamp('2025-06-15 10:00:00', tz='UTC')
timestamps[520] = pd.Timestamp('2025-09-01 14:30:00', tz='UTC')
table = pa.table({
    'event_id': pa.array(np.arange(30500, 30500 + n, dtype=np.int64), type=pa.int64()),
    'timestamp': pa.array(timestamps, type=pa.timestamp('us', tz='UTC')),
    'amount': pa.array(
        [decimal.Decimal(f'{a:.2f}') for a in amounts],
        type=pa.decimal128(12, 2)),
    'user_id': pa.array(rng.randint(1000, 9999, n).astype(np.int64), type=pa.int64()),
    'category': pa.array(pick(rng, CATEGORIES, n), type=pa.string()),
    'status': pa.array(pick(rng, STATUSES, n), type=pa.string()),
    'region': pa.array(pick(rng, REGIONS, n), type=pa.string()),
    'channel': pa.array(pick(rng, CHANNELS, n), type=pa.string()),
    'risk_score': pa.array(rng.uniform(0.0, 1.0, n).round(4), type=pa.float64()),
})
pq.write_table(table, os.path.join(STAGING, 'batch_2024_03_b_v2.parquet'),
               version='2.6', compression='zstd')

total = 500 + 500 + 520 + 600 + 600 + 500 + 500 + 530
print(f"Generated {total} total rows across 8 files in {STAGING}")
for f in sorted(os.listdir(STAGING)):
    t = pq.read_table(os.path.join(STAGING, f))
    print(f"  {f}: {len(t)} rows, schema: {[f'{c.name}:{c.type}' for c in t.schema]}")
