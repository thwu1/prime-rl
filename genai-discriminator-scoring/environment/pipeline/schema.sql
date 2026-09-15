-- NIST GenAI Evaluation Database Schema

CREATE TABLE IF NOT EXISTS eval_sets (
    set_name TEXT PRIMARY KEY,
    description TEXT,
    generator TEXT
);

CREATE TABLE IF NOT EXISTS ground_truth (
    set_name TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    true_source TEXT NOT NULL CHECK(true_source IN ('human', 'ai')),
    human_believability REAL,
    PRIMARY KEY (set_name, narrative_id)
);

CREATE TABLE IF NOT EXISTS submissions (
    file_stem TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    docker_id TEXT,
    eval_set TEXT NOT NULL,
    execution_time REAL,
    is_valid INTEGER DEFAULT 1,
    validation_errors TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS predictions (
    file_stem TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    ai_likelihood REAL,
    believability REAL,
    PRIMARY KEY (file_stem, narrative_id),
    FOREIGN KEY (file_stem) REFERENCES submissions(file_stem)
);

CREATE TABLE IF NOT EXISTS metrics (
    file_stem TEXT PRIMARY KEY,
    eval_set TEXT,
    team TEXT,
    n_predictions INTEGER,
    auc_roc REAL,
    brier_score REAL,
    ece REAL,
    mean_believability REAL,
    max_believability REAL,
    mean_human_believability REAL,
    over_deception INTEGER DEFAULT 0,
    composite_score REAL,
    FOREIGN KEY (file_stem) REFERENCES submissions(file_stem)
);
