CREATE TABLE IF NOT EXISTS analysis_results (
    site_name TEXT PRIMARY KEY,
    total_settlement REAL,
    has_consolidation INTEGER,
    raw_json TEXT
);
