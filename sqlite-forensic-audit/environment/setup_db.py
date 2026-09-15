#!/usr/bin/env python3
"""Create warehouse.db with embedded SQLite-specific data integrity issues."""

import sqlite3
import json
import os

os.makedirs('/app', exist_ok=True)
conn = sqlite3.connect('/app/warehouse.db')
c = conn.cursor()
c.execute("PRAGMA foreign_keys = OFF")

# --- Schema ---
# Note: unit_price and quantity columns intentionally have NO declared type,
# giving them BLOB affinity (no automatic type conversion on insert).
# This allows mixed-type storage that mirrors real-world SQLite misuse.

c.execute('''CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER
)''')

c.execute('''CREATE TABLE warehouses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT
)''')

c.execute('''CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category_id INTEGER,
    unit_price,
    metadata TEXT
)''')

c.execute('''CREATE TABLE inventory (
    id INTEGER PRIMARY KEY,
    product_id INTEGER,
    warehouse_id INTEGER,
    lot_number TEXT,
    quantity,
    received_date TEXT,
    UNIQUE(product_id, warehouse_id, lot_number)
)''')

c.execute('''CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    inventory_id INTEGER,
    tx_type TEXT,
    quantity INTEGER,
    tx_date TEXT,
    notes TEXT
)''')

# --- Categories (hierarchical tree, max depth = 5) ---
categories = [
    (1, 'Electronics', None),
    (2, 'Computers', 1),
    (3, 'Laptops', 2),
    (4, 'Gaming Laptops', 3),
    (5, 'Budget Gaming', 4),
    (6, 'Phones', 1),
    (7, 'Smartphones', 6),
    (8, 'Clothing', None),
    (9, 'Mens', 8),
    (10, 'Outerwear', 9),
    (11, 'Accessories', None),
    (12, 'Watches', 11),
    (13, 'Smart Watches', 12),
]
c.executemany('INSERT INTO categories VALUES (?, ?, ?)', categories)

# --- Warehouses ---
c.executemany('INSERT INTO warehouses VALUES (?, ?, ?)', [
    (1, 'West Coast Hub', 'WEST'),
    (2, 'East Coast Hub', 'EAST'),
    (3, 'Central Depot', 'CENTRAL'),
])

# --- Products ---
# Products 1-20: Normal (REAL prices, matching JSON metadata)
products_normal = [
    (1, 'SKU-0001', 'Laptop Pro 15', 3, 1299.99, {"list_price": 1299.99, "supplier": "TechCo", "weight_kg": 2.1}),
    (2, 'SKU-0002', 'Gaming Beast X1', 4, 2499.50, {"list_price": 2499.50, "supplier": "GameTech", "weight_kg": 3.5}),
    (3, 'SKU-0003', 'Phone Ultra', 7, 899.00, {"list_price": 899.00, "supplier": "MobileCo", "weight_kg": 0.2}),
    (4, 'SKU-0004', 'Budget Phone', 6, 199.99, {"list_price": 199.99, "supplier": "MobileCo", "weight_kg": 0.18}),
    (5, 'SKU-0005', 'Desktop Tower', 2, 1599.00, {"list_price": 1599.00, "supplier": "TechCo", "weight_kg": 12.0}),
    (6, 'SKU-0006', 'Smart Watch Pro', 13, 449.99, {"list_price": 449.99, "supplier": "WatchCo", "weight_kg": 0.05}),
    (7, 'SKU-0007', 'Classic Watch', 12, 299.00, {"list_price": 299.00, "supplier": "WatchCo", "weight_kg": 0.08}),
    (8, 'SKU-0008', 'Winter Jacket', 10, 189.50, {"list_price": 189.50, "supplier": "ClothCo", "weight_kg": 1.2}),
    (9, 'SKU-0009', 'Polo Shirt', 9, 59.99, {"list_price": 59.99, "supplier": "ClothCo", "weight_kg": 0.3}),
    (10, 'SKU-0010', 'USB Hub', 11, 29.99, {"list_price": 29.99, "supplier": "AccessCo", "weight_kg": 0.1}),
    (11, 'SKU-0011', 'Wireless Mouse', 11, 49.99, {"list_price": 49.99, "supplier": "AccessCo", "weight_kg": 0.08}),
    (12, 'SKU-0012', 'Keyboard Pro', 2, 149.99, {"list_price": 149.99, "supplier": "TechCo", "weight_kg": 0.9}),
    (13, 'SKU-0013', 'Monitor 27in', 2, 549.00, {"list_price": 549.00, "supplier": "TechCo", "weight_kg": 6.5}),
    (14, 'SKU-0014', 'Tablet 10in', 1, 399.99, {"list_price": 399.99, "supplier": "TechCo", "weight_kg": 0.5}),
    (15, 'SKU-0015', 'Earbuds Pro', 11, 179.99, {"list_price": 179.99, "supplier": "AudioCo", "weight_kg": 0.02}),
    (16, 'SKU-0016', 'Gaming Chair', 4, 349.00, {"list_price": 349.00, "supplier": "FurnCo", "weight_kg": 25.0}),
    (17, 'SKU-0017', 'Dress Shirt', 9, 79.99, {"list_price": 79.99, "supplier": "ClothCo", "weight_kg": 0.25}),
    (18, 'SKU-0018', 'Rain Coat', 10, 129.99, {"list_price": 129.99, "supplier": "ClothCo", "weight_kg": 0.8}),
    (19, 'SKU-0019', 'Budget Laptop', 5, 599.99, {"list_price": 599.99, "supplier": "ValueTech", "weight_kg": 2.3}),
    (20, 'SKU-0020', 'Phone Case', 11, 19.99, {"list_price": 19.99, "supplier": "AccessCo", "weight_kg": 0.05}),
]
for pid, sku, name, cat, price, meta in products_normal:
    c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
              (pid, sku, name, cat, price, json.dumps(meta)))

