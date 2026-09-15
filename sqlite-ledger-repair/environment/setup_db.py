#!/usr/bin/env python3
"""Generate the corrupted analytics database, audit data, and expected results.

This script runs during Docker build. It creates:
  /app/analytics.db         — corrupted database (solver's starting point)
  /app/expected.json        — ground truth query results (used ONLY by tests)
  /app/queries.sql          — the 5 report queries the business runs
  /app/audit_data.json      — partial ERP cross-validation data for the solver
  /app/schema_spec.md       — business rules / schema documentation
  /app/discrepancy_notes.txt — analyst's preliminary observations
"""
import sqlite3
import json
import random
import os

random.seed(42)
os.makedirs('/app', exist_ok=True)
DB = '/app/analytics.db'
if os.path.exists(DB):
    os.remove(DB)

conn = sqlite3.connect(DB)
c = conn.cursor()

# ══════════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════════

c.executescript("""
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    tier TEXT NOT NULL
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_cost REAL NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    channel TEXT NOT NULL
);
CREATE TABLE order_lines (
    line_id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount_pct REAL NOT NULL DEFAULT 0.0
);
CREATE TABLE inventory_log (
    log_id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    change_type TEXT NOT NULL,
    quantity_change INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    reference TEXT
);
CREATE TABLE daily_revenue (
    rev_date TEXT NOT NULL,
    category TEXT,
    revenue REAL NOT NULL,
    units_sold INTEGER NOT NULL,
    PRIMARY KEY (rev_date, category)
);
CREATE INDEX idx_ol_order ON order_lines(order_id);
CREATE INDEX idx_ol_product ON order_lines(product_id);
CREATE INDEX idx_inv_product ON inventory_log(product_id);
CREATE INDEX idx_inv_date ON inventory_log(log_date);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_cust ON orders(customer_id);
""")

# ══════════════════════════════════════════════════════════
# POPULATE DATA
# ══════════════════════════════════════════════════════════

# ── Customers: 50 ──
regions = ['North', 'South', 'East', 'West']
tiers = ['bronze', 'silver', 'gold', 'platinum']
fnames = [
    'James', 'Mary', 'Robert', 'Patricia', 'John', 'Jennifer', 'Michael',
    'Linda', 'David', 'Barbara', 'William', 'Elizabeth', 'Richard', 'Susan',
    'Joseph', 'Jessica', 'Thomas', 'Sarah', 'Christopher', 'Karen', 'Daniel',
    'Nancy', 'Matthew', 'Betty', 'Anthony', 'Margaret', 'Mark', 'Sandra',
    'Donald', 'Ashley',
]
lnames = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller',
    'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Wilson',
    'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin', 'Lee',
    'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez',
    'Lewis', 'Robinson', 'Walker',
]

for cid in range(1, 51):
    c.execute('INSERT INTO customers VALUES (?,?,?,?)', (
        cid,
        f'{random.choice(fnames)} {random.choice(lnames)}',
        random.choice(regions),
        random.choices(tiers, weights=[40, 30, 20, 10])[0],
    ))

# ── Products: 80 across 8 categories ──
categories = ['Electronics', 'Clothing', 'Home', 'Sports',
              'Books', 'Food', 'Toys', 'Office']
products_data = []
for pid in range(1, 81):
    cat = categories[(pid - 1) % 8]
    cost = round(random.uniform(5, 200), 2)
    sku = f'{cat[:3].upper()}-{pid:04d}'
    name = f'{cat} Item {pid}'
    products_data.append((pid, sku, name, cat, cost))
    c.execute('INSERT INTO products VALUES (?,?,?,?,?)',
              (pid, sku, name, cat, cost))

