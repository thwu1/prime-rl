CREATE TABLE algorithms (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    input_constraint TEXT
);

CREATE TABLE work_recurrences (
    algo_id INTEGER NOT NULL REFERENCES algorithms(id),
    branching_factor INTEGER NOT NULL,
    subproblem_divisor INTEGER NOT NULL,
    combine_cost_expr TEXT NOT NULL
);

CREATE TABLE span_recurrences (
    algo_id INTEGER NOT NULL REFERENCES algorithms(id),
    critical_path_branches INTEGER NOT NULL,
    subproblem_divisor INTEGER NOT NULL,
    combine_cost_expr TEXT NOT NULL
);

CREATE TABLE base_cases (
    algo_id INTEGER NOT NULL REFERENCES algorithms(id),
    condition_text TEXT NOT NULL,
    work_value INTEGER NOT NULL,
    span_value INTEGER NOT NULL
);

CREATE TABLE queries (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    description TEXT,
    params_json TEXT NOT NULL
);
