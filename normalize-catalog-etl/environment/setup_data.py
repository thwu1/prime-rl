#!/usr/bin/env python3
"""Create multi-source product feeds and reference database for reconciliation task."""
import sqlite3
import json
import csv
import os
import sys

os.makedirs('/app/feeds', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# === Alpha feed: semicolon-delimited CSV, European formatting ==================
alpha_rows = [
    ["A001", " Wireless Earbuds Pro ", "High-quality wireless earbuds with active noise cancellation and 24-hour battery life. Product reference: REF:P1001", "72,99", "EUR", "Electronics > Audio", "SoundTech", "15.01.2024", "150", "aktiv", "wireless,bluetooth,audio,portable"],
    ["A002", "Smart Watch X200", "Feature-rich smartwatch with health monitoring, GPS tracking, and 5-day battery. Catalog ref: REF:P1002", "271,82", "EUR", "Electronics > Wearables", "Tech Wear Ltd", "28.02.2024", "75", "aktiv", "smart,wearable,health,bluetooth"],
    ["A003", "Professional Chef Knife Set", "8-piece stainless steel knife set with wooden block and sharpener", "136,36", "EUR", "Home & Garden > Kitchen", "HomeGoods", "10.03.2024", "200", "aktiv", "kitchen,cooking,professional"],
    ["A004", "Yoga Mat Premium", "Extra thick non-slip yoga mat with carrying strap and alignment marks", "34,99", "EUR", "Sports > Fitness", "FitLife", "05.01.2024", "300", "aktiv", "yoga,fitness,exercise"],
    ["A005", "Compact Digital Camera ", "20MP compact camera with 10x optical zoom and WiFi connectivity. Ref: REF:P1003", "449,00", "EUR", "Electronics > Cameras", "Gadget Max Co", "22.04.2024", "50", "inaktiv", "camera,digital,photography"],
    ["A006", "Science Fiction Anthology", "Collection of award-winning science fiction stories from emerging authors", "22,72", "EUR", "Books > Fiction", "Book World Inc", "01.05.2024", "500", "aktiv", "books,fiction,scifi"],
    ["A007", "Cordless Power Drill", "18V lithium-ion cordless drill with 2 batteries, charger, and bit set", "81,81", "EUR", "Home & Garden > Tools", "Quality Tools AG", "14.02.2024", "120", "aktiv", "tools,power,drill"],
    ["A008", "Bluetooth Speaker Waterproof", "Portable wireless waterproof Bluetooth speaker with 12-hour battery. Reference REF:P1004", "54,54", "EUR", "Electronics > Audio", "SOUNDTECH INC", "30.03.2024", "180", "aktiv", "wireless,bluetooth,audio,waterproof"],
    ["A009", "Running Shoes Elite", "Lightweight running shoes with carbon fiber plate and responsive cushioning", "179,99", "EUR", "Sports > Fitness", "Fit Life Corp", "15.04.2024", "90", "aktiv", "running,shoes,fitness"],
    ["A010", "Data Science Handbook", "Comprehensive guide to data science with Python examples and real-world case studies", "49,99", "EUR", "Books > Technical", "BookWorld", "20.01.2024", "250", "aktiv", "books,data,science"],
    ["A011", "Garden Hose Expandable", "50-foot expandable garden hose with brass fittings and spray nozzle", "29,99", "EUR", "Home & Garden > Outdoor", "HomeGoods", "10.06.2024", "-5", "aktiv", "garden,hose,outdoor"],
    ["A012", "Fitness Tracker Band", "Slim fitness tracking band with heart rate monitor and sleep analysis", "0,00", "EUR", "Electronics > Wearables", "TechWear", "15.03.2024", "100", "aktiv", "fitness,tracker,wearable"],
]

with open('/app/feeds/alpha.csv', 'w', newline='') as f:
    w = csv.writer(f, delimiter=';')
    w.writerow(['sku', 'product_name', 'description', 'price', 'currency',
                'category', 'supplier', 'received_date', 'quantity', 'status', 'tags'])
    for row in alpha_rows:
        w.writerow(row)

# === Beta feed: JSON array with nested objects ==================================
beta_data = [
    {
        "sku": "B001", "name": "Pro Wireless Earbuds",
        "description": "Premium true wireless earbuds featuring advanced ANC technology and extended battery. Internal tracking: REF:P1001",
        "price": {"amount": 79.99, "currency": "USD"},
        "category": {"path": "Electronics/Audio"},
        "supplier": {"name": "SoundTech Inc", "code": "SUP-001"},
        "timestamp": 1711929600, "quantity": 120, "active": True,
        "tags": ["wireless", "bluetooth", "earbuds", "anc"]
    },
    {
        "sku": "B002", "name": "Noise Cancelling Headphones",
        "description": "Over-ear wireless headphones with advanced noise cancellation technology and 30-hour battery",
        "price": {"amount": 199.00, "currency": "GBP"},
        "category": {"path": "Electronics/Audio"},
        "supplier": {"name": "SoundTech Inc", "code": "SUP-001"},
        "timestamp": 1705276800, "quantity": 60, "active": True,
        "tags": ["wireless", "noise-cancelling", "audio"]
    },
    {
        "sku": "B003", "name": "Smart Home Hub",
        "description": "Central hub for controlling all smart home devices via voice and app",
        "price": {"amount": 129.00, "currency": "EUR"},
        "category": {"path": "Electronics/Smart Home"},
        "supplier": {"name": "GadgetMax Co", "code": "SUP-005"},
        "timestamp": 1709078400, "quantity": 100, "active": True,
        "tags": ["smart", "home", "automation"]
    },
    {
        "sku": "B004", "name": "Espresso Machine Deluxe",
        "description": "Professional-grade espresso machine with built-in ceramic burr grinder",
        "price": {"amount": 549.00, "currency": "EUR"},
        "category": {"path": "Home & Garden/Kitchen"},
        "supplier": {"name": "HomeGoods GmbH", "code": "SUP-003"},
        "timestamp": 1710028800, "quantity": 30, "active": True,
        "tags": ["kitchen", "coffee", "espresso"]
    },
    {
        "sku": "B005", "name": "Mountain Bike Pro",
        "description": "Full suspension mountain bike with 29-inch wheels and hydraulic disc brakes",
        "price": {"amount": 1299.00, "currency": "GBP"},
        "category": {"path": "Sports/Outdoor Sports"},
        "supplier": {"name": "SportsPro SA", "code": "SUP-008"},
        "timestamp": 1712361600, "quantity": 15, "active": True,
        "tags": ["cycling", "outdoor", "bike"]
    },
    {
        "sku": "B006", "name": "Philosophy of Mind",
        "description": "An introduction to contemporary philosophy of mind and consciousness",
        "price": {"amount": 29.00, "currency": "EUR"},
        "category": {"path": "Books/Non-Fiction"},
        "supplier": {"name": "BookWorld Inc", "code": "SUP-006"},
        "timestamp": 1705708800, "quantity": 80, "active": False,
        "tags": ["philosophy", "nonfiction"]
    },
    {
        "sku": "B007", "name": "Camping Tent 4-Person",
        "description": "Waterproof 4-person tent with easy setup and ventilation system",
        "price": {"amount": 189.00, "currency": "GBP"},
        "category": {"path": "Sports/Outdoor Sports"},
        "supplier": {"name": "Sports Pro SA", "code": "SUP-008"},
        "timestamp": 1715558400, "quantity": 45, "active": True,
        "tags": ["camping", "outdoor", "tent"]
    },
    {
        "sku": "B008", "name": "HD Action Camera",
        "description": "Rugged waterproof action camera with 4K video and electronic stabilization. Code: REF:P1003",
        "price": {"amount": 399.99, "currency": "USD"},
        "category": {"path": "Electronics/Cameras"},
        "supplier": {"name": "GadgetMax Co", "code": "SUP-005"},
        "timestamp": 1717200000, "quantity": 65, "active": True,
        "tags": ["camera", "action", "4k", "waterproof"]
    },
    {
        "sku": "B009", "name": "Resistance Band Set",
        "description": "Set of 5 resistance bands for home workouts with door anchor and carry bag",
        "price": {"amount": 19.99, "currency": "EUR"},
        "category": {"path": "Sports/Fitness"},
        "supplier": {"name": "FitLife Corp", "code": "SUP-004"},
        "timestamp": 1707868800, "quantity": 350, "active": True,
        "tags": ["fitness", "exercise", "bands"]
    },
    {
        "sku": "B010", "name": "Machine Learning Textbook",
        "description": "Advanced machine learning concepts with practical implementations and case studies",
        "price": {"amount": 79.00, "currency": "GBP"},
        "category": {"path": "Books/Technical"},
        "supplier": {"name": "BookWorld Inc", "code": "SUP-006"},
        "timestamp": 1712016000, "quantity": 120, "active": True,
        "tags": ["machine-learning", "ai", "technical"]
    }
]

with open('/app/feeds/beta.json', 'w') as f:
    json.dump(beta_data, f, indent=2)

# === Gamma feed: newline-delimited JSON =========================================
gamma_data = [
    {"sku": "G001", "name": "SmartWatch X200 Pro", "description": "Next-generation smartwatch with GPS, health sensors, and always-on display. Item code REF:P1002", "price": "USD 319.99", "category": "electronics::wearables", "supplier": "TechWear", "date": "2024/05/15", "quantity": 80, "status": "Y", "tags": "smart|wearable|gps|health"},
    {"sku": "G002", "name": "Smart Thermostat", "description": "WiFi-enabled smart thermostat with learning capabilities and energy usage reports", "price": "USD 179.99", "category": "electronics::smart home", "supplier": "GadgetMax", "date": "2024/02/28", "quantity": 110, "status": "Y", "tags": "smart|thermostat|wifi|energy"},
    {"sku": "G003", "name": "Cast Iron Skillet", "description": "Pre-seasoned cast iron skillet 12-inch for stovetop and oven use", "price": "USD 39.99", "category": "home & garden::kitchen", "supplier": "HomeGoods GmbH", "date": "2024/03/10", "quantity": 175, "status": "Y", "tags": "kitchen|cooking|cast-iron"},
    {"sku": "G004", "name": "Basketball Official Size", "description": "Official size and weight basketball for indoor and outdoor play", "price": "USD 29.99", "category": "sports::team sports", "supplier": "SportsPro", "date": "2024/04/05", "quantity": 200, "status": "Y", "tags": "basketball|team|sports"},
    {"sku": "G005", "name": "Mystery Novel Collection", "description": "Box set of bestselling mystery novels from contemporary authors", "price": "USD 34.99", "category": "books::fiction", "supplier": "Book World Inc", "date": "2024/05/01", "quantity": 150, "status": "N", "tags": "mystery|fiction|collection"},
    {"sku": "G006", "name": "Portable Power Bank 20000mAh", "description": "High-capacity portable charger with USB-C fast charging and LED display", "price": "USD 44.99", "category": "electronics::accessories", "supplier": "GadgetMax Co", "date": "2024/06/08", "quantity": 250, "status": "Y", "tags": "portable|charging|usb-c"},
    {"sku": "G007", "name": "Hiking Backpack 50L", "description": "Durable 50-liter hiking backpack with rain cover and hydration port", "price": "USD 89.99", "category": "sports::outdoor sports", "supplier": "Sports Pro SA", "date": "2024/03/25", "quantity": 65, "status": "Y", "tags": "hiking|outdoor|backpack"},
    {"sku": "G008", "name": "Waterproof BT Speaker", "description": "Rugged waterproof Bluetooth speaker for outdoor adventures with 10-hour playtime. ID: REF:P1004", "price": "USD 49.99", "category": "electronics::audio", "supplier": "SoundTech", "date": "2024/02/10", "quantity": 200, "status": "Y", "tags": "speaker|bluetooth|waterproof|outdoor"},
    {"sku": "G009", "name": "Adjustable Dumbbell Set", "description": "Adjustable dumbbells 5-52.5 lbs with quick-change weight selection", "price": "USD 349.99", "category": "sports::fitness", "supplier": "FitLife", "date": "2024/02/14", "quantity": 40, "status": "Y", "tags": "fitness|weights|dumbbells"},
    {"sku": "G010", "name": "Electric Kettle Glass", "description": "Glass electric kettle with temperature control and keep-warm function", "price": "USD 49.99", "category": "home & garden::kitchen", "supplier": "Home Goods GmbH", "date": "2024/04/22", "quantity": 130, "status": "Y", "tags": "kitchen|electric|kettle"},
]

with open('/app/feeds/gamma.ndjson', 'w') as f:
    for item in gamma_data:
        f.write(json.dumps(item) + '\n')

# === Reference database =========================================================
db_path = '/app/reference.db'
if os.path.exists(db_path):
    os.remove(db_path)

db = sqlite3.connect(db_path, isolation_level=None)

# Temporal FX rates -- rates change quarterly
db.execute('''CREATE TABLE fx_history (
    currency TEXT NOT NULL,
    rate_to_usd REAL NOT NULL,
    effective_from TEXT NOT NULL,
    PRIMARY KEY (currency, effective_from)
)''')
fx = [
    ('EUR', 1.08, '2024-01-01'), ('EUR', 1.10, '2024-04-01'), ('EUR', 1.12, '2024-07-01'),
    ('GBP', 1.25, '2024-01-01'), ('GBP', 1.27, '2024-04-01'), ('GBP', 1.29, '2024-07-01'),
    ('JPY', 0.0066, '2024-01-01'), ('JPY', 0.0067, '2024-04-01'), ('JPY', 0.0064, '2024-07-01'),
]
for row in fx:
    db.execute("INSERT INTO fx_history VALUES (?,?,?)", row)

# Retroactive FX corrections -- override fx_history for specific date ranges
db.execute('''CREATE TABLE fx_corrections (
    currency TEXT NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    corrected_rate REAL NOT NULL,
    reason TEXT,
    PRIMARY KEY (currency, date_from)
)''')
corrections = [
    ('EUR', '2024-01-01', '2024-03-31', 1.09, 'ECB revised Q1 benchmark rate'),
    ('JPY', '2024-04-01', '2024-06-30', 0.0068, 'BoJ intervention adjustment'),
]
for row in corrections:
    db.execute("INSERT INTO fx_corrections VALUES (?,?,?,?,?)", row)

# Supplier directory -- canonical names with metadata
db.execute('''CREATE TABLE supplier_directory (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    country TEXT,
    rating REAL
)''')
suppliers = [
    (1, 'SoundTech Inc', 'US', 4.5),
    (2, 'TechWear Ltd', 'CN', 4.2),
    (3, 'HomeGoods GmbH', 'DE', 4.0),
    (4, 'FitLife Corp', 'US', 3.9),
    (5, 'GadgetMax Co', 'JP', 4.3),
    (6, 'BookWorld Inc', 'US', 4.7),
    (7, 'QualityTools AG', 'DE', 4.1),
    (8, 'SportsPro SA', 'FR', 3.8),
]
for row in suppliers:
    db.execute("INSERT INTO supplier_directory VALUES (?,?,?,?)", row)

# Supplier aliases -- variant names that map to canonical entries
db.execute('''CREATE TABLE supplier_aliases (
    directory_id INTEGER REFERENCES supplier_directory(id),
    alias TEXT NOT NULL UNIQUE
)''')
aliases = [
    (1, 'SoundTech'), (1, 'Sound Tech Inc'), (1, 'SOUNDTECH INC'),
    (2, 'TechWear'), (2, 'Tech Wear Ltd'),
    (3, 'HomeGoods'), (3, 'Home Goods GmbH'),
    (4, 'FitLife'), (4, 'Fit Life Corp'),
    (5, 'GadgetMax'), (5, 'Gadget Max Co'),
    (6, 'BookWorld'), (6, 'Book World Inc'),
    (7, 'QualityTools'), (7, 'Quality Tools AG'),
    (8, 'SportsPro'), (8, 'Sports Pro SA'),
]
for row in aliases:
    db.execute("INSERT INTO supplier_aliases VALUES (?,?)", row)

db.close()

# === Verification ================================================================
db = sqlite3.connect(db_path)
expected_tables = ['fx_history', 'fx_corrections', 'supplier_directory', 'supplier_aliases']
actual_tables = [r[0] for r in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
for t in expected_tables:
    if t not in actual_tables:
        print(f"ERROR: Missing table {t}! Found: {actual_tables}", file=sys.stderr)
        sys.exit(1)
    count = db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {count} rows")
    if count == 0:
        print(f"ERROR: Table {t} is empty!", file=sys.stderr)
        sys.exit(1)
db.close()

# Verify feeds exist
for f in ['/app/feeds/alpha.csv', '/app/feeds/beta.json', '/app/feeds/gamma.ndjson']:
    if not os.path.exists(f):
        print(f"ERROR: Feed file missing: {f}", file=sys.stderr)
        sys.exit(1)
    sz = os.path.getsize(f)
    print(f"  {f}: {sz} bytes")

print("Setup complete and verified.")