# ── Orders: 1500 with order_lines ──
channels = ['web', 'mobile', 'store', 'phone']
lid = 1
for oid in range(1, 1501):
    cid = random.randint(1, 50)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    dt = f'2024-{m:02d}-{d:02d}'
    status = random.choices(
        ['completed', 'cancelled', 'refunded'], weights=[85, 10, 5]
    )[0]
    ch = random.choice(channels)
    c.execute('INSERT INTO orders VALUES (?,?,?,?,?)',
              (oid, cid, dt, status, ch))

    n_items = random.choices([1, 2, 3, 4], weights=[30, 40, 20, 10])[0]
    for ppid in random.sample(range(1, 81), n_items):
        qty = random.randint(1, 10)
        price = round(products_data[ppid - 1][4] * random.uniform(1.2, 2.5), 2)
        disc = random.choices(
            [0.0, 0.05, 0.10, 0.15, 0.20], weights=[50, 20, 15, 10, 5]
        )[0]
        c.execute('INSERT INTO order_lines VALUES (?,?,?,?,?,?)',
                  (lid, oid, ppid, qty, price, disc))
        lid += 1

n_clean_lines = lid - 1

# ── Inventory log: 2000 entries ──
for logid in range(1, 2001):
    ppid = random.randint(1, 80)
    ct = random.choices(['in', 'out', 'adjustment'], weights=[40, 45, 15])[0]
    if ct == 'in':
        qc = random.randint(10, 500)
    elif ct == 'out':
        qc = -random.randint(1, 100)
    else:
        qc = random.randint(-50, 50)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    ld = f'2024-{m:02d}-{d:02d}'
    ref = f'REF-{logid:05d}' if ct != 'adjustment' else None
    c.execute('INSERT INTO inventory_log VALUES (?,?,?,?,?,?)',
              (logid, ppid, ct, qc, ld, ref))

# ── Daily revenue from clean order data ──
c.execute("""
    INSERT INTO daily_revenue (rev_date, category, revenue, units_sold)
    SELECT o.order_date, p.category,
           ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2),
           SUM(ol.quantity)
    FROM order_lines ol
    JOIN orders o ON ol.order_id = o.order_id
    JOIN products p ON ol.product_id = p.product_id
    WHERE o.status = 'completed'
    GROUP BY o.order_date, p.category
""")
n_daily_rev_clean = c.execute(
    'SELECT COUNT(*) FROM daily_revenue').fetchone()[0]

conn.commit()

# ══════════════════════════════════════════════════════════
# COMPUTE EXPECTED RESULTS (before corruption) — for tests
# ══════════════════════════════════════════════════════════

QUERIES = {
    'Q1': """
        SELECT p.category,
               ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue,
               SUM(ol.quantity) as total_units
        FROM order_lines ol
        JOIN orders o ON ol.order_id = o.order_id
        JOIN products p ON ol.product_id = p.product_id
        WHERE o.status = 'completed'
        GROUP BY p.category ORDER BY p.category
    """,
    'Q2': """
        SELECT c.tier,
               COUNT(DISTINCT o.order_id) as order_count,
               ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_lines ol ON o.order_id = ol.order_id
        WHERE o.status = 'completed'
        GROUP BY c.tier ORDER BY c.tier
    """,
    'Q3': """
        SELECT p.sku, p.name, SUM(il.quantity_change) as balance
        FROM products p
        JOIN inventory_log il ON p.product_id = il.product_id
        GROUP BY p.product_id ORDER BY p.sku
    """,
    'Q4': """
        SELECT p.category,
               COUNT(*) as line_count,
               SUM(ol.quantity) as total_quantity,
               ROUND(SUM(ol.unit_price * ol.quantity), 2) as gross_demand
        FROM order_lines ol
        JOIN products p ON ol.product_id = p.product_id
        GROUP BY p.category ORDER BY p.category
    """,
    'Q5': """
        SELECT strftime('%Y-%m', rev_date) as month,
               ROUND(SUM(revenue), 2) as total_revenue,
               SUM(units_sold) as total_units
        FROM daily_revenue
        GROUP BY strftime('%Y-%m', rev_date)
        ORDER BY month
    """,
}

expected = {}
for qname, qsql in QUERIES.items():
    rows = c.execute(qsql).fetchall()
    col_names = [desc[0] for desc in c.description]
    expected[qname] = [dict(zip(col_names, row)) for row in rows]