# Products 21-25: JSON discrepancy (list_price != unit_price by > 0.01)
products_discrepant = [
    (21, 'SKU-0021', 'Headphones X', 1, 199.99, {"list_price": 249.99, "supplier": "AudioCo", "weight_kg": 0.3}),
    (22, 'SKU-0022', 'Webcam HD', 2, 89.99, {"list_price": 109.99, "supplier": "TechCo", "weight_kg": 0.15}),
    (23, 'SKU-0023', 'Fitness Band', 13, 79.99, {"list_price": 99.99, "supplier": "WatchCo", "weight_kg": 0.03}),
    (24, 'SKU-0024', 'Power Bank', 11, 39.99, {"list_price": 49.99, "supplier": "AccessCo", "weight_kg": 0.25}),
    (25, 'SKU-0025', 'Cable Kit', 11, 24.99, {"list_price": 34.99, "supplier": "AccessCo", "weight_kg": 0.15}),
]
for pid, sku, name, cat, price, meta in products_discrepant:
    c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
              (pid, sku, name, cat, price, json.dumps(meta)))

# Products 26-28: unit_price stored as TEXT string (type affinity quirk)
# Because unit_price column has BLOB affinity, Python str stays as SQLite TEXT
products_text_price = [
    (26, 'SKU-0026', 'Screen Protector', 11, '14.99', {"list_price": 14.99, "supplier": "AccessCo", "weight_kg": 0.01}),
    (27, 'SKU-0027', 'Mouse Pad XL', 11, '24.50', {"list_price": 24.50, "supplier": "AccessCo", "weight_kg": 0.4}),
    (28, 'SKU-0028', 'Laptop Stand', 2, '79.99', {"list_price": 79.99, "supplier": "FurnCo", "weight_kg": 1.5}),
]
for pid, sku, name, cat, price, meta in products_text_price:
    c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
              (pid, sku, name, cat, price, json.dumps(meta)))

# Products 29-30: orphaned category_id (references non-existent categories)
c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
          (29, 'SKU-0029', 'Mystery Item A', 99, 49.99,
           json.dumps({"list_price": 49.99, "supplier": "Unknown", "weight_kg": 0.5})))
c.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
          (30, 'SKU-0030', 'Mystery Item B', 88, 99.99, None))

# --- Inventory ---
inv_id = 1

