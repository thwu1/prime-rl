CREATE TABLE IF NOT EXISTS ate_results (
    query_id TEXT PRIMARY KEY,
    treatment TEXT NOT NULL,
    outcome TEXT NOT NULL,
    t1_val REAL NOT NULL,
    t0_val REAL NOT NULL,
    ate_estimate REAL NOT NULL,
    n_samples INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ctf_te_results (
    query_id TEXT PRIMARY KEY,
    treatment TEXT NOT NULL,
    outcome TEXT NOT NULL,
    factual_condition TEXT NOT NULL,
    t1_val REAL NOT NULL,
    t0_val REAL NOT NULL,
    ctf_te_estimate REAL NOT NULL,
    n_samples INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS d_separation_results (
    test_id TEXT PRIMARY KEY,
    x_nodes TEXT NOT NULL,
    y_nodes TEXT NOT NULL,
    z_nodes TEXT NOT NULL,
    is_d_separated INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admg_edges (
    edge_type TEXT NOT NULL CHECK(edge_type IN ('directed', 'bidirected')),
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    PRIMARY KEY (edge_type, source_node, target_node)
);

CREATE TABLE IF NOT EXISTS backdoor_results (
    treatment TEXT NOT NULL,
    outcome TEXT NOT NULL,
    adjustment_set TEXT,
    is_identifiable INTEGER NOT NULL,
    PRIMARY KEY (treatment, outcome)
);
