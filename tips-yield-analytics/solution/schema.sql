CREATE TABLE IF NOT EXISTS nominal_yields (
    date TEXT NOT NULL,
    tenor REAL NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (date, tenor)
);

CREATE TABLE IF NOT EXISTS real_yields (
    date TEXT NOT NULL,
    tenor REAL NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (date, tenor)
);

CREATE TABLE IF NOT EXISTS h15_rates (
    date TEXT NOT NULL,
    series_id TEXT NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (date, series_id)
);

CREATE TABLE IF NOT EXISTS cpi_monthly (
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (year, month)
);

CREATE TABLE IF NOT EXISTS tips_securities (
    cusip TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    maturity_date TEXT NOT NULL,
    interest_rate REAL NOT NULL,
    ref_cpi_issue REAL NOT NULL,
    ref_cpi_dated REAL NOT NULL,
    index_ratio_issue REAL NOT NULL,
    PRIMARY KEY (cusip, issue_date)
);

CREATE INDEX IF NOT EXISTS idx_nominal_date ON nominal_yields(date);
CREATE INDEX IF NOT EXISTS idx_real_date ON real_yields(date);
CREATE INDEX IF NOT EXISTS idx_h15_date ON h15_rates(date);
CREATE INDEX IF NOT EXISTS idx_tips_cusip ON tips_securities(cusip);
