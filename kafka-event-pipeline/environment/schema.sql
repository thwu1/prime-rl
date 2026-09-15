CREATE TABLE IF NOT EXISTS outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    key TEXT,
    value TEXT NOT NULL,
    created_at REAL NOT NULL,
    published_at REAL,
    status TEXT DEFAULT 'pending'
);
