#!/usr/bin/env python3
"""Generate prediction market dataset in SQLite with embedded data quality issues."""

import numpy as np
import sqlite3
import os
from datetime import datetime, timedelta
import random

np.random.seed(20241020)
random.seed(20241020)

N_EVENTS = 200
N_FORECASTERS = 25

skills = np.linspace(-1.0, 2.5, N_FORECASTERS)
true_probs = np.random.beta(2, 2, N_EVENTS)

unresolved_indices = set(np.random.choice(N_EVENTS, 18, replace=False).tolist())

outcomes = []
for i in range(N_EVENTS):
    if i in unresolved_indices:
        outcomes.append(-1)
    else:
        outcomes.append(int(1 if np.random.rand() < true_probs[i] else 0))

yes_prices = np.clip(true_probs + np.random.normal(0, 0.06, N_EVENTS), 0.05, 0.95)
no_prices = np.clip(1 - true_probs + np.random.normal(0, 0.06, N_EVENTS) + 0.025, 0.05, 0.95)
yes_prices = np.round(yes_prices, 4)
no_prices = np.round(no_prices, 4)

cat_pool = ['politics', 'finance', 'sports', 'entertainment', 'science']
cat_indices = np.random.randint(0, 5, N_EVENTS)
categories = [cat_pool[int(x)] for x in cat_indices]

base_time = datetime(2024, 10, 1, 0, 0, 0)
res_days = np.random.randint(30, 120, N_EVENTS)

os.makedirs('/app/data', exist_ok=True)
db = sqlite3.connect('/app/data/forecasts.db')
c = db.cursor()

c.execute('''CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    resolution_date TEXT NOT NULL,
    outcome INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE markets (
    event_id TEXT PRIMARY KEY,
    yes_price REAL NOT NULL,
    no_price REAL NOT NULL,
    spread REAL NOT NULL,
    volume INTEGER NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(event_id)
)''')

c.execute('''CREATE TABLE forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    forecaster_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    probability REAL NOT NULL,
    confidence REAL NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(event_id)
)''')

for i in range(N_EVENTS):
    eid = f'EVT{i+1:04d}'
    rdate = (base_time + timedelta(days=int(res_days[i]))).strftime('%Y-%m-%d')
    c.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
              (eid, categories[i], rdate, outcomes[i]))

for i in range(N_EVENTS):
    eid = f'EVT{i+1:04d}'
    spread = round(abs(float(yes_prices[i]) - float(no_prices[i])), 4)
    volume = int(np.random.randint(100, 10000))
    c.execute('INSERT INTO markets VALUES (?, ?, ?, ?, ?)',
              (eid, float(yes_prices[i]), float(no_prices[i]), spread, volume))

forecasts = []
for j in range(N_FORECASTERS):
    coverage_mask = np.random.rand(N_EVENTS) < 0.65
    for i in range(N_EVENTS):
        if coverage_mask[i]:
            noise_std = 0.2 * np.exp(-0.3 * skills[j])
            pred = float(np.clip(true_probs[i] + np.random.normal(0, noise_std), 0.01, 0.99))
            ts = base_time + timedelta(
                days=int(np.random.randint(0, 30)),
                hours=int(np.random.randint(0, 24)),
                minutes=int(np.random.randint(0, 60))
            )
            confidence = round(float(np.random.uniform(0.5, 1.0)), 2)
            forecasts.append({
                'event_id': f'EVT{i+1:04d}',
                'forecaster_id': f'FC{j+1:03d}',
                'timestamp': ts.strftime('%Y-%m-%dT%H:%M:%S'),
                'probability': round(pred, 4),
                'confidence': confidence
            })

