-- Mortality database schema
-- Stores SOA XTbML table data for actuarial valuations

CREATE TABLE IF NOT EXISTS table_metadata (
    table_id INTEGER PRIMARY KEY,
    content_type TEXT NOT NULL,
    table_name TEXT NOT NULL,
    table_description TEXT,
    source_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS select_rates (
    table_id INTEGER NOT NULL,
    issue_age INTEGER NOT NULL,
    duration INTEGER NOT NULL,
    qx REAL NOT NULL,
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);

CREATE TABLE IF NOT EXISTS ultimate_rates (
    table_id INTEGER NOT NULL,
    attained_age INTEGER NOT NULL,
    qx REAL NOT NULL,
    PRIMARY KEY (table_id, attained_age),
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);

CREATE TABLE IF NOT EXISTS improvement_factors (
    table_id INTEGER NOT NULL,
    age INTEGER NOT NULL,
    year INTEGER NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (table_id, year),
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);
