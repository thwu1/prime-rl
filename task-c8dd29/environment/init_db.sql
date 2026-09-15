-- Portfolio database for reserve valuation

CREATE TABLE policy_groups (
    group_code TEXT PRIMARY KEY,
    issue_age INTEGER NOT NULL,
    benefit_amount REAL NOT NULL,
    in_force_count INTEGER NOT NULL
);

CREATE TABLE expense_loadings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loading_type TEXT NOT NULL CHECK(loading_type IN ('premium', 'policy')),
    timing TEXT NOT NULL CHECK(timing IN ('initial', 'renewal')),
    rate REAL NOT NULL
);

CREATE TABLE settlement_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_type TEXT NOT NULL,
    amount REAL NOT NULL
);

CREATE TABLE reinsurance (
    group_code TEXT PRIMARY KEY,
    retention REAL NOT NULL,
    quota_share_ceded_pct REAL NOT NULL,
    FOREIGN KEY (group_code) REFERENCES policy_groups(group_code)
);

-- Policy groups
INSERT INTO policy_groups VALUES ('G1', 35, 100000, 1500);
INSERT INTO policy_groups VALUES ('G2', 45, 250000, 800);
INSERT INTO policy_groups VALUES ('G3', 55, 150000, 400);
INSERT INTO policy_groups VALUES ('G4', 65, 75000, 200);

-- Expense loadings (one row per loading_type x timing)
INSERT INTO expense_loadings (loading_type, timing, rate) VALUES ('premium', 'initial', 0.50);
INSERT INTO expense_loadings (loading_type, timing, rate) VALUES ('premium', 'renewal', 0.05);
INSERT INTO expense_loadings (loading_type, timing, rate) VALUES ('policy', 'initial', 400.0);
INSERT INTO expense_loadings (loading_type, timing, rate) VALUES ('policy', 'renewal', 40.0);

-- Settlement expense at death
INSERT INTO settlement_expenses (expense_type, amount) VALUES ('death_claim', 100.0);

-- Reinsurance terms per group (surplus + quota share)
INSERT INTO reinsurance VALUES ('G1', 100000, 0.0);
INSERT INTO reinsurance VALUES ('G2', 100000, 0.25);
INSERT INTO reinsurance VALUES ('G3', 100000, 0.40);
INSERT INTO reinsurance VALUES ('G4', 50000, 0.30);
