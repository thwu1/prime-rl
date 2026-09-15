
-- Schema for the pipeline validation database

CREATE TABLE IF NOT EXISTS test_suites (
    id INTEGER PRIMARY KEY,
    suite_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY,
    suite_id INTEGER NOT NULL REFERENCES test_suites(id),
    name TEXT NOT NULL,
    formula TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expected_outputs (
    test_case_id INTEGER PRIMARY KEY REFERENCES test_cases(id),
    columns_json TEXT NOT NULL,
    matrix_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_results (
    test_case_id INTEGER PRIMARY KEY REFERENCES test_cases(id),
    columns_json TEXT,
    matrix_json TEXT,
    status TEXT CHECK(status IN ('pass', 'fail', 'error')),
    error_message TEXT
);

-- Suite 1: basics
INSERT INTO test_suites (id, suite_name) VALUES (1, 'basics');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (1, 1, 'single_numeric', 'x', '{"x": [1.0, 2.0, 3.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (1, '["Intercept", "x"]', '[[1, 1], [1, 2], [1, 3]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (2, 1, 'two_numeric_additive', 'x + y', '{"x": [1.0, 2.0], "y": [3.0, 4.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (2, '["Intercept", "x", "y"]', '[[1, 1, 3], [1, 2, 4]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (3, 1, 'no_intercept_numeric', '0 + x', '{"x": [1.0, 2.0, 3.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (3, '["x"]', '[[1], [2], [3]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (4, 1, 'intercept_only', '1', '{"x": [1.0, 2.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (4, '["Intercept"]', '[[1], [1]]');

-- Suite 2: categorical
INSERT INTO test_suites (id, suite_name) VALUES (2, 'categorical');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (5, 2, 'treatment_with_intercept', 'a', '{"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (5, '["Intercept", "a[T.a2]", "a[T.a3]"]', '[[1,0,0],[1,1,0],[1,0,1],[1,0,0],[1,1,0],[1,0,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (6, 2, 'treatment_no_intercept', '0 + a', '{"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (6, '["a[a1]", "a[a2]", "a[a3]"]', '[[1,0,0],[0,1,0],[0,0,1],[1,0,0],[0,1,0],[0,0,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (7, 2, 'two_categorical_additive', 'a + b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (7, '["Intercept", "a[T.a2]", "b[T.b2]"]', '[[1,0,0],[1,0,1],[1,1,0],[1,1,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (8, 2, 'full_rank_no_intercept_interaction', '0 + a:b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (8, '["a[a1]:b[b1]", "a[a2]:b[b1]", "a[a1]:b[b2]", "a[a2]:b[b2]"]', '[[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]]');

-- Suite 3: contrasts
INSERT INTO test_suites (id, suite_name) VALUES (3, 'contrasts');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (9, 3, 'sum_coding', 'C(a, Sum)', '{"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (9, '["Intercept", "C(a, Sum)[S.a1]", "C(a, Sum)[S.a2]"]', '[[1,1,0],[1,0,1],[1,-1,-1],[1,1,0],[1,0,1],[1,-1,-1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (10, 3, 'poly_coding', 'C(a, Poly)', '{"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (10, '["Intercept", "C(a, Poly).Linear", "C(a, Poly).Quadratic"]', '[[1,-0.7071067811865476,0.4082482904638631],[1,0.0,-0.8164965809277261],[1,0.7071067811865476,0.4082482904638631],[1,-0.7071067811865476,0.4082482904638631],[1,0.0,-0.8164965809277261],[1,0.7071067811865476,0.4082482904638631]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (11, 3, 'helmert_coding', 'C(a, Helmert)', '{"a": ["a1", "a2", "a3", "a4"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (11, '["Intercept", "C(a, Helmert)[H.a2]", "C(a, Helmert)[H.a3]", "C(a, Helmert)[H.a4]"]', '[[1,-1,-1,-1],[1,1,-1,-1],[1,0,2,-1],[1,0,0,3]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (12, 3, 'diff_coding', 'C(a, Diff)', '{"a": ["a1", "a2", "a3", "a4"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (12, '["Intercept", "C(a, Diff)[D.a1]", "C(a, Diff)[D.a2]", "C(a, Diff)[D.a3]"]', '[[1,-0.75,-0.5,-0.25],[1,0.25,-0.5,-0.25],[1,0.25,0.5,-0.25],[1,0.25,0.5,0.75]]');

-- Suite 4: operators
INSERT INTO test_suites (id, suite_name) VALUES (4, 'operators');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (13, 4, 'star_full_interaction', 'a * b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (13, '["Intercept", "a[T.a2]", "b[T.b2]", "a[T.a2]:b[T.b2]"]', '[[1,0,0,0],[1,0,1,0],[1,1,0,0],[1,1,1,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (14, 4, 'colon_cat_numeric', 'a:x', '{"a": ["a1", "a1", "a2", "a2"], "x": [1.0, 2.0, 3.0, 4.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (14, '["Intercept", "a[a1]:x", "a[a2]:x"]', '[[1,1,0],[1,2,0],[1,0,3],[1,0,4]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (15, 4, 'colon_numeric_numeric', 'x1:x2', '{"x1": [1.0, 2.0, 3.0], "x2": [4.0, 5.0, 6.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (15, '["Intercept", "x1:x2"]', '[[1,4],[1,10],[1,18]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (16, 4, 'minus_removes_term', 'a * b - a:b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (16, '["Intercept", "a[T.a2]", "b[T.b2]"]', '[[1,0,0],[1,0,1],[1,1,0],[1,1,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (17, 4, 'slash_nesting', 'a / b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (17, '["Intercept", "a[T.a2]", "a[a1]:b[T.b2]", "a[a2]:b[T.b2]"]', '[[1,0,0,0],[1,0,1,0],[1,1,0,0],[1,1,0,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (18, 4, 'power_equals_star', '(a + b) ** 2', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (18, '["Intercept", "a[T.a2]", "b[T.b2]", "a[T.a2]:b[T.b2]"]', '[[1,0,0,0],[1,0,1,0],[1,1,0,0],[1,1,1,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (19, 4, 'intercept_with_interaction_rbug1', '1 + a:b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (19, '["Intercept", "b[T.b2]", "a[T.a2]:b[b1]", "a[T.a2]:b[b2]"]', '[[1,0,0,0],[1,1,0,0],[1,0,1,0],[1,1,0,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (20, 4, 'paren_intercept_retention', '(a - 1)', '{"a": ["a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (20, '["Intercept", "a[T.a2]", "a[T.a3]"]', '[[1,0,0],[1,1,0],[1,0,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (21, 4, 'bare_intercept_removal', 'a - 1', '{"a": ["a1", "a2", "a3"]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (21, '["a[a1]", "a[a2]", "a[a3]"]', '[[1,0,0],[0,1,0],[0,0,1]]');

-- Suite 5: advanced
INSERT INTO test_suites (id, suite_name) VALUES (5, 'advanced');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (22, 5, 'center_transform', 'center(x)', '{"x": [1.0, 2.0, 3.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (22, '["Intercept", "center(x)"]', '[[1,-1],[1,0],[1,1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (23, 5, 'standardize_transform', 'standardize(x)', '{"x": [12.0, 10.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (23, '["Intercept", "standardize(x)"]', '[[1,1],[1,-1]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (24, 5, 'term_ordering_by_numeric_groups', 'x1:x2 + a:b + b + a', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"], "x1": [1.0, 2.0, 3.0, 4.0], "x2": [5.0, 6.0, 7.0, 8.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (24, '["Intercept", "b[T.b2]", "a[T.a2]", "a[T.a2]:b[T.b2]", "x1:x2"]', '[[1,0,0,0,5.0],[1,1,0,0,12.0],[1,0,1,0,21.0],[1,1,1,1,32.0]]');

INSERT INTO test_cases (id, suite_id, name, formula, data_json) VALUES
    (25, 5, 'numeric_grouping_separation_rbug2', '0 + a:x + a:b', '{"a": ["a1", "a1", "a2", "a2"], "b": ["b1", "b2", "b1", "b2"], "x": [1.0, 2.0, 3.0, 4.0]}');
INSERT INTO expected_outputs (test_case_id, columns_json, matrix_json) VALUES
    (25, '["a[a1]:b[b1]", "a[a2]:b[b1]", "a[a1]:b[b2]", "a[a2]:b[b2]", "a[a1]:x", "a[a2]:x"]', '[[1,0,0,0,1,0],[0,0,1,0,2,0],[0,1,0,0,0,3],[0,0,0,1,0,4]]');