expected['counts'] = {
    'order_lines': n_clean_lines,
    'daily_revenue': n_daily_rev_clean,
    'inventory_log': 2000,
}

with open('/app/expected.json', 'w') as f:
    json.dump(expected, f, indent=2)

# ══════════════════════════════════════════════════════════
# GENERATE AUDIT DATA (before corruption) — solver's evidence
# ══════════════════════════════════════════════════════════

audit_data = {
    'description': 'Pre-migration audit snapshot exported from legacy ERP system. '
                   'Use this data to cross-validate the analytics database and '
                   'identify discrepancies.',
    'snapshot_date': '2024-11-30',
    'table_row_counts': {
        'customers': 50,
        'products': 80,
        'orders': 1500,
        'order_lines': n_clean_lines,
        'inventory_log': 2000,
        'daily_revenue': n_daily_rev_clean,
    },
    'aggregate_checksums': {
        'order_lines': {
            'sum_unit_price': round(c.execute(
                'SELECT SUM(unit_price) FROM order_lines').fetchone()[0], 4),
            'sum_quantity': c.execute(
                'SELECT SUM(quantity) FROM order_lines').fetchone()[0],
            'sum_discount_pct': round(c.execute(
                'SELECT SUM(discount_pct) FROM order_lines').fetchone()[0], 6),
            'count_with_discount': c.execute(
                'SELECT COUNT(*) FROM order_lines WHERE discount_pct > 0'
            ).fetchone()[0],
        },
        'inventory_log': {
            'sum_quantity_change': c.execute(
                'SELECT SUM(quantity_change) FROM inventory_log').fetchone()[0],
            'count_in': c.execute(
                "SELECT COUNT(*) FROM inventory_log WHERE change_type='in'"
            ).fetchone()[0],
            'count_out': c.execute(
                "SELECT COUNT(*) FROM inventory_log WHERE change_type='out'"
            ).fetchone()[0],
            'count_adjustment': c.execute(
                "SELECT COUNT(*) FROM inventory_log WHERE change_type='adjustment'"
            ).fetchone()[0],
        },
        'daily_revenue': {
            'sum_revenue': round(c.execute(
                'SELECT SUM(revenue) FROM daily_revenue').fetchone()[0], 2),
            'sum_units_sold': c.execute(
                'SELECT SUM(units_sold) FROM daily_revenue').fetchone()[0],
            'distinct_categories': c.execute(
                'SELECT COUNT(DISTINCT category) FROM daily_revenue').fetchone()[0],
        },
    },
    'sample_order_lines': [],
    'category_revenue_totals': [],
    'per_product_inventory_balance': [],
}

# Sample 30 order_lines with known-correct values
sample_ids = sorted(random.sample(range(1, n_clean_lines + 1), 30))
for sid in sample_ids:
    row = c.execute(
        'SELECT line_id, order_id, product_id, quantity, unit_price, discount_pct '
        'FROM order_lines WHERE line_id=?', (sid,)
    ).fetchone()
    audit_data['sample_order_lines'].append({
        'line_id': row[0],
        'order_id': row[1],
        'product_id': row[2],
        'quantity': row[3],
        'unit_price': round(row[4], 2),
        'discount_pct': round(row[5], 4),
    })

# Per-category revenue totals (completed orders)
cat_rev = c.execute("""
    SELECT p.category,
           ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue,
           SUM(ol.quantity) as total_units
    FROM order_lines ol
    JOIN orders o ON ol.order_id = o.order_id
    JOIN products p ON ol.product_id = p.product_id
    WHERE o.status = 'completed'
    GROUP BY p.category ORDER BY p.category
""").fetchall()
audit_data['category_revenue_totals'] = [
    {'category': r[0], 'revenue': r[1], 'total_units': r[2]} for r in cat_rev
]

