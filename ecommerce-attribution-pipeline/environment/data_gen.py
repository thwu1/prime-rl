#!/usr/bin/env python3
"""Generate deterministic e-commerce database for analytics pipeline task."""
import duckdb
import random
from datetime import datetime, timedelta

random.seed(42)

conn = duckdb.connect('/app/ecommerce.duckdb')

conn.execute("""CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    signup_date DATE NOT NULL,
    country VARCHAR NOT NULL,
    acquisition_channel VARCHAR NOT NULL
)""")

conn.execute("""CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    base_price DECIMAL(10,2) NOT NULL
)""")

conn.execute("""CREATE TABLE sessions (
    session_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    channel VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL
)""")

conn.execute("""CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR NOT NULL
)""")

conn.execute("""CREATE TABLE order_items (
    item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL
)""")

conn.execute("""CREATE TABLE refunds (
    refund_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    refunded_at TIMESTAMP NOT NULL,
    reason VARCHAR NOT NULL,
    refund_amount DECIMAL(10,2) NOT NULL
)""")

# Force checkpoint after table creation to persist schema to main DB file
conn.execute("CHECKPOINT")

CHANNELS = ['organic', 'paid_search', 'social', 'email', 'referral', 'direct']
COUNTRIES = ['US', 'UK', 'DE', 'FR', 'JP', 'CA', 'AU']
CATEGORIES = ['Electronics', 'Clothing', 'Home & Garden', 'Books', 'Sports']
RETURN_REASONS = ['defective', 'wrong_size', 'not_as_described', 'changed_mind', 'arrived_late']
MAX_TS = datetime(2023, 12, 31, 23, 59, 59)

# 50 products with deterministic prices
products = []
for i in range(1, 51):
    price = round(15.0 + ((i * 7 + 13) % 47) * 4.25, 2)
    products.append((i, 'Product_%03d' % i, CATEGORIES[(i - 1) % 5], price))
conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

# 300 users signing up throughout 2023
users = []
for i in range(1, 301):
    signup = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 364))
    users.append((i, signup, COUNTRIES[random.randint(0, 6)], CHANNELS[random.randint(0, 5)]))
conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?)",
    [(u[0], u[1].strftime('%Y-%m-%d'), u[2], u[3]) for u in users])

# 3-20 sessions per user across various channels
sessions = []
sid = 0
for uid, signup, _, _ in users:
    days_left = max(0, (MAX_TS - signup).days)
    n = random.randint(3, 20)
    for _ in range(n):
        sid += 1
        d = random.randint(0, min(300, days_left))
        h = random.randint(0, 23)
        m = random.randint(0, 59)
        ts = min(signup + timedelta(days=d, hours=h, minutes=m), MAX_TS)
        sessions.append((sid, uid, CHANNELS[random.randint(0, 5)], ts))
conn.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)",
    [(s[0], s[1], s[2], s[3].strftime('%Y-%m-%d %H:%M:%S')) for s in sessions])

# Orders: ~12% session conversion, ~85% completed
orders = []
items = []
oid = 0
iid = 0
for s_id, u_id, ch, started in sessions:
    if random.random() < 0.12:
        oid += 1
        created = min(started + timedelta(minutes=random.randint(5, 60)), MAX_TS)
        n_items = random.randint(1, 4)
        total = 0.0
        for _ in range(n_items):
            iid += 1
            p = products[random.randint(0, 49)]
            qty = random.randint(1, 3)
            total += qty * p[3]
            items.append((iid, oid, p[0], qty, p[3]))
        status = 'completed' if random.random() < 0.85 else 'refunded'
        orders.append((oid, u_id, s_id, created, round(total, 2), status))

conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
    [(o[0], o[1], o[2], o[3].strftime('%Y-%m-%d %H:%M:%S'), o[4], o[5]) for o in orders])
conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)

# Refunds: ~20% of completed orders have 1-2 items returned (full item refund)
order_items_map = {}
for item in items:
    order_items_map.setdefault(item[1], []).append(item)

refunds_data = []
rid = 0
for order in orders:
    if order[5] == 'completed' and random.random() < 0.20:
        order_item_list = order_items_map.get(order[0], [])
        if not order_item_list:
            continue
        n_returns = min(random.randint(1, 2), len(order_item_list))
        returned_items = random.sample(order_item_list, n_returns)
        for item in returned_items:
            rid += 1
            refunded_at = order[3] + timedelta(days=random.randint(3, 30))
            refund = round(item[3] * item[4], 2)
            refunds_data.append((rid, order[0], item[0], refunded_at,
                                 RETURN_REASONS[random.randint(0, 4)], refund))

conn.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)",
    [(r[0], r[1], r[2], r[3].strftime('%Y-%m-%d %H:%M:%S'), r[4], r[5])
     for r in refunds_data])

# Promotional credits — pre-sale discounts already factored into order total_amount.
# These should NOT be further subtracted from revenue (distractor table).
conn.execute("""CREATE TABLE promotional_credits (
    credit_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    credit_type VARCHAR NOT NULL,
    credit_amount DECIMAL(10,2) NOT NULL,
    applied_at TIMESTAMP NOT NULL
)""")

CREDIT_TYPES = ['coupon', 'loyalty_points', 'flash_sale', 'referral_bonus']
promo_data = []
pcid = 0
for order in orders:
    if order[5] == 'completed' and random.random() < 0.15:
        pcid += 1
        ctype = CREDIT_TYPES[random.randint(0, 3)]
        camount = round(random.uniform(3.0, 30.0), 2)
        # applied_at is BEFORE order creation — indicates pre-sale discount
        applied_at = order[3] - timedelta(minutes=random.randint(1, 10))
        promo_data.append((pcid, order[0], ctype, camount, applied_at))

conn.executemany("INSERT INTO promotional_credits VALUES (?, ?, ?, ?, ?)",
    [(p[0], p[1], p[2], p[3], p[4].strftime('%Y-%m-%d %H:%M:%S'))
     for p in promo_data])

# Force checkpoint to flush WAL to main database file before closing
conn.execute("CHECKPOINT")

# Verify all tables exist
tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()
table_names = [t[0] for t in tables]
assert 'refunds' in table_names, f"refunds table missing! Found: {table_names}"
assert 'promotional_credits' in table_names, f"promotional_credits table missing! Found: {table_names}"
assert len(table_names) == 7, f"Expected 7 tables, found {len(table_names)}: {table_names}"

refund_count = conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]
assert refund_count > 0, "refunds table is empty!"

conn.close()
print("DB: %d users, %d sessions, %d orders, %d items, %d refunds, %d promo_credits" %
      (len(users), len(sessions), len(orders), len(items), len(refunds_data), len(promo_data)))
print("Tables verified: %s" % ', '.join(table_names))
