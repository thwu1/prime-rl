#!/usr/bin/env python3
"""Generate synthetic financial dataset stored in SQLite with YAML config."""
import numpy as np
import pandas as pd
import sqlite3
import os
from sklearn.datasets import make_classification

np.random.seed(42)

n_samples = 1200
n_features = 10
n_informative = 5
n_redundant = 2

X, y = make_classification(
    n_samples=n_samples,
    n_features=n_features,
    n_informative=n_informative,
    n_redundant=n_redundant,
    random_state=42,
    shuffle=False
)

# Create temporal index (business days)
dates = pd.bdate_range(start='2015-01-01', periods=n_samples)
date_strings = [d.strftime('%Y-%m-%d') for d in dates]

# Create overlapping label end-times: each label spans 5-20 bars forward
rng = np.random.RandomState(42)
spans = rng.randint(5, 21, size=n_samples)
t1_dates = []
for i, s in enumerate(spans):
    end_idx = min(i + s, n_samples - 1)
    t1_dates.append(date_strings[end_idx])

os.makedirs('/app/data', exist_ok=True)

# ---------------------------------------------------------------------------
# Create SQLite database with normalized tables
# ---------------------------------------------------------------------------
db_path = '/app/data/market.db'
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# market_data: observation features
feature_cols = ', '.join([f'f{i} REAL' for i in range(n_features)])
cursor.execute(f'''CREATE TABLE market_data (
    obs_id INTEGER PRIMARY KEY,
    trade_date TEXT NOT NULL,
    {feature_cols}
)''')

# signals: classification labels
cursor.execute('''CREATE TABLE signals (
    obs_id INTEGER PRIMARY KEY,
    signal INTEGER NOT NULL,
    FOREIGN KEY (obs_id) REFERENCES market_data(obs_id)
)''')

# event_windows: temporal span of each label
cursor.execute('''CREATE TABLE event_windows (
    obs_id INTEGER PRIMARY KEY,
    event_start TEXT NOT NULL,
    event_end TEXT NOT NULL,
    FOREIGN KEY (obs_id) REFERENCES market_data(obs_id)
)''')

# Insert features
for i in range(n_samples):
    values = [i, date_strings[i]] + [float(X[i, j]) for j in range(n_features)]
    placeholders = ', '.join(['?'] * (n_features + 2))
    cursor.execute(f'INSERT INTO market_data VALUES ({placeholders})', values)

# Insert labels
for i in range(n_samples):
    cursor.execute('INSERT INTO signals VALUES (?, ?)', (i, int(y[i])))

# Insert event windows
for i in range(n_samples):
    cursor.execute('INSERT INTO event_windows VALUES (?, ?, ?)',
                   (i, date_strings[i], t1_dates[i]))

conn.commit()

# Create indices for efficient querying
cursor.execute('CREATE INDEX idx_trade_date ON market_data(trade_date)')
cursor.execute('CREATE INDEX idx_event_start ON event_windows(event_start)')
cursor.execute('CREATE INDEX idx_event_end ON event_windows(event_end)')
conn.commit()
conn.close()

# ---------------------------------------------------------------------------
# Create YAML configuration
# ---------------------------------------------------------------------------
yaml_content = """# Backtesting analysis configuration
cross_validation:
  n_groups: 6
  n_test_groups: 2
  pct_embargo: 0.01

classifier:
  type: random_forest
  max_depths:
    - 1
    - 2
    - 3
    - 5
    - 10
    - 20
    - null
  n_estimators: 100

random_state: 42
"""

with open('/app/data/config.yaml', 'w') as f:
    f.write(yaml_content)

# ---------------------------------------------------------------------------
# Create stub Makefile
# ---------------------------------------------------------------------------
makefile_content = ".PHONY: all clean\n\nall:\n\t@echo \"Pipeline not yet implemented\"\n\nclean:\n\trm -rf /app/results/*\n"

with open('/app/Makefile', 'w') as f:
    f.write(makefile_content)

os.makedirs('/app/results', exist_ok=True)

print(f"Generated SQLite database at {db_path}")
print(f"  - market_data: {n_samples} rows, {n_features} feature columns")
print(f"  - signals: {n_samples} rows")
print(f"  - event_windows: {n_samples} rows, spans {spans.min()}-{spans.max()} bars")
print(f"Config: /app/data/config.yaml")
print(f"Makefile stub: /app/Makefile")