# Normal entries (integer quantities, products 1-25)
normal_inventory = [
    (1, 1, 'LOT-A001', 50, '2024-01-15'),
    (1, 2, 'LOT-A002', 30, '2024-02-10'),
    (2, 1, 'LOT-B001', 15, '2024-01-20'),
    (2, 3, 'LOT-B002', 25, '2024-03-05'),
    (3, 2, 'LOT-C001', 100, '2024-01-10'),
    (4, 1, 'LOT-D001', 200, '2024-02-01'),
    (4, 2, 'LOT-D002', 150, '2024-02-15'),
    (4, 3, 'LOT-D003', 180, '2024-03-01'),
    (5, 1, 'LOT-E001', 20, '2024-01-25'),
    (6, 2, 'LOT-F001', 75, '2024-02-20'),
    (6, 3, 'LOT-F002', 60, '2024-03-10'),
    (7, 1, 'LOT-G001', 40, '2024-01-30'),
    (8, 2, 'LOT-H001', 90, '2024-02-05'),
    (9, 1, 'LOT-I001', 120, '2024-01-12'),
    (9, 3, 'LOT-I002', 85, '2024-03-15'),
    (10, 1, 'LOT-J001', 300, '2024-01-05'),
    (10, 2, 'LOT-J002', 250, '2024-02-28'),
    (11, 3, 'LOT-K001', 180, '2024-03-20'),
    (12, 1, 'LOT-L001', 65, '2024-01-18'),
    (13, 2, 'LOT-M001', 35, '2024-02-22'),
    (14, 1, 'LOT-N001', 45, '2024-01-28'),
    (14, 3, 'LOT-N002', 55, '2024-03-08'),
    (15, 2, 'LOT-O001', 200, '2024-02-14'),
    (16, 1, 'LOT-P001', 30, '2024-01-22'),
    (17, 3, 'LOT-Q001', 110, '2024-03-12'),
    (18, 2, 'LOT-R001', 70, '2024-02-18'),
    (19, 1, 'LOT-S001', 40, '2024-01-08'),
    (19, 2, 'LOT-S002', 35, '2024-02-25'),
    (20, 3, 'LOT-T001', 500, '2024-03-02'),
    (21, 1, 'LOT-U001', 60, '2024-01-14'),
    (22, 2, 'LOT-V001', 45, '2024-02-08'),
    (23, 3, 'LOT-W001', 80, '2024-03-18'),
    (24, 1, 'LOT-X001', 150, '2024-01-20'),
    (25, 2, 'LOT-Y001', 200, '2024-02-12'),
]
for pid, wid, lot, qty, date in normal_inventory:
    c.execute("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)",
              (inv_id, pid, wid, lot, qty, date))
    inv_id += 1

# Phantom duplicate entries: same (product_id, warehouse_id) with NULL lot_number.
# SQLite UNIQUE constraint treats each NULL as distinct, allowing these "duplicates".
phantom_entries = [
    (1, 1, None, 10, '2024-04-01'),
    (1, 1, None, 15, '2024-04-05'),
    (1, 1, None, 20, '2024-04-10'),
    (5, 1, None, 25, '2024-04-02'),
    (5, 1, None, 30, '2024-04-06'),
    (10, 2, None, 40, '2024-04-03'),
    (10, 2, None, 35, '2024-04-07'),
    (15, 2, None, 50, '2024-04-04'),
    (15, 2, None, 45, '2024-04-08'),
    (15, 2, None, 55, '2024-04-12'),
    (20, 3, None, 100, '2024-04-09'),
    (20, 3, None, 80, '2024-04-11'),
]
for pid, wid, lot, qty, date in phantom_entries:
    c.execute("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)",
              (inv_id, pid, wid, lot, qty, date))
    inv_id += 1

