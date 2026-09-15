#!/usr/bin/env python3
"""Generate the test database with sales data and shard tables."""
import duckdb
import random
from datetime import date, timedelta

random.seed(42)

conn = duckdb.connect('/app/warehouse.duckdb')

conn.execute("""
CREATE TABLE sales (
    id INTEGER,
    region VARCHAR,
    product VARCHAR,
    quantity INTEGER,
    price DOUBLE,
    discount DOUBLE,
    sale_date DATE,
    shard_id INTEGER
)
""")

regions = ['North', 'South', 'East', 'West']
products = ['Widget', 'Gadget', 'Doohickey', 'Thingamajig', 'Whatchamacallit']
region_price_mult = {'North': 1.5, 'South': 0.6, 'East': 1.0, 'West': 1.2}
base_date = date(2024, 1, 1)

batch = []
for i in range(10000):
    region = random.choice(regions)
    product = random.choice(products)
    quantity = random.randint(1, 100)
    base_price = random.uniform(10.0, 400.0)
    price = round(base_price * region_price_mult[region], 2)
    discount = round(random.uniform(0.0, 0.5), 4)
    day_offset = random.randint(0, 364)
    sale_date = (base_date + timedelta(days=day_offset)).isoformat()
    shard_id = i % 4
    batch.append((i, region, product, quantity, price, discount, sale_date, shard_id))

conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)

for s in range(4):
    conn.execute(f"""
    CREATE TABLE shard_{s} AS
    SELECT id, region, product, quantity, price, discount, sale_date
    FROM sales WHERE shard_id = {s}
    """)

conn.close()
print("Database setup complete: /app/warehouse.duckdb")
