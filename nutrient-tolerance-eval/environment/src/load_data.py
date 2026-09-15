#!/usr/bin/env python3
"""Load evaluation data from JSON/TOML files into the SQLite pipeline database."""
import json
import os
import sqlite3
import tomllib

DB_PATH = '/app/pipeline.db'
DATA_DIR = '/app/data'
CONFIG_PATH = '/app/config/pipeline_config.toml'


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE recipes
                 (recipe_id TEXT, nutrient TEXT, actual_value REAL,
                  PRIMARY KEY (recipe_id, nutrient))''')

    c.execute('''CREATE TABLE predictions
                 (system_name TEXT, recipe_id TEXT, nutrient TEXT, predicted_value REAL,
                  PRIMARY KEY (system_name, recipe_id, nutrient))''')

    c.execute('''CREATE TABLE tolerance_rules
                 (nutrient TEXT, tier_order INTEGER, max_actual REAL,
                  tolerance_type TEXT, tolerance_value REAL)''')

    c.execute('''CREATE TABLE fsa_thresholds
                 (nutrient TEXT, low_threshold REAL, high_threshold REAL,
                  PRIMARY KEY (nutrient))''')

    c.execute('''CREATE TABLE config
                 (key TEXT PRIMARY KEY, value TEXT)''')

    c.execute('''CREATE TABLE tolerance_results
                 (system_name TEXT, recipe_id TEXT, nutrient TEXT,
                  within_tolerance INTEGER,
                  PRIMARY KEY (system_name, recipe_id, nutrient))''')

    c.execute('''CREATE TABLE fsa_results
                 (system_name TEXT, recipe_id TEXT, nutrient TEXT,
                  true_label TEXT, predicted_label TEXT,
                  PRIMARY KEY (system_name, recipe_id, nutrient))''')

    c.execute('''CREATE TABLE error_analysis_results
                 (system_name TEXT, nutrient TEXT, bias REAL, mae REAL,
                  rmse REAL, tolerance_margin REAL,
                  PRIMARY KEY (system_name, nutrient))''')

    c.execute('''CREATE TABLE error_analysis_summary
                 (system_name TEXT PRIMARY KEY, overall_mae REAL,
                  overall_rmse REAL, mean_tolerance_margin REAL)''')

    c.execute('''CREATE TABLE composite_scores
                 (system_name TEXT, recipe_id TEXT, tolerance_fraction REAL,
                  fsa_fraction REAL, composite REAL,
                  PRIMARY KEY (system_name, recipe_id))''')

    c.execute('''CREATE TABLE system_ranking
                 (rank_order INTEGER, system_name TEXT, composite_score REAL)''')

    c.execute('''CREATE TABLE significance_results
                 (pair_key TEXT PRIMARY KEY, p_value REAL, significant INTEGER)''')

    # Load ground truth
    with open(os.path.join(DATA_DIR, 'ground_truth.json')) as f:
        gt = json.load(f)
    for rid, nutrients in sorted(gt.items()):
        for nut, val in nutrients.items():
            c.execute('INSERT INTO recipes VALUES (?,?,?)', (rid, nut, val))

    # Load predictions
    pred_dir = os.path.join(DATA_DIR, 'predictions')
    for fname in sorted(os.listdir(pred_dir)):
        if fname.endswith('.json'):
            sysname = fname.replace('.json', '')
            with open(os.path.join(pred_dir, fname)) as f:
                preds = json.load(f)
            for rid, nutrients in sorted(preds.items()):
                for nut, val in nutrients.items():
                    c.execute('INSERT INTO predictions VALUES (?,?,?,?)',
                              (sysname, rid, nut, val))

    # Load tolerance rules
    with open(os.path.join(DATA_DIR, 'tolerance_rules.json')) as f:
        rules = json.load(f)
    for nut, tiers in rules.items():
        for i, tier in enumerate(tiers):
            c.execute('INSERT INTO tolerance_rules VALUES (?,?,?,?,?)',
                      (nut, i, tier.get('max_actual'),
                       tier['tolerance_type'], tier['tolerance_value']))

    # Load FSA thresholds
    with open(os.path.join(DATA_DIR, 'fsa_thresholds.json')) as f:
        fsa = json.load(f)
    for nut, thresh in fsa.items():
        c.execute('INSERT INTO fsa_thresholds VALUES (?,?,?)',
                  (nut, thresh['low'], thresh['high']))

    # Load config from TOML
    with open(CONFIG_PATH, 'rb') as f:
        toml_cfg = tomllib.load(f)
    eval_cfg = toml_cfg['evaluation']
    c.execute('INSERT INTO config VALUES (?,?)',
              ('composite_weights', json.dumps(eval_cfg['composite_weights'])))
    c.execute('INSERT INTO config VALUES (?,?)',
              ('bootstrap', json.dumps(eval_cfg['bootstrap'])))
    c.execute('INSERT INTO config VALUES (?,?)',
              ('significance_level', str(eval_cfg['significance_level'])))
    c.execute('INSERT INTO config VALUES (?,?)',
              ('round_digits', str(eval_cfg['round_digits'])))

    conn.commit()
    conn.close()
    print("Data loaded into", DB_PATH)


if __name__ == '__main__':
    main()
