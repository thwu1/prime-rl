"""
Generate production database and supplementary files for cutting stock task.
Run during Docker build to populate /app/.
"""
import sqlite3
import csv
import os

os.makedirs('/app/data/adjustments', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# ============================================================
# SQLite production database
# ============================================================
conn = sqlite3.connect('/app/data/production.db')
c = conn.cursor()

c.execute('''CREATE TABLE roll_stock (
    id INTEGER PRIMARY KEY,
    material_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    thickness REAL NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    description TEXT
)''')

c.execute('''CREATE TABLE machine_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
)''')

c.execute('''CREATE TABLE work_orders (
    id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','fulfilled','cancelled')),
    priority TEXT DEFAULT 'normal',
    created_at TEXT NOT NULL,
    notes TEXT
)''')

c.execute('''CREATE TABLE order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER NOT NULL,
    piece_width INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
)''')

# ---- Roll stock: multiple types, only standard+available matters ----
c.executemany('INSERT INTO roll_stock VALUES (?, ?, ?, ?, ?, ?)', [
    (1, 'premium',  1200, 2.0, 1, 'Premium grade wide format'),
    (2, 'standard', 1000, 1.5, 1, 'Standard production roll'),
    (3, 'standard',  800, 1.5, 0, 'Discontinued narrow standard'),
    (4, 'economy',   600, 1.0, 1, 'Economy grade narrow'),
    (5, 'premium',  1500, 2.5, 0, 'Discontinued wide premium'),
])

# ---- Machine config: active_material_type selects which roll to use ----
c.executemany('INSERT INTO machine_config VALUES (?, ?, ?)', [
    ('active_material_type', 'standard', 'Material type loaded on cutting machine'),
    ('max_patterns_per_run', '50', 'Max distinct patterns per production run'),
    ('min_utilization_pct', '75', 'Minimum roll utilization target'),
    ('shift_hours', '8', 'Hours per shift'),
])

# ---- Work orders ----
pending_orders = [
    (1,  'Apex Manufacturing',     'pending', 'high',   '2024-10-02', None),
    (2,  'BlueLine Industries',    'pending', 'normal', '2024-10-03', None),
    (3,  'CastForm Corp',          'pending', 'urgent', '2024-10-05', None),
    (4,  'Deltawave Solutions',    'pending', 'normal', '2024-10-07', None),
    (5,  'EastPoint Fabrication',  'pending', 'high',   '2024-10-08', None),
    (6,  'Frontier Materials',     'pending', 'normal', '2024-10-09', None),
    (7,  'GreenTech Packaging',    'pending', 'normal', '2024-10-11', None),
    (8,  'Highland Assembly',      'pending', 'high',   '2024-10-12', None),
    (9,  'IronClad Products',      'pending', 'normal', '2024-10-14', None),
    (10, 'JetStream Components',   'pending', 'urgent', '2024-10-15', None),
    (11, 'KeyStone Metals',        'pending', 'normal', '2024-10-17', None),
    (12, 'LightPath Designs',      'pending', 'normal', '2024-10-18', None),
    (13, 'MetroFab Inc',           'pending', 'high',   '2024-10-20', None),
    (14, 'NovaPart Systems',       'pending', 'normal', '2024-10-22', None),
    (15, 'OmniCraft LLC',          'pending', 'normal', '2024-10-24', None),
]

fulfilled_orders = [
    (16, 'PeakForm Industries',      'fulfilled', 'normal', '2024-09-05', 'Completed on schedule'),
    (17, 'QuickCut Solutions',        'fulfilled', 'normal', '2024-09-08', 'Delivered'),
    (18, 'RapidBuild Corp',           'fulfilled', 'high',   '2024-09-12', 'Completed'),
    (19, 'SteelEdge Manufacturing',   'fulfilled', 'normal', '2024-09-15', 'Shipped'),
    (20, 'TrueForm Assemblies',       'fulfilled', 'normal', '2024-09-18', 'Done'),
    (21, 'UltraCut Precision',        'fulfilled', 'normal', '2024-09-22', 'Completed'),
    (22, 'VanguardParts Inc',         'fulfilled', 'normal', '2024-09-25', 'Delivered'),
]

cancelled_orders = [
    (23, 'WestPoint Fabrication', 'cancelled', 'normal', '2024-10-01', 'Customer cancelled'),
    (24, 'XcelFab Industries',    'cancelled', 'normal', '2024-10-04', 'Budget constraints'),
    (25, 'ZenithCraft LLC',       'cancelled', 'high',   '2024-10-06', 'Project postponed'),
]

for order in pending_orders + fulfilled_orders + cancelled_orders:
    c.execute('INSERT INTO work_orders VALUES (?, ?, ?, ?, ?, ?)', order)

# ---- Order lines for PENDING orders ----
# Base demands (before adjustments) by piece_width, summed across pending orders:
# 467:18, 333:40, 295:35, 258:25, 231:12, 197:28, 168:39, 150:50,
# 137:20, 125:15, 113:58, 99:38, 89:30, 76:45, 63:53, 52:36,
# 41:70, 33:82, 27:50, 21:90
pending_lines = [
    # Order 1
    (1, 467, 5), (1, 333, 8), (1, 295, 7), (1, 258, 5),
    # Order 2
    (2, 231, 4), (2, 197, 6), (2, 168, 8), (2, 150, 10),
    # Order 3
    (3, 137, 5), (3, 125, 4), (3, 113, 12), (3, 99, 8),
    # Order 4
    (4, 89, 7), (4, 76, 10), (4, 63, 12), (4, 52, 8),
    # Order 5
    (5, 41, 15), (5, 33, 18), (5, 27, 12), (5, 21, 20),
    # Order 6
    (6, 467, 4), (6, 333, 7), (6, 295, 6), (6, 197, 5),
    # Order 7
    (7, 258, 5), (7, 231, 3), (7, 168, 7), (7, 150, 8),
    # Order 8
    (8, 137, 4), (8, 125, 3), (8, 113, 10), (8, 99, 6),
    # Order 9
    (9, 89, 5), (9, 76, 8), (9, 63, 9), (9, 52, 6),
    # Order 10
    (10, 41, 12), (10, 33, 14), (10, 27, 8), (10, 21, 15),
    # Order 11
    (11, 467, 3), (11, 333, 8), (11, 295, 7), (11, 258, 5),
    # Order 12
    (12, 231, 2), (12, 197, 6), (12, 168, 8), (12, 150, 10),
    # Order 13
    (13, 137, 4), (13, 125, 3), (13, 113, 12), (13, 99, 8),
    # Order 14
    (14, 89, 6), (14, 76, 9), (14, 63, 11), (14, 52, 7),
    # Order 15 (largest order — catches remaining demand)
    (15, 467, 6), (15, 333, 17), (15, 295, 15), (15, 258, 10),
    (15, 231, 3), (15, 197, 11), (15, 168, 16), (15, 150, 22),
    (15, 137, 7), (15, 125, 5), (15, 113, 24), (15, 99, 16),
    (15, 89, 12), (15, 76, 18), (15, 63, 21), (15, 52, 15),
    (15, 41, 43), (15, 33, 50), (15, 27, 30), (15, 21, 55),
]

# ---- Order lines for FULFILLED orders (distractors — must NOT be counted) ----
fulfilled_lines = [
    (16, 467, 10), (16, 333, 15), (16, 150, 20),
    (17, 295, 12), (17, 258, 8),  (17, 113, 25),
    (18, 197, 14), (18, 168, 18), (18, 99, 12),
    (19, 231, 6),  (19, 137, 9),  (19, 76, 15),
    (20, 125, 7),  (20, 89, 11),  (20, 63, 18),
    (21, 52, 14),  (21, 41, 22),  (21, 33, 30),
    (22, 27, 16),  (22, 21, 28),  (22, 467, 8),
]

# ---- Order lines for CANCELLED orders (distractors — must NOT be counted) ----
cancelled_lines = [
    (23, 333, 10), (23, 295, 8),  (23, 168, 12),
    (24, 150, 15), (24, 113, 20), (24, 76, 10),
    (25, 63, 14),  (25, 41, 18),  (25, 21, 25),
]

for line in pending_lines + fulfilled_lines + cancelled_lines:
    c.execute('INSERT INTO order_lines (work_order_id, piece_width, quantity) VALUES (?, ?, ?)', line)

conn.commit()
conn.close()

# ============================================================
# Demand adjustments CSV
# ============================================================
# These add to the base pending-order demands.
# Final demand = base (from pending orders) + adjustment
adj_rows = [
    (467, 3, 'Rush order addition'),
    (333, 4, 'Customer revision'),
    (295, 2, 'Safety stock increase'),
    (258, 3, 'Forecast update'),
    (231, 3, 'Rush order addition'),
    (197, 3, 'Quality buffer'),
    (168, 3, 'Customer revision'),
    (150, 5, 'Rush order addition'),
    (137, 3, 'Safety stock increase'),
    (125, 3, 'Customer revision'),
    (113, 4, 'Forecast update'),
    (99,  3, 'Quality buffer'),
    (89,  2, 'Rush order addition'),
    (76,  3, 'Customer revision'),
    (63,  4, 'Safety stock increase'),
    (52,  3, 'Forecast update'),
    (41,  3, 'Rush order addition'),
    (33,  4, 'Quality buffer'),
    (27,  4, 'Customer revision'),
    (21,  3, 'Forecast update'),
]

with open('/app/data/adjustments/2024_q4_adjustments.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['piece_width', 'quantity_change', 'reason'])
    for row in adj_rows:
        writer.writerow(row)

# ============================================================
# README
# ============================================================
with open('/app/README.txt', 'w') as f:
    f.write(
        "Production Cutting Optimization System v3.2\n"
        "============================================\n"
        "\n"
        "Order data, material specifications, and machine settings are managed\n"
        "through the production database. Check the data directory for the\n"
        "database and any supplementary files.\n"
        "\n"
        "Only pending work orders require fulfillment. Demand adjustments\n"
        "from the adjustments directory must be factored into the final\n"
        "piece quantities before optimization.\n"
    )
