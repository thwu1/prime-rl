--
-- Required SQLite schema for the OWASP Benchmark scoring engine.
-- Initialize: sqlite3 /app/benchmark.db < /app/schema.sql

CREATE TABLE IF NOT EXISTS expected_results (
    test_name TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    is_true_positive INTEGER NOT NULL CHECK(is_true_positive IN (0, 1)),
    cwe INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tools (
    name TEXT PRIMARY KEY,
    results_file TEXT NOT NULL,
    commercial INTEGER NOT NULL CHECK(commercial IN (0, 1))
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    test_name TEXT NOT NULL,
    cwe INTEGER NOT NULL,
    FOREIGN KEY (tool_name) REFERENCES tools(name),
    FOREIGN KEY (test_name) REFERENCES expected_results(test_name)
);

CREATE TABLE IF NOT EXISTS classifications (
    tool_name TEXT NOT NULL,
    test_name TEXT NOT NULL,
    category TEXT NOT NULL,
    classification TEXT NOT NULL CHECK(classification IN ('TP', 'FN', 'FP', 'TN')),
    PRIMARY KEY (tool_name, test_name),
    FOREIGN KEY (tool_name) REFERENCES tools(name),
    FOREIGN KEY (test_name) REFERENCES expected_results(test_name)
);

CREATE TABLE IF NOT EXISTS category_metrics (
    tool_name TEXT NOT NULL,
    category TEXT NOT NULL,
    tp INTEGER NOT NULL,
    fn INTEGER NOT NULL,
    fp INTEGER NOT NULL,
    tn INTEGER NOT NULL,
    tpr REAL NOT NULL,
    fpr REAL NOT NULL,
    PRIMARY KEY (tool_name, category),
    FOREIGN KEY (tool_name) REFERENCES tools(name)
);

CREATE TABLE IF NOT EXISTS overall_metrics (
    tool_name TEXT PRIMARY KEY,
    macro_tpr REAL NOT NULL,
    macro_fpr REAL NOT NULL,
    youdens_j REAL NOT NULL,
    FOREIGN KEY (tool_name) REFERENCES tools(name)
);