# Per-product inventory balances
inv_bal = c.execute("""
    SELECT p.sku, p.product_id, SUM(il.quantity_change) as balance
    FROM products p
    JOIN inventory_log il ON p.product_id = il.product_id
    GROUP BY p.product_id ORDER BY p.sku
""").fetchall()
audit_data['per_product_inventory_balance'] = [
    {'sku': r[0], 'product_id': r[1], 'balance': r[2]} for r in inv_bal
]

with open('/app/audit_data.json', 'w') as f:
    json.dump(audit_data, f, indent=2)

# ══════════════════════════════════════════════════════════
# INJECT CORRUPTIONS
# ══════════════════════════════════════════════════════════

all_lids = list(range(1, n_clean_lines + 1))
random.shuffle(all_lids)

# ── C1: TEXT unit_price with currency formatting (40 rows) ──
text_price_ids = sorted(all_lids[:40])
rest_lids = all_lids[40:]


def fmt_price(v):
    r = random.random()
    if r < 0.5:
        return f'${v:,.2f}'
    else:
        return f'USD {v:.2f}'


for lid2 in text_price_ids:
    p = c.execute(
        'SELECT unit_price FROM order_lines WHERE line_id=?', (lid2,)
    ).fetchone()[0]
    c.execute('UPDATE order_lines SET unit_price=? WHERE line_id=?',
              (fmt_price(p), lid2))

# ── C2: Discount stored as percentage instead of fraction (25 rows) ──
disc_ids = []
for lid2 in rest_lids:
    if len(disc_ids) >= 25:
        break
    d = c.execute(
        'SELECT discount_pct FROM order_lines WHERE line_id=?', (lid2,)
    ).fetchone()[0]
    if d > 0:
        disc_ids.append(lid2)
disc_ids.sort()

for lid2 in disc_ids:
    d = c.execute(
        'SELECT discount_pct FROM order_lines WHERE line_id=?', (lid2,)
    ).fetchone()[0]
    c.execute('UPDATE order_lines SET discount_pct=? WHERE line_id=?',
              (d * 100.0, lid2))

# ── C3: Orphaned order_lines (15 new rows, non-existent order_ids) ──
for i in range(15):
    ppid = random.randint(1, 80)
    qty = random.randint(1, 10)
    pr = round(random.uniform(20, 150), 2)
    c.execute('INSERT INTO order_lines VALUES (?,?,?,?,?,?)',
              (n_clean_lines + 1 + i, 9001 + i, ppid, qty, pr, 0.0))

# ── C4: Sign flips in inventory_log (12 'in' or 'out' entries) ──
flip_candidates = [r[0] for r in c.execute(
    "SELECT log_id FROM inventory_log WHERE change_type IN ('in','out') "
    "ORDER BY log_id"
).fetchall()]
flip_ids = sorted(random.sample(flip_candidates, 12))
for fid in flip_ids:
    c.execute(
        'UPDATE inventory_log SET quantity_change=-quantity_change '
        'WHERE log_id=?', (fid,))

# ── C5: NULL category duplicates in daily_revenue (18 extra rows) ──
all_dr_dates = [r[0] for r in c.execute(
    'SELECT DISTINCT rev_date FROM daily_revenue ORDER BY rev_date'
).fetchall()]
dup_dates = sorted(random.sample(all_dr_dates, 18))
for rd in dup_dates:
    rev = round(random.uniform(50, 1500), 2)
    units = random.randint(3, 40)
    c.execute('INSERT INTO daily_revenue VALUES (?,?,?,?)',
              (rd, None, rev, units))

conn.commit()
conn.close()

# ══════════════════════════════════════════════════════════
# SAVE QUERIES FILE
# ══════════════════════════════════════════════════════════

