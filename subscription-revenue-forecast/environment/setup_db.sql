-- GlobalEd SaaS Financial Model Database
-- Schema version 3.1 — Entity reference data, subscriber snapshots, and par bond rates
-- Rate projections maintained externally in /app/data/rate_curves.csv
-- Hedge contracts maintained in /app/data/hedge_book.csv

CREATE TABLE countries (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    region TEXT,
    incorporation_date TEXT
);

INSERT INTO countries VALUES ('USA', 'United States', 'USD', 'North America', '2018-03-15');
INSERT INTO countries VALUES ('AUS', 'Australia', 'AUD', 'Asia-Pacific', '2019-07-01');
INSERT INTO countries VALUES ('UK', 'United Kingdom', 'GBP', 'Europe', '2019-11-20');

CREATE TABLE subscription_tiers (
    tier_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tier_order INTEGER NOT NULL,
    max_users INTEGER,
    features TEXT
);

INSERT INTO subscription_tiers VALUES (1, 'Starter', 1, 1, 'Basic course access, community forums');
INSERT INTO subscription_tiers VALUES (2, 'Growth', 2, 5, 'Standard access, group sessions, email support');
INSERT INTO subscription_tiers VALUES (3, 'Professional', 3, 20, 'Full access, live workshops, priority support');
INSERT INTO subscription_tiers VALUES (4, 'Business', 4, 50, 'Full access, custom content, dedicated CSM');
INSERT INTO subscription_tiers VALUES (5, 'Enterprise', 5, NULL, 'Unlimited access, SLA, on-site training');

CREATE TABLE base_pricing (
    country_code TEXT REFERENCES countries(code),
    tier_id INTEGER REFERENCES subscription_tiers(tier_id),
    monthly_price REAL NOT NULL,
    effective_date TEXT NOT NULL,
    PRIMARY KEY (country_code, tier_id, effective_date)
);

