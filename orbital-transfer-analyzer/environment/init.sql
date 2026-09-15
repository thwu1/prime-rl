-- Orbital mechanics mission planner database
-- Initialize: sqlite3 /app/missions.db < /app/init.sql

CREATE TABLE IF NOT EXISTS bodies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mu REAL NOT NULL,       -- gravitational parameter, km^3/s^2
    radius REAL NOT NULL,   -- equatorial radius, km
    j2 REAL NOT NULL        -- J2 oblateness coefficient
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    body_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    params TEXT NOT NULL,    -- JSON blob
    FOREIGN KEY (body_id) REFERENCES bodies(id)
);

CREATE TABLE IF NOT EXISTS golden_values (
    mission_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value REAL NOT NULL,
    tol_abs REAL,
    tol_rel REAL,
    PRIMARY KEY (mission_id, field),
    FOREIGN KEY (mission_id) REFERENCES missions(id)
);

-- ============================================================
-- Body data
-- ============================================================
INSERT OR IGNORE INTO bodies VALUES (1, 'Earth', 398600.4418, 6378.1366, 0.00108263);

-- ============================================================
-- rv2coe_1: State vectors to classical elements (Curtis Example 4.3)
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('rv2coe_1', 1, 'rv2coe',
    '{"r": [-6045.0, -3490.0, 2500.0], "v": [-3.457, 6.618, 2.533]}');

INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'p_km',     8530.474,   NULL, 0.001);
INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'ecc',      0.17121,    NULL, 0.005);
INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'inc_deg',  153.249,    0.15, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'raan_deg', 255.279,    0.15, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'argp_deg', 20.068,     0.15, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('rv2coe_1', 'nu_deg',   28.446,     0.15, NULL);

-- ============================================================
-- coe2rv_1: Classical elements to state vectors (roundtrip of rv2coe_1)
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('coe2rv_1', 1, 'coe2rv',
    '{"p": 8530.47436396927, "ecc": 0.17121118195416898, "inc_deg": 153.2492285182475, "raan_deg": 255.27928533439618, "argp_deg": 20.068139973005362, "nu_deg": 28.445804984192122}');

INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'r_km_0', -6045.0,  1.0,  NULL);
INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'r_km_1', -3490.0,  1.0,  NULL);
INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'r_km_2',  2500.0,  1.0,  NULL);
INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'v_km_s_0', -3.457, 0.01, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'v_km_s_1',  6.618, 0.01, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('coe2rv_1', 'v_km_s_2',  2.533, 0.01, NULL);

-- ============================================================
-- lambert_1: Planar transfer (Vallado Example 7.5)
-- r0=[15945.34,0,0], r=[12214.83399,10249.46731,0], tof=76 min
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('lambert_1', 1, 'lambert',
    '{"r0": [15945.34, 0.0, 0.0], "r": [12214.83399, 10249.46731, 0.0], "tof_s": 4560.0, "prograde": true}');

INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v0_km_s_0',  2.058925,  0.015, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v0_km_s_1',  2.915956,  0.015, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v0_km_s_2',  0.0,       0.015, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v_km_s_0',  -3.451569,  0.015, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v_km_s_1',   0.910301,  0.015, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_1', 'v_km_s_2',   0.0,       0.015, NULL);

-- ============================================================
-- lambert_2: 3D transfer (Curtis Example 5.2)
-- r0=[5000,10000,2100], r=[-14600,2500,7000], tof=1 h
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('lambert_2', 1, 'lambert',
    '{"r0": [5000.0, 10000.0, 2100.0], "r": [-14600.0, 2500.0, 7000.0], "tof_s": 3600.0, "prograde": true}');

INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v0_km_s_0', -5.9925,   0.02, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v0_km_s_1',  1.9254,   0.02, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v0_km_s_2',  3.2456,   0.02, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v_km_s_0',  -3.3125,   0.02, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v_km_s_1',  -4.1966,   0.02, NULL);
INSERT OR IGNORE INTO golden_values VALUES ('lambert_2', 'v_km_s_2',  -0.38529,  0.02, NULL);

-- ============================================================
-- hohmann_1: LEO to GEO (Vallado Example 6.1)
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('hohmann_1', 1, 'hohmann',
    '{"r_i": 6569.48071, "r_f": 42159.48517}');

INSERT OR IGNORE INTO golden_values VALUES ('hohmann_1', 'dv_total_km_s', 3.935224,  NULL, 0.002);
INSERT OR IGNORE INTO golden_values VALUES ('hohmann_1', 't_trans_s',     18924.167, NULL, 0.002);

-- ============================================================
-- bielliptic_1: Three-impulse transfer (Vallado Example 6.2)
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('bielliptic_1', 1, 'bielliptic',
    '{"r_i": 6569.48071, "r_b": 510251.1366, "r_f": 382688.1366}');

INSERT OR IGNORE INTO golden_values VALUES ('bielliptic_1', 'dv_total_km_s', 3.904057, NULL, 0.002);

-- ============================================================
-- j2_correction_1: Pericenter drift correction (Vallado p.895)
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('j2_correction_1', 1, 'j2_correction',
    '{"a": 6570.0, "ecc": 0.001, "inc_deg": 45.0, "max_delta_r": 30.0}');

INSERT OR IGNORE INTO golden_values VALUES ('j2_correction_1', 'delta_t_s',    2224141.0, NULL, 0.05);
INSERT OR IGNORE INTO golden_values VALUES ('j2_correction_1', 'delta_v_km_s', 0.011782,  NULL, 0.05);

-- ============================================================
-- plane_change_1: Inclination change at GEO
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('plane_change_1', 1, 'plane_change',
    '{"a": 42164.0, "inc_initial_deg": 28.5, "inc_final_deg": 0.0}');

INSERT OR IGNORE INTO golden_values VALUES ('plane_change_1', 'dv_km_s', 1.5134, NULL, 0.005);

-- ============================================================
-- mission_budget_1: Combined LEO-to-GEO with 28.5-degree plane change
-- ============================================================
INSERT OR IGNORE INTO missions VALUES ('mission_budget_1', 1, 'mission_budget',
    '{"r_i": 6570.0, "r_f": 42164.0, "inc_change_deg": 28.5}');

INSERT OR IGNORE INTO golden_values VALUES ('mission_budget_1', 'dv_arrive_total_km_s', 4.294,  NULL, 0.01);
INSERT OR IGNORE INTO golden_values VALUES ('mission_budget_1', 'dv_depart_total_km_s', 6.516,  NULL, 0.01);
INSERT OR IGNORE INTO golden_values VALUES ('mission_budget_1', 'optimal_strategy_code', 1.0,   NULL, NULL);
-- optimal_strategy_code: 0=depart, 1=arrive
