-- Schema for reactor solver runtime configuration
-- Used by natcirc_sim to control solver behavior

CREATE TABLE solver_options (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    description TEXT
);

INSERT INTO solver_options VALUES ('include_chimney_buoyancy', 0, 'Include chimney/riser buoyancy contribution in driving force (1=yes, 0=no)');
INSERT INTO solver_options VALUES ('max_bisection_iter', 300, 'Maximum number of bisection iterations for flow solver');
INSERT INTO solver_options VALUES ('convergence_tol', 1e-12, 'Relative convergence tolerance for bisection');
INSERT INTO solver_options VALUES ('max_temperature_K', 5000, 'Maximum allowable temperature before flagging divergence');