-- Current pricing effective 2024-01-01
INSERT INTO base_pricing VALUES ('USA', 1, 19.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('USA', 2, 39.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('USA', 3, 69.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('USA', 4, 99.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('USA', 5, 149.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('AUS', 1, 29.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('AUS', 2, 59.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('AUS', 3, 99.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('AUS', 4, 149.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('AUS', 5, 224.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('UK', 1, 14.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('UK', 2, 29.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('UK', 3, 54.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('UK', 4, 79.99, '2024-01-01');
INSERT INTO base_pricing VALUES ('UK', 5, 114.99, '2024-01-01');

-- Historical pricing (superseded, pre-2024)
INSERT INTO base_pricing VALUES ('USA', 1, 14.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('USA', 2, 34.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('USA', 3, 64.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('USA', 4, 94.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('USA', 5, 144.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('AUS', 1, 24.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('AUS', 2, 54.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('AUS', 3, 94.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('AUS', 4, 139.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('AUS', 5, 214.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('UK', 1, 12.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('UK', 2, 24.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('UK', 3, 49.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('UK', 4, 74.99, '2022-01-01');
INSERT INTO base_pricing VALUES ('UK', 5, 109.99, '2022-01-01');

CREATE TABLE subscriber_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code TEXT REFERENCES countries(code),
    tier_id INTEGER REFERENCES subscription_tiers(tier_id),
    subscriber_count INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL
);

-- Opening snapshot 2024-01-01 (forecast starting point)
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 1, 45000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 2, 22000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 3, 12000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 4, 6500, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 5, 2800, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 1, 11000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 2, 5500, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 3, 3000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 4, 1600, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 5, 700, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 1, 17000, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 2, 8500, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 3, 4500, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 4, 2400, '2024-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 5, 1050, '2024-01-01');

-- Historical snapshots (prior periods — not forecast inputs)
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 1, 38000, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 2, 18500, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 3, 10000, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 4, 5500, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 5, 2300, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 1, 8500, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 2, 4200, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 3, 2300, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 4, 1200, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('AUS', 5, 520, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 1, 14000, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 2, 7000, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 3, 3700, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 4, 1900, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('UK', 5, 850, '2023-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 1, 28000, '2022-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 2, 14000, '2022-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 3, 7500, '2022-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 4, 4000, '2022-01-01');
INSERT INTO subscriber_snapshots (country_code, tier_id, subscriber_count, snapshot_date) VALUES ('USA', 5, 1700, '2022-01-01');

-- Data source registry — external data governance
CREATE TABLE data_sources (
    source_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    file_path TEXT,
    last_updated TEXT,
    governance_status TEXT
);

INSERT INTO data_sources VALUES ('DS-001', 'Rate curve projections (CPI, growth, FX spot)', '/app/data/rate_curves.csv', '2023-12-20', 'approved');
INSERT INTO data_sources VALUES ('DS-002', 'FX hedge contract book', '/app/data/hedge_book.csv', '2023-12-18', 'approved');
INSERT INTO data_sources VALUES ('DS-003', 'Credit loss provision rates', '/app/data/credit_provisions.csv', '2024-01-15', 'approved');
INSERT INTO data_sources VALUES ('DS-004', 'Seasonality adjustment factors', '/app/data/seasonality_adjustments.csv', '2023-11-30', 'under_review');
INSERT INTO data_sources VALUES ('DS-005', 'Hedge valuation mark-to-market data', '/app/data/hedge_valuations.parquet', '2024-01-20', 'approved');

-- Audit log — operational records, not forecast inputs
CREATE TABLE audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    country_code TEXT,
    tier_id INTEGER,
    description TEXT,
    impact_usd REAL
);

INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-07-15', 'PRICE_ADJUSTMENT', 'USA', NULL, 'Annual CPI pass-through under PP-2022-06. All tiers increased by $5.', 142000.00);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-07-15', 'PRICE_ADJUSTMENT', 'AUS', NULL, 'Annual CPI pass-through under PP-2022-06. All tiers increased by AUD 5.', 38000.00);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-07-15', 'PRICE_ADJUSTMENT', 'UK', NULL, 'Annual CPI pass-through under PP-2022-06. All tiers increased by GBP 5.', 67000.00);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-09-01', 'POLICY_CHANGE', NULL, NULL, 'Board approved transition from annual CPI pass-through to consensus-based threshold pricing (PP-2023-12). Effective for FY2024 forecast.', NULL);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-10-15', 'DATA_GOVERNANCE', NULL, NULL, 'Rate projections migrated from database tables to external CSV under DS-001. Historical DB rates retained for audit only.', NULL);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-11-01', 'HEDGE_PROGRAM', NULL, NULL, 'Treasury established rolling FX hedge program for AUD and GBP revenue streams. Contracts filed in hedge book (DS-002).', NULL);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-11-20', 'SUBSCRIBER_MIGRATION', 'AUS', 1, 'Migrated 1200 trial users to Starter tier following campaign completion.', 5400.00);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-12-01', 'FX_HEDGE', NULL, NULL, 'Treasury entered 12-month AUD/USD forward contract at 0.665 for Q1-Q4 2024 revenue hedging.', NULL);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2023-12-15', 'CHURN_EVENT', 'UK', 3, 'Lost 3 enterprise clients (Professional tier) due to competitor pricing. Total MRR impact: -GBP 164.97.', -209.51);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2024-01-15', 'CREDIT_REVIEW', NULL, NULL, 'Credit Committee completed FY2024 ECL assessment. Approved provision rates filed in DS-003. Superseded preliminary rates from Risk Assessment.', NULL);
INSERT INTO audit_log (event_date, event_type, country_code, tier_id, description, impact_usd) VALUES ('2024-01-20', 'HEDGE_EFFECTIVENESS', NULL, NULL, 'Treasury completed IFRS 9 hedge effectiveness assessment. Quarterly MTM data filed in DS-005 (Parquet format).', NULL);

-- Churn analytics — operational metric, not a forecast input
CREATE TABLE churn_rates (
    country_code TEXT REFERENCES countries(code),
    tier_id INTEGER REFERENCES subscription_tiers(tier_id),
    fiscal_year INTEGER NOT NULL,
    monthly_churn_rate REAL NOT NULL,
    PRIMARY KEY (country_code, tier_id, fiscal_year)
);

INSERT INTO churn_rates VALUES ('USA', 1, 2024, 0.035);
INSERT INTO churn_rates VALUES ('USA', 2, 2024, 0.028);
INSERT INTO churn_rates VALUES ('USA', 3, 2024, 0.022);
INSERT INTO churn_rates VALUES ('USA', 4, 2024, 0.018);
INSERT INTO churn_rates VALUES ('USA', 5, 2024, 0.012);
INSERT INTO churn_rates VALUES ('AUS', 1, 2024, 0.040);
INSERT INTO churn_rates VALUES ('AUS', 2, 2024, 0.032);
INSERT INTO churn_rates VALUES ('AUS', 3, 2024, 0.025);
INSERT INTO churn_rates VALUES ('AUS', 4, 2024, 0.020);
INSERT INTO churn_rates VALUES ('AUS', 5, 2024, 0.014);
INSERT INTO churn_rates VALUES ('UK', 1, 2024, 0.038);
INSERT INTO churn_rates VALUES ('UK', 2, 2024, 0.030);
INSERT INTO churn_rates VALUES ('UK', 3, 2024, 0.024);
INSERT INTO churn_rates VALUES ('UK', 4, 2024, 0.019);
INSERT INTO churn_rates VALUES ('UK', 5, 2024, 0.013);

-- Historical rate data (retained for audit, NOT for forecast projections)
-- Forecast projections are in /app/data/rate_curves.csv per data governance (DS-001)
CREATE TABLE historical_rates (
    country_code TEXT REFERENCES countries(code),
    fiscal_year INTEGER NOT NULL,
    rate_type TEXT NOT NULL,
    rate_value REAL NOT NULL,
    source TEXT,
    PRIMARY KEY (country_code, fiscal_year, rate_type)
);

INSERT INTO historical_rates VALUES ('USA', 2022, 'cpi', 0.065, 'BLS actual');
INSERT INTO historical_rates VALUES ('USA', 2023, 'cpi', 0.041, 'BLS actual');
INSERT INTO historical_rates VALUES ('AUS', 2022, 'cpi', 0.078, 'ABS actual');
INSERT INTO historical_rates VALUES ('AUS', 2023, 'cpi', 0.056, 'ABS actual');
INSERT INTO historical_rates VALUES ('UK', 2022, 'cpi', 0.091, 'ONS actual');
INSERT INTO historical_rates VALUES ('UK', 2023, 'cpi', 0.047, 'ONS actual');
INSERT INTO historical_rates VALUES ('USA', 2022, 'fx_spot', 1.000, 'Federal Reserve');
INSERT INTO historical_rates VALUES ('USA', 2023, 'fx_spot', 1.000, 'Federal Reserve');
INSERT INTO historical_rates VALUES ('AUS', 2022, 'fx_spot', 0.690, 'RBA');
INSERT INTO historical_rates VALUES ('AUS', 2023, 'fx_spot', 0.670, 'RBA');
INSERT INTO historical_rates VALUES ('UK', 2022, 'fx_spot', 1.220, 'BoE');
INSERT INTO historical_rates VALUES ('UK', 2023, 'fx_spot', 1.240, 'BoE');
INSERT INTO historical_rates VALUES ('USA', 2022, 'subscriber_growth', 0.180, 'Internal');
INSERT INTO historical_rates VALUES ('USA', 2023, 'subscriber_growth', 0.150, 'Internal');
INSERT INTO historical_rates VALUES ('AUS', 2022, 'subscriber_growth', 0.220, 'Internal');
INSERT INTO historical_rates VALUES ('AUS', 2023, 'subscriber_growth', 0.180, 'Internal');
INSERT INTO historical_rates VALUES ('UK', 2022, 'subscriber_growth', 0.200, 'Internal');
INSERT INTO historical_rates VALUES ('UK', 2023, 'subscriber_growth', 0.160, 'Internal');

-- Par bond rates (US Treasury benchmark, as of 2023-12-29)
-- Used for yield curve bootstrapping and NPV discounting
CREATE TABLE par_bond_rates (
    tenor_years INTEGER PRIMARY KEY,
    par_coupon_rate REAL NOT NULL,
    benchmark TEXT NOT NULL,
    as_of_date TEXT NOT NULL
);

INSERT INTO par_bond_rates VALUES (1, 0.0425, 'US Treasury', '2023-12-29');
INSERT INTO par_bond_rates VALUES (2, 0.0450, 'US Treasury', '2023-12-29');
INSERT INTO par_bond_rates VALUES (3, 0.0480, 'US Treasury', '2023-12-29');
INSERT INTO par_bond_rates VALUES (4, 0.0500, 'US Treasury', '2023-12-29');
INSERT INTO par_bond_rates VALUES (5, 0.0515, 'US Treasury', '2023-12-29');

-- Deprecated discount rates (superseded by par bond bootstrapping approach)
-- Retained for audit; DO NOT use for NPV computation
CREATE TABLE flat_discount_rates (
    fiscal_year INTEGER PRIMARY KEY,
    annual_discount_rate REAL NOT NULL,
    source TEXT,
    status TEXT DEFAULT 'superseded'
);

INSERT INTO flat_discount_rates VALUES (2024, 0.045, 'CFO estimate', 'superseded');
INSERT INTO flat_discount_rates VALUES (2025, 0.043, 'CFO estimate', 'superseded');
INSERT INTO flat_discount_rates VALUES (2026, 0.040, 'CFO estimate', 'superseded');
INSERT INTO flat_discount_rates VALUES (2027, 0.038, 'CFO estimate', 'superseded');
INSERT INTO flat_discount_rates VALUES (2028, 0.035, 'CFO estimate', 'superseded');