queries_sql = """-- Q1: Revenue by category (completed orders)
SELECT p.category,
       ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue,
       SUM(ol.quantity) as total_units
FROM order_lines ol
JOIN orders o ON ol.order_id = o.order_id
JOIN products p ON ol.product_id = p.product_id
WHERE o.status = 'completed'
GROUP BY p.category ORDER BY p.category;

-- Q2: Revenue by customer tier (completed orders)
SELECT c.tier,
       COUNT(DISTINCT o.order_id) as order_count,
       ROUND(SUM(ol.unit_price * ol.quantity * (1.0 - ol.discount_pct)), 2) as revenue
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_lines ol ON o.order_id = ol.order_id
WHERE o.status = 'completed'
GROUP BY c.tier ORDER BY c.tier;

-- Q3: Inventory balance by product
SELECT p.sku, p.name, SUM(il.quantity_change) as balance
FROM products p
JOIN inventory_log il ON p.product_id = il.product_id
GROUP BY p.product_id ORDER BY p.sku;

-- Q4: Product demand by category (all line items)
SELECT p.category,
       COUNT(*) as line_count,
       SUM(ol.quantity) as total_quantity,
       ROUND(SUM(ol.unit_price * ol.quantity), 2) as gross_demand
FROM order_lines ol
JOIN products p ON ol.product_id = p.product_id
GROUP BY p.category ORDER BY p.category;

-- Q5: Daily revenue monthly summary
SELECT strftime('%Y-%m', rev_date) as month,
       ROUND(SUM(revenue), 2) as total_revenue,
       SUM(units_sold) as total_units
FROM daily_revenue
GROUP BY strftime('%Y-%m', rev_date)
ORDER BY month;
"""

with open('/app/queries.sql', 'w') as f:
    f.write(queries_sql)

# ══════════════════════════════════════════════════════════
# SAVE SCHEMA SPEC
# ══════════════════════════════════════════════════════════

schema_spec = """# Analytics Database — Schema Specification & Business Rules

## Overview

This database tracks e-commerce order data, inventory movements, and revenue
summaries. It was migrated from a legacy ERP system.

## Table Definitions & Constraints

### customers
| Column      | Type    | Constraint          |
|-------------|---------|---------------------|
| customer_id | INTEGER | PRIMARY KEY         |
| name        | TEXT    | NOT NULL            |
| region      | TEXT    | NOT NULL            |
| tier        | TEXT    | NOT NULL, one of: bronze, silver, gold, platinum |

### products
| Column     | Type    | Constraint          |
|------------|---------|---------------------|
| product_id | INTEGER | PRIMARY KEY         |
| sku        | TEXT    | NOT NULL, UNIQUE    |
| name       | TEXT    | NOT NULL            |
| category   | TEXT    | NOT NULL            |
| unit_cost  | REAL    | NOT NULL, >= 0      |

### orders
| Column      | Type    | Constraint          |
|-------------|---------|---------------------|
| order_id    | INTEGER | PRIMARY KEY         |
| customer_id | INTEGER | FK -> customers     |
| order_date  | TEXT    | NOT NULL, ISO-8601  |
| status      | TEXT    | NOT NULL, one of: completed, cancelled, refunded |
| channel     | TEXT    | NOT NULL            |

### order_lines
| Column      | Type    | Constraint          |
|-------------|---------|---------------------|
| line_id     | INTEGER | PRIMARY KEY         |
| order_id    | INTEGER | FK -> orders        |
| product_id  | INTEGER | FK -> products      |
| quantity    | INTEGER | NOT NULL, > 0       |
| unit_price  | REAL    | NOT NULL, >= 0      |
| discount_pct| REAL    | NOT NULL, DEFAULT 0.0 |

**Business rule — discount_pct**: Represents a *fractional* discount.
`0.0` = no discount, `0.10` = 10% off, `0.20` = 20% off. Valid range is
`[0.0, 1.0]`. The revenue formula is:
`unit_price * quantity * (1.0 - discount_pct)`.

**Business rule — unit_price**: Must always be stored as a numeric type
(REAL or INTEGER). Never as formatted text.

**Business rule — referential integrity**: Every `order_id` in order_lines
MUST reference a valid row in the `orders` table. order_lines exist for ALL
order statuses (completed, cancelled, refunded).

### inventory_log
| Column          | Type    | Constraint          |
|-----------------|---------|---------------------|
| log_id          | INTEGER | PRIMARY KEY         |
| product_id      | INTEGER | FK -> products      |
| change_type     | TEXT    | NOT NULL            |
| quantity_change  | INTEGER | NOT NULL           |
| log_date        | TEXT    | NOT NULL            |
| reference       | TEXT    | nullable            |

**Business rule — sign convention**:
- `change_type = 'in'`: `quantity_change` MUST be **positive** (goods received)
- `change_type = 'out'`: `quantity_change` MUST be **negative** (goods shipped)
- `change_type = 'adjustment'`: `quantity_change` may be positive or negative

### daily_revenue
| Column     | Type    | Constraint          |
|------------|---------|---------------------|
| rev_date   | TEXT    | NOT NULL            |
| category   | TEXT    | part of PK          |
| revenue    | REAL    | NOT NULL            |
| units_sold | INTEGER | NOT NULL            |

**Composite primary key**: `(rev_date, category)`. Each date+category pair
should appear exactly once. `category` MUST NOT be NULL.

**Business rule**: This table contains aggregated revenue from *completed*
orders, grouped by date and product category.

## Foreign Key Policy

All declared foreign key relationships must be enforced. No orphaned
references should exist in the database.

## Data Types

SQLite uses dynamic typing with type affinity. Columns declared as REAL
should contain numeric values, not formatted text strings. The `typeof()`
function can be used to verify actual storage types.
"""

