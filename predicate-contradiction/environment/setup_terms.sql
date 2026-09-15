-- Legal Predicate Terms Database
-- Entity term assignments and interchangeable position groups for each predicate.
-- Predicate templates, quantities, and truth values are in holdings.yaml.

CREATE TABLE predicate_terms (
    predicate_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    term_name TEXT NOT NULL,
    is_generic INTEGER NOT NULL CHECK (is_generic IN (0, 1)),
    PRIMARY KEY (predicate_id, position)
);

CREATE TABLE interchangeable_groups (
    predicate_id TEXT NOT NULL,
    group_index INTEGER NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (predicate_id, group_index, position)
);

-- A-family: beard tax (single generic term)
INSERT INTO predicate_terms VALUES ('A1', 0, 'suspect', 1);
INSERT INTO predicate_terms VALUES ('A2', 0, 'suspect', 1);
INSERT INTO predicate_terms VALUES ('A3', 0, 'suspect', 1);
INSERT INTO predicate_terms VALUES ('A4', 0, 'suspect', 1);
INSERT INTO predicate_terms VALUES ('A5', 0, 'suspect', 1);

-- B-family: gold fines (single generic term)
INSERT INTO predicate_terms VALUES ('B1', 0, 'accused', 1);
INSERT INTO predicate_terms VALUES ('B2', 0, 'accused', 1);
INSERT INTO predicate_terms VALUES ('B3', 0, 'accused', 1);

-- C-family: copyright originality (single generic term)
INSERT INTO predicate_terms VALUES ('C1', 0, 'work', 1);
INSERT INTO predicate_terms VALUES ('C2', 0, 'work', 1);
INSERT INTO predicate_terms VALUES ('C3', 0, 'work', 1);

-- D-family: contract formation (two specific terms, interchangeable)
INSERT INTO predicate_terms VALUES ('D1', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('D1', 1, 'Bob', 0);
INSERT INTO predicate_terms VALUES ('D2', 0, 'Bob', 0);
INSERT INTO predicate_terms VALUES ('D2', 1, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('D3', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('D3', 1, 'Carol', 0);
INSERT INTO predicate_terms VALUES ('D4', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('D4', 1, 'Bob', 0);
INSERT INTO interchangeable_groups VALUES ('D1', 0, 0);
INSERT INTO interchangeable_groups VALUES ('D1', 0, 1);
INSERT INTO interchangeable_groups VALUES ('D2', 0, 0);
INSERT INTO interchangeable_groups VALUES ('D2', 0, 1);
INSERT INTO interchangeable_groups VALUES ('D3', 0, 0);
INSERT INTO interchangeable_groups VALUES ('D3', 0, 1);
INSERT INTO interchangeable_groups VALUES ('D4', 0, 0);
INSERT INTO interchangeable_groups VALUES ('D4', 0, 1);

-- E-family: licensing (generic vs specific)
INSERT INTO predicate_terms VALUES ('E1', 0, 'person', 1);
INSERT INTO predicate_terms VALUES ('E2', 0, 'Bob Smith', 0);

-- F-family: employment (two generic terms, NOT interchangeable)
INSERT INTO predicate_terms VALUES ('F1', 0, 'employer', 1);
INSERT INTO predicate_terms VALUES ('F1', 1, 'employee', 1);
INSERT INTO predicate_terms VALUES ('F2', 0, 'employer', 1);
INSERT INTO predicate_terms VALUES ('F2', 1, 'employee', 1);

-- G-family: traffic speed (single generic term)
INSERT INTO predicate_terms VALUES ('G1', 0, 'driver', 1);
INSERT INTO predicate_terms VALUES ('G2', 0, 'driver', 1);
INSERT INTO predicate_terms VALUES ('G3', 0, 'driver', 1);

-- H-family: class certification (4 terms, plaintiffs interchangeable)
INSERT INTO predicate_terms VALUES ('H1', 0, 'judge', 1);
INSERT INTO predicate_terms VALUES ('H1', 1, 'Smith', 0);
INSERT INTO predicate_terms VALUES ('H1', 2, 'Jones', 0);
INSERT INTO predicate_terms VALUES ('H1', 3, 'defendant', 1);
INSERT INTO predicate_terms VALUES ('H2', 0, 'judge', 1);
INSERT INTO predicate_terms VALUES ('H2', 1, 'Jones', 0);
INSERT INTO predicate_terms VALUES ('H2', 2, 'Smith', 0);
INSERT INTO predicate_terms VALUES ('H2', 3, 'defendant', 1);
INSERT INTO interchangeable_groups VALUES ('H1', 0, 1);
INSERT INTO interchangeable_groups VALUES ('H1', 0, 2);
INSERT INTO interchangeable_groups VALUES ('H2', 0, 1);
INSERT INTO interchangeable_groups VALUES ('H2', 0, 2);

-- I-family: customs weight (single generic term, strict/non-strict boundaries)
INSERT INTO predicate_terms VALUES ('I1', 0, 'item', 1);
INSERT INTO predicate_terms VALUES ('I2', 0, 'item', 1);
INSERT INTO predicate_terms VALUES ('I3', 0, 'item', 1);

-- J-family: joint venture (interchangeable, mixed generic/specific)
INSERT INTO predicate_terms VALUES ('J1', 0, 'party', 1);
INSERT INTO predicate_terms VALUES ('J1', 1, 'party', 1);
INSERT INTO predicate_terms VALUES ('J2', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('J2', 1, 'Bob', 0);
INSERT INTO predicate_terms VALUES ('J3', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('J3', 1, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('J4', 0, 'party', 1);
INSERT INTO predicate_terms VALUES ('J4', 1, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('J5', 0, 'Alice', 0);
INSERT INTO predicate_terms VALUES ('J5', 1, 'Bob', 0);
INSERT INTO interchangeable_groups VALUES ('J1', 0, 0);
INSERT INTO interchangeable_groups VALUES ('J1', 0, 1);
INSERT INTO interchangeable_groups VALUES ('J2', 0, 0);
INSERT INTO interchangeable_groups VALUES ('J2', 0, 1);
INSERT INTO interchangeable_groups VALUES ('J3', 0, 0);
INSERT INTO interchangeable_groups VALUES ('J3', 0, 1);
INSERT INTO interchangeable_groups VALUES ('J4', 0, 0);
INSERT INTO interchangeable_groups VALUES ('J4', 0, 1);
INSERT INTO interchangeable_groups VALUES ('J5', 0, 0);
INSERT INTO interchangeable_groups VALUES ('J5', 0, 1);
