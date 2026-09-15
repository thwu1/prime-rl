-- Sudoku grid archive with analysis task queue

CREATE TABLE grid_sources (
    source_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    url TEXT
);

CREATE TABLE completed_grids (
    grid_id INTEGER PRIMARY KEY,
    grid_string TEXT NOT NULL CHECK(length(grid_string) = 81),
    source_id INTEGER REFERENCES grid_sources(source_id),
    symmetry_class TEXT,
    date_added TEXT,
    notes TEXT
);

CREATE TABLE analysis_queue (
    task_id INTEGER PRIMARY KEY,
    grid_id INTEGER NOT NULL REFERENCES completed_grids(grid_id),
    analysis_type TEXT NOT NULL,
    max_ua_size INTEGER DEFAULT 6,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 5,
    requested_by TEXT,
    created_at TEXT
);

CREATE TABLE analysis_results (
    result_id INTEGER PRIMARY KEY,
    task_id INTEGER REFERENCES analysis_queue(task_id),
    grid_id INTEGER REFERENCES completed_grids(grid_id),
    result_json TEXT,
    completed_at TEXT
);

-- Sources
INSERT INTO grid_sources VALUES (1, 'canonical', 'Standard/identity Sudoku grid', NULL);
INSERT INTO grid_sources VALUES (2, 'royle_collection', 'Grids from Gordon Royle 17-clue puzzle solutions', NULL);
INSERT INTO grid_sources VALUES (3, 'random_valid', 'Randomly generated valid completions', NULL);
INSERT INTO grid_sources VALUES (4, 'mcguire_test', 'McGuire et al. checker test grids', NULL);
INSERT INTO grid_sources VALUES (5, 'digit_transform', 'Digit-permuted variants of canonical', NULL);

-- 15 completed grids
INSERT INTO completed_grids VALUES (1, '234567891567891234891234567342675918675918342918342675423756189756189423189423756', 5, 'cyclic', '2024-01-05', 'Canonical +1 digit shift');
INSERT INTO completed_grids VALUES (2, '345678912678912345912345678453786129786129453129453786534867291867291534291534867', 5, 'cyclic', '2024-01-05', 'Canonical +2 digit shift');
INSERT INTO completed_grids VALUES (3, '456789123123456789789123456231564897564897231897231564312645978645978312978312645', 1, 'near-canonical', '2024-01-10', 'Row permutation of canonical');
INSERT INTO completed_grids VALUES (4, '456789123789123456123456789564897231897231564231564897645978312978312645312645978', 5, 'cyclic', '2024-01-05', 'Canonical +3 digit shift');
INSERT INTO completed_grids VALUES (5, '213456789546789123879123456321564897654897231987231564132645978465978312798312645', 1, 'near-canonical', '2024-01-10', 'Column permutation of canonical');
INSERT INTO completed_grids VALUES (6, '567891234891234567234567891675918342918342675342675918756189423189423756423756189', 5, 'cyclic', '2024-01-05', 'Canonical +4 digit shift');
INSERT INTO completed_grids VALUES (7, '123456789456789123789123456231564897564897231897231564312645978645978312978312645', 1, 'canonical', '2024-01-01', 'Identity/canonical Sudoku grid');
INSERT INTO completed_grids VALUES (8, '678912345912345678345678912786129453129453786453786129867291534291534867534867291', 5, 'cyclic', '2024-01-05', 'Canonical +5 digit shift');
INSERT INTO completed_grids VALUES (9, '789123456456789123123456789231564897564897231897231564978312645645978312312645978', 1, 'near-canonical', '2024-01-12', 'Band/row permutation of canonical');
INSERT INTO completed_grids VALUES (10, '591738264738264591264591738915387642387642915642915387159873426873426159426159873', 5, 'permuted', '2024-01-15', 'Digit permutation of canonical');
INSERT INTO completed_grids VALUES (11, '891234567234567891567891234918342675342675918675918342189423756423756189756189423', 5, 'cyclic', '2024-01-05', 'Canonical +7 digit shift');
INSERT INTO completed_grids VALUES (12, '483921657967345821251876493548132976729564138136798245372689514814253769695417382', 2, 'generic', '2024-02-15', 'Solution grid for Royle puzzle #1138');
INSERT INTO completed_grids VALUES (13, '912345678345678912678912345129453786453786129786129453291534867534867291867291534', 5, 'cyclic', '2024-01-05', 'Canonical +8 digit shift');
INSERT INTO completed_grids VALUES (14, '231564897564897231897231564123456789456789123789123456312645978645978312978312645', 3, 'generic', '2024-03-01', 'Generated grid #4471');
INSERT INTO completed_grids VALUES (15, '312645978645978312978312645123456789456789123789123456231564897564897231897231564', 3, 'generic', '2024-03-05', 'Generated grid #4502');

-- Analysis queue (mix of types and statuses — only task_ids 2,4 are pending ua_mcn)
INSERT INTO analysis_queue VALUES (1, 3, 'basic_count', 4, 'completed', 3, 'system', '2024-01-15');
INSERT INTO analysis_queue VALUES (2, 7, 'ua_mcn', 6, 'pending', 8, 'researcher_a', '2024-06-01');
INSERT INTO analysis_queue VALUES (3, 5, 'symmetry', NULL, 'pending', 2, 'researcher_b', '2024-05-20');
INSERT INTO analysis_queue VALUES (4, 12, 'ua_mcn', 6, 'pending', 7, 'researcher_a', '2024-06-01');
INSERT INTO analysis_queue VALUES (5, 9, 'ua_mcn', 6, 'failed', 5, 'system', '2024-03-10');
INSERT INTO analysis_queue VALUES (6, 1, 'basic_count', 4, 'completed', 1, 'system', '2024-01-10');
INSERT INTO analysis_queue VALUES (7, 14, 'symmetry', NULL, 'completed', 4, 'researcher_b', '2024-04-01');
INSERT INTO analysis_queue VALUES (8, 10, 'full_check', 8, 'pending', 1, 'system', '2024-05-30');

-- Some completed analysis results (for noise)
INSERT INTO analysis_results VALUES (1, 1, 3, '{"ua4_count": 0, "status": "done"}', '2024-01-16');
INSERT INTO analysis_results VALUES (2, 6, 1, '{"ua4_count": 0, "status": "done"}', '2024-01-11');
INSERT INTO analysis_results VALUES (3, 7, 14, '{"symmetry_class": "near-canonical"}', '2024-04-02');

CREATE INDEX idx_queue_status ON analysis_queue(status);
CREATE INDEX idx_queue_type ON analysis_queue(analysis_type);
CREATE INDEX idx_grids_source ON completed_grids(source_id);