with open('/app/schema_spec.md', 'w') as f:
    f.write(schema_spec)

# ══════════════════════════════════════════════════════════
# SAVE DISCREPANCY NOTES
# ══════════════════════════════════════════════════════════

discrepancy_notes = """Discrepancy Report — Analytics Database Audit
Analyst: J. Chen, Data Quality Team
Date: 2024-12-05
Status: Unresolved — escalated for forensic analysis

------------------------------------------------------------------------

CONTEXT:
  The analytics database was bulk-imported from the legacy ERP on 2024-12-01.
  PRAGMA integrity_check returns 'ok'. Schema structure appears intact.
  However, five standard report queries (see queries.sql) produce results
  that diverge from the verified ERP totals.

OBSERVATIONS:

  1. REVENUE UNDERCOUNT: Q1 (revenue by category) shows revenue significantly
     below ERP figures for several categories. The shortfall is not uniform —
     some categories are affected more than others. Hypothesis: some line
     items may not be contributing their full price to revenue calculations,
     or may be contributing zero.

  2. NEGATIVE REVENUE ANOMALY: Q2 (revenue by tier) produces implausible
     negative revenue values for some tiers. The per-order revenue average
     varies wildly, suggesting a multiplicative error in the revenue formula
     for certain line items.

  3. INVENTORY IMBALANCE: Q3 (inventory balance) shows balances that diverge
     from physical warehouse counts. Some products show balances much lower
     than expected; others are higher. The errors seem to involve direction
     (sign) rather than magnitude.

  4. INFLATED DEMAND: Q4 (product demand) reports higher line item counts
     and quantities than the ERP source. The inflation is consistent across
     categories, suggesting extra rows rather than incorrect values in
     existing rows.

  5. MONTHLY OVERCOUNT: Q5 (monthly revenue summary) produces totals that
     exceed what's derivable from the order data alone. Additional spurious
     rows may exist in the summary table.

NOTE: These issues interact. Fixing one issue in isolation may change the
symptoms of another. A systematic, ordered approach to diagnosis and repair
is recommended.

PRAGMA integrity_check: ok
PRAGMA foreign_key_check: not run (foreign_keys pragma was off at import time)
"""

with open('/app/discrepancy_notes.txt', 'w') as f:
    f.write(discrepancy_notes)

print(f'Setup complete: {n_clean_lines} clean lines, '
      f'{n_daily_rev_clean} daily_revenue entries')
print(f'Corruptions: 40 text prices, 25 bad discounts, '
      f'15 orphaned, 12 sign flips, 18 null dupes')