dup_indices = np.random.choice(len(forecasts), 30, replace=False).tolist()
for idx in dup_indices:
    orig = forecasts[idx]
    orig_ts = datetime.strptime(orig['timestamp'], '%Y-%m-%dT%H:%M:%S')
    new_ts = orig_ts + timedelta(days=int(np.random.randint(1, 15)),
                                  hours=int(np.random.randint(0, 24)))
    new_pred = float(np.clip(orig['probability'] + np.random.normal(0, 0.08), 0.01, 0.99))
    forecasts.append({
        'event_id': orig['event_id'],
        'forecaster_id': orig['forecaster_id'],
        'timestamp': new_ts.strftime('%Y-%m-%dT%H:%M:%S'),
        'probability': round(new_pred, 4),
        'confidence': round(float(np.random.uniform(0.5, 1.0)), 2)
    })

for k in range(5):
    orphan_eid = f'EVT{N_EVENTS + 10 + k:04d}'
    orphan_fid = f'FC{int(np.random.randint(1, N_FORECASTERS+1)):03d}'
    ts = base_time + timedelta(days=int(np.random.randint(0, 30)))
    forecasts.append({
        'event_id': orphan_eid,
        'forecaster_id': orphan_fid,
        'timestamp': ts.strftime('%Y-%m-%dT%H:%M:%S'),
        'probability': round(float(np.random.uniform(0.1, 0.9)), 4),
        'confidence': round(float(np.random.uniform(0.5, 1.0)), 2)
    })

extreme_indices = np.random.choice(len(forecasts), 4, replace=False).tolist()
for idx in extreme_indices:
    forecasts[idx]['probability'] = float(np.random.choice([0.0, 1.0]))

random.shuffle(forecasts)

for fc in forecasts:
    c.execute('INSERT INTO forecasts (event_id, forecaster_id, timestamp, probability, confidence) VALUES (?, ?, ?, ?, ?)',
              (fc['event_id'], fc['forecaster_id'], fc['timestamp'],
               fc['probability'], fc['confidence']))

c.execute('CREATE INDEX idx_forecasts_event ON forecasts(event_id)')
c.execute('CREATE INDEX idx_forecasts_forecaster ON forecasts(forecaster_id)')
c.execute('CREATE INDEX idx_forecasts_composite ON forecasts(event_id, forecaster_id, timestamp)')

db.commit()

with open('/app/data/data_dictionary.txt', 'w') as f:
    f.write("Prediction Market Dataset (SQLite)\n")
    f.write("===================================\n\n")
    f.write("Database: /app/data/forecasts.db\n\n")
    f.write("Tables:\n\n")
    f.write("events:\n")
    f.write("  event_id        TEXT PRIMARY KEY - Unique event identifier (EVTxxxx)\n")
    f.write("  category        TEXT - Event category\n")
    f.write("  resolution_date TEXT - Date the event resolved\n")
    f.write("  outcome         INTEGER - 1 = Yes, 0 = No, -1 = Unresolved/Pending\n\n")
    f.write("markets:\n")
    f.write("  event_id    TEXT PRIMARY KEY - Event identifier (FK to events)\n")
    f.write("  yes_price   REAL - Market price of YES contract (pays $1 if Yes)\n")
    f.write("  no_price    REAL - Market price of NO contract (pays $1 if No)\n")
    f.write("  spread      REAL - Absolute price spread\n")
    f.write("  volume      INTEGER - Trading volume\n\n")
    f.write("forecasts:\n")
    f.write("  id            INTEGER PRIMARY KEY AUTOINCREMENT\n")
    f.write("  event_id      TEXT - Event identifier\n")
    f.write("  forecaster_id TEXT - Forecaster identifier (FCxxx)\n")
    f.write("  timestamp     TEXT - Prediction timestamp (ISO 8601)\n")
    f.write("  probability   REAL - Predicted probability of Yes outcome\n")
    f.write("  confidence    REAL - Self-reported confidence level (0-1)\n")

print(f"Generated SQLite database with {N_EVENTS} events "
      f"({len(unresolved_indices)} unresolved), {len(forecasts)} forecast records")
db.close()
