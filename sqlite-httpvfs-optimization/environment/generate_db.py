"""Generate analytics event database for HTTP-VFS optimization task."""
import sqlite3
import random
import shutil
import os

random.seed(42)

DB_PATH = '/app/analytics.db'
BACKUP_PATH = '/app/.original.db'
os.makedirs('/app', exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute('''CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    country_code TEXT NOT NULL,
    device TEXT NOT NULL,
    value REAL,
    session_id TEXT NOT NULL,
    referrer TEXT
)''')

EVENT_TYPES = ['pageview', 'click', 'purchase', 'signup', 'share']
EVENT_WEIGHTS = [50, 25, 10, 5, 10]
CATEGORIES = ['electronics', 'clothing', 'food', 'books', 'sports', 'home', 'automotive', 'health']
COUNTRIES = ['US', 'GB', 'DE', 'FR', 'JP', 'BR', 'IN', 'AU', 'CA', 'MX', 'KR', 'IT', 'ES', 'NL', 'SE']
COUNTRY_WEIGHTS = [30, 10, 8, 7, 7, 6, 6, 5, 5, 4, 3, 3, 3, 2, 1]
DEVICES = ['mobile', 'desktop', 'tablet']
DEVICE_WEIGHTS = [55, 35, 10]
REFERRERS = [None, 'google.com', 'facebook.com', 'twitter.com', 'direct', 'email']

NUM_USERS = 10000
NUM_EVENTS = 500000

users = [f'U{i:05d}' for i in range(NUM_USERS)]

# Time range: Jan 1 2024 to Dec 31 2024 (UTC)
TS_START = 1704067200
TS_END = 1735689600

c.execute("BEGIN")
batch = []
for i in range(NUM_EVENTS):
    ts = random.randint(TS_START, TS_END - 1)
    user_id = random.choice(users)
    event_type = random.choices(EVENT_TYPES, weights=EVENT_WEIGHTS, k=1)[0]
    category = random.choice(CATEGORIES)
    country = random.choices(COUNTRIES, weights=COUNTRY_WEIGHTS, k=1)[0]
    device = random.choices(DEVICES, weights=DEVICE_WEIGHTS, k=1)[0]

    if event_type == 'purchase':
        value = round(random.uniform(1.0, 500.0), 2)
    elif event_type == 'click':
        value = round(random.uniform(0.01, 5.0), 2)
    else:
        value = None

    session_id = f'S{random.randint(0, 999999):06d}'
    referrer = random.choice(REFERRERS)

    batch.append((ts, user_id, event_type, category, country, device,
                   value, session_id, referrer))

    if len(batch) >= 10000:
        c.executemany(
            'INSERT INTO events (ts, user_id, event_type, category, '
            'country_code, device, value, session_id, referrer) '
            'VALUES (?,?,?,?,?,?,?,?,?)', batch)
        batch = []

if batch:
    c.executemany(
        'INSERT INTO events (ts, user_id, event_type, category, '
        'country_code, device, value, session_id, referrer) '
        'VALUES (?,?,?,?,?,?,?,?,?)', batch)

conn.commit()
conn.close()

# Save pristine backup for verification
shutil.copy(DB_PATH, BACKUP_PATH)
