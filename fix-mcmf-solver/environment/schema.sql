CREATE TABLE instances (
    name TEXT PRIMARY KEY,
    num_sources INTEGER NOT NULL,
    num_sinks INTEGER NOT NULL,
    num_hubs INTEGER NOT NULL,
    num_edges INTEGER NOT NULL,
    total_supply INTEGER NOT NULL,
    total_demand INTEGER NOT NULL
);

CREATE TABLE optimal_solutions (
    name TEXT PRIMARY KEY,
    max_flow INTEGER NOT NULL,
    min_cost INTEGER NOT NULL,
    FOREIGN KEY (name) REFERENCES instances(name)
);

CREATE TABLE evaluations (
    name TEXT PRIMARY KEY,
    proposed_flow INTEGER NOT NULL,
    proposed_cost INTEGER NOT NULL,
    is_feasible INTEGER NOT NULL,
    is_optimal INTEGER NOT NULL,
    cost_gap INTEGER NOT NULL,
    FOREIGN KEY (name) REFERENCES instances(name)
);
