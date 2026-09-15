import sqlite3
import json
import os

DB_PATH = "/app/research/data/game_variants.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
CREATE TABLE experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    tile_start INTEGER NOT NULL,
    tile_end INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_date TEXT
)
""")

c.execute("""
CREATE TABLE dice_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    option_label TEXT NOT NULL,
    config TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
)
""")

c.execute("""
CREATE TABLE scoring_config (
    experiment_id INTEGER PRIMARY KEY,
    config_type TEXT NOT NULL,
    config_ref TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
)
""")

c.execute("""
CREATE TABLE benchmark_results (
    experiment_id INTEGER NOT NULL,
    metric TEXT NOT NULL,
    numerator INTEGER,
    denominator INTEGER,
    notes TEXT,
    PRIMARY KEY (experiment_id, metric),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
)
""")

c.execute("""
CREATE TABLE simulation_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    num_games INTEGER NOT NULL,
    mean_score REAL NOT NULL,
    std_score REAL NOT NULL,
    min_score INTEGER NOT NULL,
    max_score INTEGER NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id)
)
""")

experiments = [
    (1, "basic_6tile", "Standard 6-tile Shut the Box with 1d6", 1, 6, "verified", "2024-01-15"),
    (2, "extended_9tile", "9-tile variant with 2d6", 1, 9, "completed", "2024-02-20"),
    (3, "classic_9tile_1d6", "Classic 9-tile with 1d6 only", 1, 9, "verified", "2024-03-10"),
    (4, "large_12tile_2d6", "12-tile with standard 2d6", 1, 12, "completed", "2024-04-05"),
    (5, "mixed_9tile", "9-tile with d6+d4 option", 1, 9, "verified", "2024-05-18"),
    (6, "weighted_6tile", "6-tile with weighted scoring", 1, 6, "completed", "2024-06-22"),
    (7, "weighted_12tile_multi", "12-tile weighted scoring with multi-dice options", 1, 12, "challenge", "2024-07-30"),
    (8, "extreme_15tile", "15-tile experimental variant", 1, 15, "pending", "2024-08-12"),
]
c.executemany("INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)", experiments)

c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (1, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (2, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (3, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (4, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (5, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 4}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (6, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (7, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (7, 'B', ?)",
          [json.dumps({"dice": [{"sides": 4}, {"sides": 4}, {"sides": 4}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (7, 'C', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 8}]})])
c.execute("INSERT INTO dice_options (experiment_id, option_label, config) VALUES (8, 'A', ?)",
          [json.dumps({"dice": [{"sides": 6}, {"sides": 6}, {"sides": 6}]})])

scoring_configs = [
    (1, "uniform", "default"),
    (2, "uniform", "default"),
    (3, "uniform", "default"),
    (4, "uniform", "default"),
    (5, "uniform", "default"),
    (6, "file", "configs/exp6_scoring.json"),
    (7, "file", "configs/exp7_scoring.json"),
    (8, "uniform", "default"),
]
c.executemany("INSERT INTO scoring_config VALUES (?, ?, ?)", scoring_configs)

benchmark_results = [
    (1, "optimal_expected_score", 317, 120, "Exact rational value, verified independently"),
    (3, "optimal_expected_score", 8753, 1296, "Exact rational value"),
    (5, "optimal_expected_score", 4219, 720, "Exact rational value"),
]
c.executemany("INSERT INTO benchmark_results VALUES (?, ?, ?, ?, ?)", benchmark_results)

sim_stats = [
    (7, "random_uniform", 500000, 89.42, 38.71, 0, 188),
    (7, "greedy_max_tile", 500000, 52.18, 31.55, 0, 188),
    (7, "greedy_min_ev", 500000, 34.76, 25.12, 0, 188),
]
for exp_id_val, strategy, num, mean, std, min_s, max_s in sim_stats:
    c.execute("""INSERT INTO simulation_stats
                 (experiment_id, strategy, num_games, mean_score, std_score, min_score, max_score)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (exp_id_val, strategy, num, mean, std, min_s, max_s))

conn.commit()
conn.close()
