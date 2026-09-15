#!/usr/bin/env python3
"""Generate the analytics database with embedded data-integrity issues and DBA damage."""

import sqlite3
import random
import json
import calendar
import shutil

random.seed(42)

DB_PATH = '/app/analytics.db'

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = OFF")
cur = conn.cursor()

# ===================== SCHEMA =====================

cur.executescript('''
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    tier TEXT,
    region TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id)
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    price REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    user_id INTEGER REFERENCES users(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    event_data TEXT,
    occurred_at TEXT NOT NULL
);

-- ISSUE: monthly_revenue view exploits SQLite Quirk #6.
-- GROUP BY month only; product_id and product_name are bare (non-aggregate)
-- columns not in the GROUP BY clause. SQLite returns arbitrary values for them
-- rather than raising an error as most other SQL engines would.
CREATE VIEW monthly_revenue AS
SELECT
    strftime('%Y-%m', o.order_date) AS month,
    p.id AS product_id,
    p.name AS product_name,
    SUM(oi.quantity * oi.unit_price) AS total_revenue,
    COUNT(oi.id) AS item_count
FROM order_items oi
JOIN orders o ON oi.order_id = o.id
JOIN products p ON oi.product_id = p.id
GROUP BY month;

-- ISSUE: product_best_review view uses separate correlated subqueries.
-- MAX(rating) is computed correctly, but the detail columns (comment, user_id,
-- created_at) come from a DIFFERENT subquery that returns the FIRST review
-- by rowid (ORDER BY r.id LIMIT 1), not the review with the highest rating.
CREATE VIEW product_best_review AS
SELECT
    p.id AS product_id,
    (SELECT MAX(r.rating) FROM reviews r WHERE r.product_id = p.id) AS best_rating,
    (SELECT r.comment FROM reviews r WHERE r.product_id = p.id ORDER BY r.id LIMIT 1) AS best_comment,
    (SELECT r.user_id FROM reviews r WHERE r.product_id = p.id ORDER BY r.id LIMIT 1) AS reviewer_id,
    (SELECT r.created_at FROM reviews r WHERE r.product_id = p.id ORDER BY r.id LIMIT 1) AS review_date
FROM products p
WHERE EXISTS (SELECT 1 FROM reviews r WHERE r.product_id = p.id);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_reviews_product ON reviews(product_id);
CREATE INDEX idx_reviews_product_rating ON reviews(product_id, rating);
CREATE INDEX idx_events_user ON events(user_id);
CREATE INDEX idx_events_date ON events(occurred_at);
''')

# ===================== HELPER FUNCTIONS =====================

regions = ['NA', 'EU', 'APAC', 'LATAM']
tiers = ['free', 'basic', 'premium', 'enterprise']


def make_date(year, month, day, hour=0, minute=0, second=0):
    return f'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}'


def random_date(start_year=2023, end_year=2024):
    y = random.randint(start_year, end_year)
    mo = random.randint(1, 12)
    d = random.randint(1, 28)
    h = random.randint(0, 23)
    mi = random.randint(0, 59)
    s = random.randint(0, 59)
    return make_date(y, mo, d, h, mi, s)


def iso_to_us(date_str):
    """'YYYY-MM-DD HH:MM:SS' -> 'MM/DD/YYYY HH:MM:SS'"""
    parts = date_str.split(' ')
    ymd = parts[0].split('-')
    return f'{ymd[1]}/{ymd[2]}/{ymd[0]} {parts[1]}'


def iso_to_unix(date_str):
    """'YYYY-MM-DD HH:MM:SS' -> unix timestamp string (10 digits)"""
    import time
    st = time.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    return str(int(calendar.timegm(st)))


def iso_to_epoch_ms(date_str):
    """'YYYY-MM-DD HH:MM:SS' -> epoch-millisecond timestamp (13 digits)"""
    import time
    st = time.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    return str(int(calendar.timegm(st)) * 1000 + random.randint(1, 999))


# ===================== DATA =====================

# --- Users: 100 total, will delete 96-100 to create orphaned orders ---
for i in range(1, 101):
    cur.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?)",
        (i, f'user_{i}', f'user_{i}@example.com',
         random.choice(tiers), random.choice(regions), random_date())
    )

