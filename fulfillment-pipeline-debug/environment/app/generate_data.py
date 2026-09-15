#!/usr/bin/env python3
"""Deterministic data generator for the fulfillment analytics database.
Outputs SQL INSERT statements to stdout. Uses seed 42 for reproducibility.
"""

import random
import json
from datetime import datetime, timedelta

random.seed(42)

# ---------------------------------------------------------------------------
# Warehouse hierarchy (20 warehouses, 4 levels deep in North region)
# ---------------------------------------------------------------------------
warehouses = [
    # Hubs (depth 1)
    (1,  'Hub_Alpha',          None, 'North', 8000, 'hub'),
    (2,  'Hub_Beta',           None, 'South', 7500, 'hub'),
    (3,  'Hub_Gamma',          None, 'East',  9000, 'hub'),
    # Regionals (depth 2)
    (4,  'North_Regional_1',   1,    'North', 2500, 'regional'),
    (5,  'North_Regional_2',   1,    'North', 2200, 'regional'),
    (6,  'South_Regional_1',   2,    'South', 2800, 'regional'),
    (7,  'South_Regional_2',   2,    'South', 2100, 'regional'),
    (8,  'East_Regional_1',    3,    'East',  3000, 'regional'),
    # Locals (depth 3)
    (9,  'NR1_Local_1',        4,    'North', 600,  'local'),
    (10, 'NR1_Local_2',        4,    'North', 550,  'local'),
    (11, 'NR2_Local_1',        5,    'North', 700,  'local'),
    (12, 'NR2_Local_2',        5,    'North', 450,  'local'),
    (13, 'SR1_Local_1',        6,    'South', 650,  'local'),
    (14, 'SR1_Local_2',        6,    'South', 500,  'local'),
    (15, 'SR2_Local_1',        7,    'South', 600,  'local'),
    (16, 'SR2_Local_2',        7,    'South', 480,  'local'),
    (17, 'ER1_Local_1',        8,    'East',  750,  'local'),
    (18, 'ER1_Local_2',        8,    'East',  620,  'local'),
    (19, 'ER1_Local_3',        8,    'East',  580,  'local'),
    # Depot (depth 4 — only North has this extra level)
    (20, 'NR2_Depot_1',        11,   'North', 200,  'depot'),
]

warehouse_region = {w[0]: w[3] for w in warehouses}

print("BEGIN;")

for wid, wname, parent_id, region, capacity, wtype in warehouses:
    parent_str = 'NULL' if parent_id is None else str(parent_id)
    print(
        f"INSERT INTO warehouses (warehouse_id, warehouse_name, parent_id, "
        f"region, capacity, warehouse_type) "
        f"VALUES ({wid}, '{wname}', {parent_str}, '{region}', {capacity}, '{wtype}');"
    )

print()

# ---------------------------------------------------------------------------
# Fulfillment stages
# ---------------------------------------------------------------------------
stages = [
    (1, 'received',  1),
    (2, 'picked',    2),
    (3, 'packed',    3),
    (4, 'shipped',   4),
    (5, 'delivered', 5),
]
for sid, sname, sorder in stages:
    print(
        f"INSERT INTO fulfillment_stages (stage_id, stage_name, stage_order) "
        f"VALUES ({sid}, '{sname}', {sorder});"
    )

print()

# ---------------------------------------------------------------------------
# Orders — 600 orders across 2024-01-01 to 2024-06-30
# ---------------------------------------------------------------------------
operational_warehouses = list(range(9, 21))  # IDs 9-20 (all leaf + depot)
items_pool = [
    'widget', 'gadget', 'gizmo', 'thingamajig', 'doohickey',
    'contraption', 'sprocket', 'flange', 'coupling', 'manifold',
]

start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 6, 30)
total_days = (end_date - start_date).days

orders_data = []
for oid in range(1, 601):
    wh = random.choice(operational_warehouses)
    day_offset = random.randint(0, total_days)
    order_date = start_date + timedelta(days=day_offset)

    region = warehouse_region[wh]

    # Customer tier (weighted)
    r = random.random()
    if r < 0.2:
        tier = 'gold'
    elif r < 0.6:
        tier = 'silver'
    else:
        tier = 'bronze'

    priority = random.randint(1, 5)
    num_items = random.randint(1, 4)
    items = random.sample(items_pool, num_items)

    # Base amount varies by tier
    if tier == 'gold':
        amount = round(random.uniform(200, 500), 2)
    elif tier == 'silver':
        amount = round(random.uniform(100, 350), 2)
    else:
        amount = round(random.uniform(50, 200), 2)

    # Seasonal multiplier for quarterly growth variation
    quarter = (order_date.month - 1) // 3 + 1
    if region == 'North' and quarter == 2:
        amount = round(amount * 1.25, 2)
    elif region == 'East' and quarter == 2:
        amount = round(amount * 0.8, 2)

    metadata = json.dumps(
        {'customer_tier': tier, 'priority': priority, 'items': items},
        ensure_ascii=True,
    )
    metadata_sql = metadata.replace("'", "''")

    print(
        f"INSERT INTO orders (order_id, warehouse_id, order_date, metadata, total_amount) "
        f"VALUES ({oid}, {wh}, '{order_date.strftime('%Y-%m-%d %H:%M:%S+00')}', "
        f"'{metadata_sql}'::jsonb, {amount});"
    )

    orders_data.append((oid, wh, order_date, region))

print()

# ---------------------------------------------------------------------------
# Order events — stage transitions for each order
# ~80% complete all 5 stages
# ~8% incomplete (stages 1-3 only)
# ~8% skip one middle stage (2 or 3)
# ~4% skip stage 1 (rare data-quality issue)
# ---------------------------------------------------------------------------
event_id = 1
for oid, wh, order_date, region in orders_data:
    r = random.random()
    if r < 0.80:
        active_stages = [1, 2, 3, 4, 5]
    elif r < 0.88:
        active_stages = [1, 2, 3]
    elif r < 0.96:
        skip = random.choice([2, 3])
        active_stages = [s for s in [1, 2, 3, 4, 5] if s != skip]
    else:
        active_stages = [2, 3, 4, 5]

    for stage_id in active_stages:
        entered = order_date + timedelta(
            hours=stage_id * 4 + random.randint(0, 2)
        )
        completed = entered + timedelta(hours=random.randint(1, 3))

        # Delivery stage may fail — rate varies by region
        if stage_id == 5:
            fail_rate = {'North': 0.10, 'South': 0.15, 'East': 0.20}
            status = (
                'failed'
                if random.random() < fail_rate.get(region, 0.15)
                else 'completed'
            )
        else:
            status = 'completed'

        entered_str = entered.strftime('%Y-%m-%d %H:%M:%S+00')
        completed_str = completed.strftime('%Y-%m-%d %H:%M:%S+00')

        print(
            f"INSERT INTO order_events "
            f"(event_id, order_id, stage_id, entered_at, completed_at, status) "
            f"VALUES ({event_id}, {oid}, {stage_id}, "
            f"'{entered_str}', '{completed_str}', '{status}');"
        )
        event_id += 1

print("COMMIT;")
