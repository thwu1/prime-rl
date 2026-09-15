CREATE TABLE parameters (key TEXT PRIMARY KEY, value REAL NOT NULL);
INSERT INTO parameters VALUES ('throttle_K', 2.0);
INSERT INTO parameters VALUES ('throttle_window_steps', 10);
INSERT INTO parameters VALUES ('retry_budget_fraction', 0.10);
INSERT INTO parameters VALUES ('crash_threshold', 1.5);
INSERT INTO parameters VALUES ('crash_consecutive_steps', 3);
INSERT INTO parameters VALUES ('crash_offline_steps', 5);
INSERT INTO parameters VALUES ('crash_recovery_capacity_fraction', 0.5);
INSERT INTO parameters VALUES ('crash_recovery_steps', 3);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time_step INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    cluster_name TEXT,
    value REAL NOT NULL
);
INSERT INTO events (time_step, event_type, cluster_name, value) VALUES (10, 'capacity_change', 'alpha', 0);
INSERT INTO events (time_step, event_type, cluster_name, value) VALUES (30, 'load_change', NULL, 6500);
INSERT INTO events (time_step, event_type, cluster_name, value) VALUES (55, 'capacity_change', 'alpha', 2000);
INSERT INTO events (time_step, event_type, cluster_name, value) VALUES (55, 'load_change', NULL, 2500);

CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO metadata VALUES ('duration_steps', '80');
INSERT INTO metadata VALUES ('base_load_qps', '5000');
INSERT INTO metadata VALUES ('service_name', 'payment-gateway');
