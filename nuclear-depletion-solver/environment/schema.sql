CREATE TABLE nuclides (
    name TEXT PRIMARY KEY
);

CREATE TABLE steps (
    step_number INTEGER PRIMARY KEY,
    cumulative_time_s REAL NOT NULL,
    label TEXT
);

CREATE TABLE concentrations (
    step_number INTEGER NOT NULL,
    nuclide TEXT NOT NULL,
    value_atoms_per_cm3 REAL NOT NULL,
    PRIMARY KEY (step_number, nuclide),
    FOREIGN KEY (step_number) REFERENCES steps(step_number),
    FOREIGN KEY (nuclide) REFERENCES nuclides(name)
);
