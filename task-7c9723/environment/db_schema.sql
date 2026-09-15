CREATE TABLE placements (
    scenario TEXT NOT NULL,
    bank_id INTEGER NOT NULL,
    bank_x INTEGER NOT NULL,
    bank_y INTEGER NOT NULL,
    reader_x INTEGER NOT NULL,
    reader_y INTEGER NOT NULL,
    noc INTEGER NOT NULL,
    hops INTEGER NOT NULL,
    PRIMARY KEY (scenario, bank_id)
);

CREATE TABLE return_path_links (
    scenario TEXT NOT NULL,
    bank_id INTEGER NOT NULL,
    noc INTEGER NOT NULL,
    direction TEXT NOT NULL,
    from_x INTEGER NOT NULL,
    from_y INTEGER NOT NULL,
    to_x INTEGER NOT NULL,
    to_y INTEGER NOT NULL,
    FOREIGN KEY (scenario, bank_id) REFERENCES placements(scenario, bank_id)
);

CREATE TABLE link_utilization (
    scenario TEXT NOT NULL,
    noc INTEGER NOT NULL,
    direction TEXT NOT NULL,
    from_x INTEGER NOT NULL,
    from_y INTEGER NOT NULL,
    to_x INTEGER NOT NULL,
    to_y INTEGER NOT NULL,
    path_count INTEGER NOT NULL,
    PRIMARY KEY (scenario, noc, direction, from_x, from_y, to_x, to_y)
);

CREATE TABLE scenario_summary (
    scenario TEXT PRIMARY KEY,
    total_hops INTEGER NOT NULL,
    congestion_free INTEGER NOT NULL,
    max_link_load INTEGER NOT NULL,
    total_links_used INTEGER NOT NULL,
    theoretical_gbps REAL NOT NULL,
    utilization_factor REAL NOT NULL,
    estimated_gbps REAL NOT NULL
);