# Text quantity entries: quantity stored as TEXT due to BLOB affinity
text_qty_entries = [
    (26, 1, 'LOT-AA01', '150', '2024-05-01'),
    (27, 2, 'LOT-BB01', '75', '2024-05-02'),
    (28, 3, 'LOT-CC01', '40', '2024-05-03'),
    (3, 3, 'LOT-C002', 'pending', '2024-05-04'),
    (7, 2, 'LOT-G002', 'N/A', '2024-05-05'),
    (12, 2, 'LOT-L002', 'backorder', '2024-05-06'),
    (16, 3, 'LOT-P002', '0', '2024-05-07'),
]
for pid, wid, lot, qty, date in text_qty_entries:
    c.execute("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)",
              (inv_id, pid, wid, lot, qty, date))
    inv_id += 1

# --- Transactions ---
tx_id = 1

normal_transactions = [
    (1, 'RECEIPT', 50, '2024-01-15', None),
    (1, 'SHIPMENT', 20, '2024-02-01', None),
    (2, 'RECEIPT', 30, '2024-02-10', None),
    (3, 'RECEIPT', 15, '2024-01-20', None),
    (4, 'RECEIPT', 25, '2024-03-05', None),
    (5, 'RECEIPT', 100, '2024-01-10', None),
    (5, 'SHIPMENT', 40, '2024-02-20', None),
    (6, 'RECEIPT', 200, '2024-02-01', None),
    (7, 'RECEIPT', 150, '2024-02-15', None),
    (8, 'RECEIPT', 180, '2024-03-01', None),
    (9, 'RECEIPT', 20, '2024-01-25', None),
    (10, 'RECEIPT', 75, '2024-02-20', None),
    (11, 'RECEIPT', 60, '2024-03-10', None),
    (12, 'RECEIPT', 40, '2024-01-30', None),
    (13, 'RECEIPT', 90, '2024-02-05', None),
    (14, 'RECEIPT', 120, '2024-01-12', None),
    (14, 'SHIPMENT', 30, '2024-03-01', None),
    (15, 'RECEIPT', 85, '2024-03-15', None),
    (16, 'RECEIPT', 300, '2024-01-05', None),
    (16, 'SHIPMENT', 100, '2024-02-15', None),
    (17, 'RECEIPT', 250, '2024-02-28', None),
]
for inv, txtype, qty, date, notes in normal_transactions:
    c.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
              (tx_id, inv, txtype, qty, date, notes))
    tx_id += 1

# Orphaned transactions: reference non-existent inventory_ids
orphaned_transactions = [
    (9901, 'RECEIPT', 100, '2024-06-01', 'legacy import'),
    (9902, 'SHIPMENT', 50, '2024-06-02', 'legacy import'),
    (9903, 'RECEIPT', 75, '2024-06-03', 'data migration'),
    (9904, 'ADJUSTMENT', 25, '2024-06-04', 'data migration'),
    (9905, 'RETURN', 10, '2024-06-05', 'legacy import'),
    (9906, 'RECEIPT', 200, '2024-06-06', 'data migration'),
    (9907, 'SHIPMENT', 30, '2024-06-07', 'legacy import'),
    (9908, 'RECEIPT', 150, '2024-06-08', 'data migration'),
]
for inv, txtype, qty, date, notes in orphaned_transactions:
    c.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
              (tx_id, inv, txtype, qty, date, notes))
    tx_id += 1

# --- Indexes (needed for sqlite_stat1 analysis) ---
c.execute("CREATE INDEX idx_products_category ON products(category_id)")
c.execute("CREATE INDEX idx_inventory_product ON inventory(product_id)")
c.execute("CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id)")
c.execute("CREATE INDEX idx_transactions_inventory ON transactions(inventory_id)")

# --- Run ANALYZE to populate sqlite_stat1, then corrupt it ---
c.execute("ANALYZE")
conn.commit()

# Corrupt sqlite_stat1 entries
c.execute("UPDATE sqlite_stat1 SET stat = '500000 1' "
          "WHERE tbl = 'products' AND idx = 'idx_products_category'")
c.execute("UPDATE sqlite_stat1 SET stat = '999999 1 1 1' "
          "WHERE tbl = 'inventory' AND idx = 'sqlite_autoindex_inventory_1'")
c.execute("INSERT INTO sqlite_stat1 VALUES "
          "('transactions', 'ix_tx_nonexistent', '50000 100 10')")
conn.commit()
conn.close()
