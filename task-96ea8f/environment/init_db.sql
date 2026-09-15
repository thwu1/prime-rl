CREATE TABLE IF NOT EXISTS submissions (
    task_id TEXT PRIMARY KEY,
    test_outputs TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS solve_log (
    task_id TEXT PRIMARY KEY,
    input_rows INTEGER NOT NULL,
    input_cols INTEGER NOT NULL,
    output_rows INTEGER NOT NULL,
    output_cols INTEGER NOT NULL,
    num_colors INTEGER NOT NULL,
    transformation_type TEXT NOT NULL
);
