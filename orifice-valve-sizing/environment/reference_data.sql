-- Reference calibration data for flow measurement pipeline.
-- Each table stores test case inputs and expected correct outputs.
--

-- ──────────────────────────────────────────────────────────────
-- Orifice discharge coefficient tests
-- ──────────────────────────────────────────────────────────────
CREATE TABLE orifice_C_tests (
    id          TEXT PRIMARY KEY,
    D           REAL NOT NULL,
    Do          REAL NOT NULL,
    rho         REAL NOT NULL,
    mu          REAL NOT NULL,
    m           REAL NOT NULL,
    taps        TEXT NOT NULL,
    expected_C  REAL NOT NULL
);

INSERT INTO orifice_C_tests VALUES
    ('orifice_C_corner',  0.07391, 0.0222, 1.1645909036, 1.8586175309e-05, 0.124431876, 'corner', 0.6000085121443794),
    ('orifice_C_D',       0.07391, 0.0222, 1.1645909036, 1.8586175309e-05, 0.124431876, 'D',      0.5988219225153737),
    ('orifice_C_flange',  0.07391, 0.0222, 1.1645909036, 1.8586175309e-05, 0.124431876, 'flange', 0.5990042535666640);

-- ──────────────────────────────────────────────────────────────
-- Orifice expansibility tests
-- ──────────────────────────────────────────────────────────────
CREATE TABLE orifice_eps_tests (
    id            TEXT PRIMARY KEY,
    D             REAL NOT NULL,
    Do            REAL NOT NULL,
    P1            REAL NOT NULL,
    P2            REAL NOT NULL,
    k             REAL NOT NULL,
    expected_eps  REAL NOT NULL
);

INSERT INTO orifice_eps_tests VALUES
    ('orifice_eps_1', 0.0739, 0.0222, 100000.0, 99000.0, 1.4, 0.9974739057343425);

-- ──────────────────────────────────────────────────────────────
-- Orifice flow rate tests
-- ──────────────────────────────────────────────────────────────
CREATE TABLE orifice_flow_tests (
    id          TEXT PRIMARY KEY,
    D           REAL NOT NULL,
    Do          REAL NOT NULL,
    P1          REAL NOT NULL,
    P2          REAL NOT NULL,
    rho         REAL NOT NULL,
    mu          REAL NOT NULL,
    k           REAL NOT NULL,
    taps        TEXT NOT NULL,
    expected_m  REAL NOT NULL
);

INSERT INTO orifice_flow_tests VALUES
    ('orifice_flow_D', 0.07366, 0.05, 200000.0, 183000.0, 999.1, 0.0011, 1.33, 'D', 7.702338035732143);

-- ──────────────────────────────────────────────────────────────
-- Liquid valve sizing tests
-- D1, D2, d may be NULL (no piping correction)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE valve_liquid_tests (
    id           TEXT PRIMARY KEY,
    rho          REAL NOT NULL,
    Psat         REAL NOT NULL,
    Pc           REAL NOT NULL,
    mu           REAL NOT NULL,
    P1           REAL NOT NULL,
    P2           REAL NOT NULL,
    Q            REAL NOT NULL,
    D1           REAL,
    D2           REAL,
    d            REAL,
    FL           REAL NOT NULL,
    Fd           REAL NOT NULL,
    expected_Kv  REAL NOT NULL
);

INSERT INTO valve_liquid_tests VALUES
    ('valve_liq_non_choked', 965.4, 70100.0, 22120000.0, 3.1472e-4,
     680000.0, 220000.0, 0.1, 0.15, 0.15, 0.15, 0.9, 0.46,
     164.9954763704956),
    ('valve_liq_choked',     965.4, 70100.0, 22120000.0, 3.1472e-4,
     680000.0, 220000.0, 0.1, 0.1,  0.1,  0.1,  0.6, 0.98,
     238.05817216710483),
    ('valve_liq_piping',     965.4, 70100.0, 22120000.0, 3.1472e-4,
     680000.0, 220000.0, 0.1, 0.1,  0.1,  0.095, 0.6, 0.98,
     241.6812562245056);

-- ──────────────────────────────────────────────────────────────
-- Gas valve sizing tests
-- D1, D2, d may be NULL (no piping correction)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE valve_gas_tests (
    id           TEXT PRIMARY KEY,
    T            REAL NOT NULL,
    MW           REAL NOT NULL,
    mu           REAL NOT NULL,
    gamma        REAL NOT NULL,
    Z            REAL NOT NULL,
    P1           REAL NOT NULL,
    P2           REAL NOT NULL,
    Q            REAL NOT NULL,
    D1           REAL,
    D2           REAL,
    d            REAL,
    FL           REAL NOT NULL,
    Fd           REAL NOT NULL,
    xT           REAL NOT NULL,
    expected_Kv  REAL NOT NULL
);

INSERT INTO valve_gas_tests VALUES
    ('valve_gas_piping',  433.0, 44.01, 1.4665e-4, 1.30, 0.988,
     680000.0, 310000.0, 1.0555555555555556,
     0.08, 0.1, 0.05, 0.85, 0.42, 0.60,
     72.58664545391050),
    ('valve_gas_choked',  433.0, 44.01, 1.4665e-4, 1.30, 0.988,
     680000.0, 100000.0, 0.5,
     NULL, NULL, NULL, 0.85, 0.42, 0.60,
     29.671162740732292);