# --- Categories: 20 total, CYCLE: 14->16->15->14 ---
cat_names = [
    'Electronics', 'Computers', 'Laptops', 'Desktops', 'Tablets',
    'Phones', 'Media', 'Audio', 'Video', 'Gaming',
    'Software', 'Books', 'Clothing',
    'Home & Garden', 'Kitchen', 'Patio',
    'Furniture', 'Outdoor Living', 'Appliances', 'Planters'
]

hierarchy = {
    1: None, 2: 1, 3: 2, 4: 2, 5: 1,
    6: 1, 7: None, 8: 7, 9: 7, 10: 7,
    11: None, 12: None, 13: None,
    14: 16,    # Home & Garden -> Patio (CYCLE)
    15: 14,    # Kitchen -> Home & Garden
    16: 15,    # Patio -> Kitchen (completes cycle: 14->16->15->14)
    17: 14,    # Furniture -> Home & Garden (child of cycle node)
    18: 15,    # Outdoor Living -> Kitchen (child of cycle node)
    19: 16,    # Appliances -> Patio (child of cycle node)
    20: 18,    # Planters -> Outdoor Living (grandchild of cycle)
}

for i in range(1, 21):
    cur.execute("INSERT INTO categories VALUES (?,?,?)",
                (i, cat_names[i - 1], hierarchy[i]))

# --- Products: 50 total, will delete 46-50 to create orphans ---
prod_statuses = ['active', 'active', 'active', 'discontinued', 'draft']
for i in range(1, 51):
    cur.execute(
        "INSERT INTO products VALUES (?,?,?,?,?,?)",
        (i, f'Product_{i}', random.randint(1, 13),
         round(random.uniform(9.99, 999.99), 2),
         random.choice(prod_statuses), random_date())
    )

# --- Orders: 500 total ---
order_statuses = ['completed', 'completed', 'completed',
                  'pending', 'shipped', 'cancelled']
for i in range(1, 501):
    if i <= 450:
        uid = random.randint(1, 95)
    else:
        uid = random.randint(96, 100)   # orphaned user
    cur.execute(
        "INSERT INTO orders VALUES (?,?,?,?)",
        (i, uid, random_date(), random.choice(order_statuses))
    )

# --- Order Items: exactly 600 (1 per order, 2 for every 5th order) ---
item_id = 1
for oid in range(1, 501):
    n_items = 2 if (oid % 5 == 0) else 1
    for j in range(n_items):
        if oid <= 470:
            pid = random.randint(1, 45)
        else:
            pid = random.choice([46, 47, 48, 49, 50])   # orphaned product
        qty = random.randint(1, 5)
        price = round(random.uniform(9.99, 299.99), 2)
        cur.execute(
            "INSERT INTO order_items VALUES (?,?,?,?,?)",
            (item_id, oid, pid, qty, price)
        )
        item_id += 1

# --- Reviews: structured so the correlated-subquery bug is deterministic ---
review_id = 1
for pid in range(1, 46):
    # FIRST review (lowest id): always rating 1
    uid = random.randint(1, 95)
    cur.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        (review_id, pid, uid, 1,
         'Terrible product, very disappointed. Would not buy again.',
         make_date(2023, 1, random.randint(1, 28),
                   random.randint(0, 23), random.randint(0, 59),
                   random.randint(0, 59)))
    )
    review_id += 1

    # Middle reviews: ratings 2-4
    for _ in range(random.randint(3, 6)):
        uid2 = random.randint(1, 95)
        rating = random.choice([2, 3, 3, 4])
        cur.execute(
            "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
            (review_id, pid, uid2, rating,
             f'Decent product overall. Rating {rating}/5.',
             make_date(2023, random.randint(3, 10),
                       random.randint(1, 28),
                       random.randint(0, 23), random.randint(0, 59),
                       random.randint(0, 59)))
        )
        review_id += 1

    # LAST review (highest id): always rating 5
    uid3 = random.randint(1, 95)
    cur.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        (review_id, pid, uid3, 5,
         'Outstanding product! Best purchase I ever made. Highly recommend.',
         make_date(2024, random.randint(1, 12),
                   random.randint(1, 28),
                   random.randint(0, 23), random.randint(0, 59),
                   random.randint(0, 59)))
    )
    review_id += 1

