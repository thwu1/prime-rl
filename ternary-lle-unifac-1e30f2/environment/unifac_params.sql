
-- UNIFAC Parameter Database (Original UNIFAC)
-- Normalized relational schema for group-contribution activity-coefficient model
-- Based on published DDBST / Dortmund Data Bank parameters

PRAGMA foreign_keys = ON;

CREATE TABLE parameter_sources (
    id INTEGER PRIMARY KEY,
    citation TEXT NOT NULL,
    year INTEGER NOT NULL,
    priority INTEGER NOT NULL
);

INSERT INTO parameter_sources VALUES
(1, 'Fredenslund et al., Ind. Eng. Chem. Process Des. Dev., 18(4), 714-722, 1979', 1979, 1),
(2, 'Hansen et al., Ind. Eng. Chem. Res., 30(10), 2352-2355, 1991', 1991, 2),
(3, 'Wittig et al., Ind. Eng. Chem. Res., 42(1), 183-188, 2003', 2003, 3);

CREATE TABLE main_groups (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

INSERT INTO main_groups VALUES
(1, 'CH2'),
(2, 'ACH'),
(3, 'ACCH2'),
(4, 'OH'),
(5, 'H2O'),
(6, 'CH2CO'),
(7, 'CH2O'),
(8, 'CNH'),
(9, 'CCN');

CREATE TABLE subgroups (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    main_group_id INTEGER NOT NULL REFERENCES main_groups(id),
    rk REAL NOT NULL,
    qk REAL NOT NULL
);

INSERT INTO subgroups VALUES
(1,  'CH3',   1, 0.9011, 0.848),
(2,  'CH2',   1, 0.6744, 0.540),
(3,  'CH',    1, 0.4469, 0.228),
(4,  'C',     1, 0.2195, 0.000),
(10, 'ACH',   2, 0.5313, 0.400),
(12, 'ACCH3', 3, 1.2663, 0.968),
(13, 'ACCH2', 3, 1.0396, 0.660),
(15, 'OH',    4, 1.0000, 1.200),
(17, 'H2O',   5, 0.9200, 1.400),
(19, 'CH3CO', 6, 1.6724, 1.488),
(20, 'CH2CO', 6, 1.4457, 1.180),
(25, 'CH3O',  7, 1.1450, 1.088),
(26, 'CH2O',  7, 0.9183, 0.780),
(27, 'CHO',   7, 0.6908, 0.468),
(32, 'CH3NH', 8, 1.4337, 1.244),
(33, 'CH2NH', 8, 1.2070, 0.936),
(34, 'CHNH',  8, 0.9795, 0.624),
(41, 'CH3CN', 9, 1.8701, 1.724),
(42, 'CH2CN', 9, 1.6434, 1.416);

CREATE TABLE compounds (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    cas_number TEXT,
    molecular_formula TEXT
);

INSERT INTO compounds VALUES
(1,  'water',        '7732-18-5', 'H2O'),
(2,  'acetone',      '67-64-1',   'C3H6O'),
(3,  'toluene',      '108-88-3',  'C7H8'),
(4,  'ethanol',      '64-17-5',   'C2H6O'),
(5,  'benzene',      '71-43-2',   'C6H6'),
(6,  'cyclohexane',  '110-82-7',  'C6H12'),
(7,  'methanol',     '67-56-1',   'CH4O'),
(8,  '1-propanol',   '71-23-8',   'C3H8O'),
(9,  'acetonitrile', '75-05-8',   'C2H3N'),
(10, '2-butanone',   '78-93-3',   'C4H8O'),
(11, 'diethylether', '60-29-7',   'C4H10O');

CREATE TABLE compound_subgroups (
    compound_id INTEGER NOT NULL REFERENCES compounds(id),
    subgroup_id INTEGER NOT NULL REFERENCES subgroups(id),
    count INTEGER NOT NULL CHECK(count > 0),
    PRIMARY KEY (compound_id, subgroup_id)
);

INSERT INTO compound_subgroups VALUES
(1,  17, 1),
(2,  1,  1),
(2,  19, 1),
(3,  10, 5),
(3,  12, 1),
(4,  1,  1),
(4,  2,  1),
(4,  15, 1),
(5,  10, 6),
(6,  2,  6),
(7,  1,  1),
(7,  15, 1),
(8,  1,  1),
(8,  2,  2),
(8,  15, 1),
(9,  41, 1),
(10, 1,  1),
(10, 2,  1),
(10, 19, 1),
(11, 1,  2),
(11, 25, 1);

CREATE TABLE interaction_params (
    source_group_id INTEGER NOT NULL REFERENCES main_groups(id),
    target_group_id INTEGER NOT NULL REFERENCES main_groups(id),
    a_value REAL NOT NULL,
    param_source_id INTEGER NOT NULL REFERENCES parameter_sources(id),
    PRIMARY KEY (source_group_id, target_group_id, param_source_id)
);

-- Primary parameter set (source 3, priority 3 — most recent / recommended)
INSERT INTO interaction_params VALUES
(1, 1,    0.0,    3),
(1, 2,   61.13,   3),
(1, 3,   76.50,   3),
(1, 4,  986.5,    3),
(1, 5, 1318.0,    3),
(1, 6,  476.40,   3),
(1, 7,  251.5,    3),
(1, 8,  255.7,    3),
(1, 9,  597.0,    3),
(2, 1,  -11.12,   3),
(2, 2,    0.0,    3),
(2, 3,  167.0,    3),
(2, 4,  636.10,   3),
(2, 5,  903.8,    3),
(2, 6,   25.77,   3),
(2, 7,   32.14,   3),
(2, 8,  122.8,    3),
(2, 9,  212.5,    3),
(3, 1,  -69.7,    3),
(3, 2, -146.8,    3),
(3, 3,    0.0,    3),
(3, 4,  803.2,    3),
(3, 5, 5695.0,    3),
(3, 6,  -52.1,    3),
(3, 7,  213.1,    3),
(3, 8,  -49.29,   3),
(3, 9, 6096.0,    3),
(4, 1,  156.4,    3),
(4, 2,   89.6,    3),
(4, 3,   25.82,   3),
(4, 4,    0.0,    3),
(4, 5,  353.5,    3),
(4, 6,   84.0,    3),
(4, 7,   28.06,   3),
(4, 8,   42.7,    3),
(4, 9,    6.712,  3),
(5, 1,  300.0,    3),
(5, 2,  362.3,    3),
(5, 3,  377.6,    3),
(5, 4, -229.1,    3),
(5, 5,    0.0,    3),
(5, 6, -195.4,    3),
(5, 7,  540.5,    3),
(5, 8,  168.0,    3),
(5, 9,  112.6,    3),
(6, 1,   26.76,   3),
(6, 2,  140.10,   3),
(6, 3,  365.8,    3),
(6, 4,  164.5,    3),
(6, 5,  472.5,    3),
(6, 6,    0.0,    3),
(6, 7, -103.6,    3),
(6, 8, -174.2,    3),
(6, 9,  481.7,    3),
(7, 1,   83.36,   3),
(7, 2,   52.13,   3),
(7, 3,   65.69,   3),
(7, 4,  237.7,    3),
(7, 5, -314.7,    3),
(7, 6,  191.1,    3),
(7, 7,    0.0,    3),
(7, 8,  251.5,    3),
(7, 9,  -18.51,   3),
(8, 1,   65.33,   3),
(8, 2,  -22.31,   3),
(8, 3,  223.0,    3),
(8, 4, -150.0,    3),
(8, 5, -448.2,    3),
(8, 6,  394.6,    3),
(8, 7,  -56.08,   3),
(8, 8,    0.0,    3),
(8, 9,  147.10,   3),
(9, 1,   24.82,   3),
(9, 2,  -22.97,   3),
(9, 3, -138.4,    3),
(9, 4,  185.4,    3),
(9, 5,  242.8,    3),
(9, 6, -287.5,    3),
(9, 7,   38.81,   3),
(9, 8, -108.5,    3),
(9, 9,    0.0,    3);

-- Superseded parameters from older publications (source 1, priority 1)
-- A correct solver MUST select the highest-priority entry for each pair
INSERT INTO interaction_params VALUES
(5, 2,  370.0,  1),
(2, 5,  920.0,  1),
(5, 6, -180.0,  1),
(6, 5,  490.0,  1),
(5, 3,  390.0,  1);

-- Additional older entries (source 2, priority 2) for other pairs
INSERT INTO interaction_params VALUES
(1, 5, 1290.0,  2),
(5, 1,  315.0,  2),
(3, 5, 5750.0,  2);
