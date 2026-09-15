-- War of Attrition Tournament Database Schema
-- Used by woa-sim --output sqlite to store simulation results.

CREATE TABLE IF NOT EXISTS game_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    game_num INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    winner INTEGER,
    turns INTEGER NOT NULL,
    p1_final_hp INTEGER NOT NULL,
    p2_final_hp INTEGER NOT NULL,
    action_sequence TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS matchup_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    n_games INTEGER NOT NULL,
    p1_wins INTEGER NOT NULL,
    p2_wins INTEGER NOT NULL,
    draws INTEGER NOT NULL,
    avg_turns REAL NOT NULL,
    fairness REAL NOT NULL,
    decisiveness REAL NOT NULL,
    depth REAL NOT NULL,
    variety REAL NOT NULL,
    composite REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parameter_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_results_matchup ON game_results(matchup);
CREATE INDEX IF NOT EXISTS idx_results_run ON game_results(run_id);
CREATE INDEX IF NOT EXISTS idx_summary_run ON matchup_summary(run_id);