# --- Events: 1000 events with FOUR date formats ---
event_types = ['page_view', 'add_to_cart', 'purchase',
               'search', 'login', 'logout']
for eid in range(1, 1001):
    uid = random.randint(1, 100)
    etype = random.choice(event_types)
    iso_date = random_date()

    if etype == 'page_view':
        data = json.dumps({"page": f"/products/{random.randint(1, 45)}",
                           "duration_ms": random.randint(100, 30000)})
    elif etype == 'search':
        data = json.dumps({"query": random.choice(
            ["laptop", "phone", "tablet", "headphones"]),
            "results_count": random.randint(0, 50)})
    elif etype == 'purchase':
        data = json.dumps({"order_id": random.randint(1, 500),
                           "amount": round(random.uniform(10, 1000), 2)})
    else:
        data = json.dumps({"action": etype})

    # Four date formats depending on event range
    if eid <= 600:
        date_str = iso_date                   # ISO-8601
    elif eid <= 750:
        date_str = iso_to_us(iso_date)        # US: MM/DD/YYYY HH:MM:SS
    elif eid <= 900:
        date_str = iso_to_unix(iso_date)      # Unix timestamp (10 digits)
    else:
        date_str = iso_to_epoch_ms(iso_date)  # Epoch milliseconds (13 digits)

    cur.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                (eid, uid, etype, data, date_str))

# --- Create orphans by deleting referenced records ---
cur.execute("DELETE FROM users WHERE id BETWEEN 96 AND 100")
cur.execute("DELETE FROM products WHERE id BETWEEN 46 AND 50")

conn.commit()

# =================================================================
# Save backup BEFORE DBA damage (for agent reference / comparison)
# =================================================================
shutil.copy(DB_PATH, f'{DB_PATH}.bak')

# =================================================================
# Simulate DBA's attempted repairs (introduces additional problems)
# =================================================================

# DBA fix 1: tried to break category cycle at node 14.
# TYPO: wrote "SET parent_id = 14" instead of "SET parent_id = NULL"
# Result: node 14 becomes self-referencing (parent_id = 14)
cur.execute("UPDATE categories SET parent_id = 14 WHERE id = 14")

# DBA fix 2: broke one cycle link by making node 16 a root
cur.execute("UPDATE categories SET parent_id = NULL WHERE id = 16")

# DBA fix 3: inserted placeholder products with NON-EXISTENT category_ids
cur.execute(
    "INSERT INTO products VALUES "
    "(51, '_dba_placeholder_a', 99, 0.0, 'archived', '2024-01-01 00:00:00')")
cur.execute(
    "INSERT INTO products VALUES "
    "(52, '_dba_placeholder_b', 88, 0.0, 'archived', '2024-01-01 00:00:00')")

# DBA fix 4: ran ANALYZE during partial migration, then manually edited stats
# to "speed up" queries — corrupts the query planner's cost estimates
cur.execute("ANALYZE")
cur.execute("DELETE FROM sqlite_stat1")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('reviews', 'idx_reviews_product_rating', '50 50 50')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('reviews', 'idx_reviews_product', '50 50')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('order_items', 'idx_order_items_product', '10 10')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('order_items', 'idx_order_items_order', '10 10')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('orders', 'idx_orders_user', '50 50')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('orders', 'idx_orders_date', '50 50')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('events', 'idx_events_user', '50 50')")
cur.execute(
    "INSERT INTO sqlite_stat1 VALUES "
    "('events', 'idx_events_date', '50 50')")

conn.commit()

# Save the full initial state (with DBA damage) for test repeatability
shutil.copy(DB_PATH, f'{DB_PATH}.initial')

# Print summary
total_reviews = cur.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
total_oi = cur.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
print(f"Database created at {DB_PATH}")
print(f"  Users: 95 (5 deleted -> orphaned orders)")
print(f"  Categories: 20 (cycle 14->16->15->14 + DBA self-ref at 14, DBA root at 16)")
print(f"  Products: 47 (45 original + 2 DBA with bad category_id)")
print(f"  Orders: 500 (50 with orphaned user_id)")
print(f"  Order Items: {total_oi}")
print(f"  Reviews: {total_reviews}")
print(f"  Events: 1000 (4 date formats: ISO, US, unix-sec, epoch-ms)")
print(f"  sqlite_stat1: manually corrupted")

conn.close()
