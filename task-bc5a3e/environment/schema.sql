-- Kernel crash triage database schema

CREATE TABLE IF NOT EXISTS crashes (
    id TEXT PRIMARY KEY,
    bug_type TEXT NOT NULL,
    access_type TEXT,
    access_size INTEGER,
    faulting_function TEXT NOT NULL,
    task_comm TEXT NOT NULL,
    task_pid INTEGER NOT NULL,
    kernel_version TEXT NOT NULL,
    call_trace_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dedup_groups (
    group_id INTEGER NOT NULL,
    crash_id TEXT NOT NULL,
    FOREIGN KEY (crash_id) REFERENCES crashes(id)
);

CREATE TABLE IF NOT EXISTS evaluations (
    bug_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('resolved', 'unresolved')),
    total_clean_runs INTEGER NOT NULL,
    total_trials INTEGER NOT NULL
);
