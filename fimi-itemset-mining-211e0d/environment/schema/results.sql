CREATE TABLE IF NOT EXISTS mining_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('all', 'closed', 'maximal')),
    min_support INTEGER NOT NULL,
    total_itemsets INTEGER NOT NULL,
    per_length_counts TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
