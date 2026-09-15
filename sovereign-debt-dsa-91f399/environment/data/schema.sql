-- Sovereign Debt Sustainability Analysis - Input Data
-- Schema uses entity-attribute-value format for macroeconomic projections.
-- The endogenous_rate flag indicates whether the country's interest
-- rate is market-determined (with a risk premium that depends on the
-- projected debt trajectory). For such countries, the macro_variables
-- table stores 'base_interest_rate' rather than 'effective_interest_rate'.

CREATE TABLE countries (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    base_year INTEGER NOT NULL,
    initial_debt_to_gdp REAL NOT NULL,
    fc_debt_share REAL NOT NULL CHECK(fc_debt_share >= 0 AND fc_debt_share <= 1),
    endogenous_rate INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE macro_variables (
    country_id INTEGER NOT NULL,
    year_offset INTEGER NOT NULL CHECK(year_offset >= 1),
    variable TEXT NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (country_id) REFERENCES countries(id),
    PRIMARY KEY (country_id, year_offset, variable)
);

CREATE TABLE debt_service (
    country_id INTEGER NOT NULL,
    year_offset INTEGER NOT NULL CHECK(year_offset >= 1),
    amortization REAL NOT NULL,
    interest_revenue REAL NOT NULL,
    FOREIGN KEY (country_id) REFERENCES countries(id),
    PRIMARY KEY (country_id, year_offset)
);

CREATE TABLE stress_parameters (
    country_id INTEGER NOT NULL,
    parameter TEXT NOT NULL,
    value REAL NOT NULL,
    FOREIGN KEY (country_id) REFERENCES countries(id),
    PRIMARY KEY (country_id, parameter)
);

CREATE TABLE contingent_liabilities (
    country_id INTEGER NOT NULL,
    year_offset INTEGER NOT NULL CHECK(year_offset >= 1),
    shock_amount REAL NOT NULL,
    FOREIGN KEY (country_id) REFERENCES countries(id),
    PRIMARY KEY (country_id, year_offset)
);

-- Country data
INSERT INTO countries VALUES (1, 'Montavia', 2023, 140.0, 0.05, 0);
INSERT INTO countries VALUES (2, 'Valdoria', 2023, 65.0, 0.35, 0);
INSERT INTO countries VALUES (3, 'Tervalia', 2023, 82.0, 0.20, 1);

-- Montavia macroeconomic projections (EAV format)
INSERT INTO macro_variables VALUES (1, 1, 'real_gdp_growth', 0.008);
INSERT INTO macro_variables VALUES (1, 1, 'inflation_domestic', 0.025);
INSERT INTO macro_variables VALUES (1, 1, 'inflation_foreign', 0.025);
INSERT INTO macro_variables VALUES (1, 1, 'effective_interest_rate', 0.030);
INSERT INTO macro_variables VALUES (1, 1, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 1, 'primary_balance', -0.5);
INSERT INTO macro_variables VALUES (1, 1, 'sfa', 1.5);
INSERT INTO macro_variables VALUES (1, 2, 'real_gdp_growth', 0.010);
INSERT INTO macro_variables VALUES (1, 2, 'inflation_domestic', 0.020);
INSERT INTO macro_variables VALUES (1, 2, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (1, 2, 'effective_interest_rate', 0.032);
INSERT INTO macro_variables VALUES (1, 2, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 2, 'primary_balance', 0.5);
INSERT INTO macro_variables VALUES (1, 2, 'sfa', 1.0);
INSERT INTO macro_variables VALUES (1, 3, 'real_gdp_growth', 0.012);
INSERT INTO macro_variables VALUES (1, 3, 'inflation_domestic', 0.020);
INSERT INTO macro_variables VALUES (1, 3, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (1, 3, 'effective_interest_rate', 0.035);
INSERT INTO macro_variables VALUES (1, 3, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 3, 'primary_balance', 1.0);
INSERT INTO macro_variables VALUES (1, 3, 'sfa', 0.5);
INSERT INTO macro_variables VALUES (1, 4, 'real_gdp_growth', 0.010);
INSERT INTO macro_variables VALUES (1, 4, 'inflation_domestic', 0.020);
INSERT INTO macro_variables VALUES (1, 4, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (1, 4, 'effective_interest_rate', 0.036);
INSERT INTO macro_variables VALUES (1, 4, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 4, 'primary_balance', 1.2);
INSERT INTO macro_variables VALUES (1, 4, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (1, 5, 'real_gdp_growth', 0.008);
INSERT INTO macro_variables VALUES (1, 5, 'inflation_domestic', 0.020);
INSERT INTO macro_variables VALUES (1, 5, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (1, 5, 'effective_interest_rate', 0.037);
INSERT INTO macro_variables VALUES (1, 5, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 5, 'primary_balance', 1.0);
INSERT INTO macro_variables VALUES (1, 5, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (1, 6, 'real_gdp_growth', 0.008);
INSERT INTO macro_variables VALUES (1, 6, 'inflation_domestic', 0.020);
INSERT INTO macro_variables VALUES (1, 6, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (1, 6, 'effective_interest_rate', 0.038);
INSERT INTO macro_variables VALUES (1, 6, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (1, 6, 'primary_balance', 0.8);
INSERT INTO macro_variables VALUES (1, 6, 'sfa', 0.0);

-- Valdoria macroeconomic projections (EAV format)
INSERT INTO macro_variables VALUES (2, 1, 'real_gdp_growth', 0.030);
INSERT INTO macro_variables VALUES (2, 1, 'inflation_domestic', 0.060);
INSERT INTO macro_variables VALUES (2, 1, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 1, 'effective_interest_rate', 0.080);
INSERT INTO macro_variables VALUES (2, 1, 'real_exchange_rate_change', 0.05);
INSERT INTO macro_variables VALUES (2, 1, 'primary_balance', 0.5);
INSERT INTO macro_variables VALUES (2, 1, 'sfa', 0.5);
INSERT INTO macro_variables VALUES (2, 2, 'real_gdp_growth', 0.025);
INSERT INTO macro_variables VALUES (2, 2, 'inflation_domestic', 0.050);
INSERT INTO macro_variables VALUES (2, 2, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 2, 'effective_interest_rate', 0.075);
INSERT INTO macro_variables VALUES (2, 2, 'real_exchange_rate_change', 0.03);
INSERT INTO macro_variables VALUES (2, 2, 'primary_balance', 1.0);
INSERT INTO macro_variables VALUES (2, 2, 'sfa', 0.3);
INSERT INTO macro_variables VALUES (2, 3, 'real_gdp_growth', 0.030);
INSERT INTO macro_variables VALUES (2, 3, 'inflation_domestic', 0.045);
INSERT INTO macro_variables VALUES (2, 3, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 3, 'effective_interest_rate', 0.070);
INSERT INTO macro_variables VALUES (2, 3, 'real_exchange_rate_change', -0.02);
INSERT INTO macro_variables VALUES (2, 3, 'primary_balance', 1.5);
INSERT INTO macro_variables VALUES (2, 3, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (2, 4, 'real_gdp_growth', 0.035);
INSERT INTO macro_variables VALUES (2, 4, 'inflation_domestic', 0.040);
INSERT INTO macro_variables VALUES (2, 4, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 4, 'effective_interest_rate', 0.065);
INSERT INTO macro_variables VALUES (2, 4, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (2, 4, 'primary_balance', 2.0);
INSERT INTO macro_variables VALUES (2, 4, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (2, 5, 'real_gdp_growth', 0.035);
INSERT INTO macro_variables VALUES (2, 5, 'inflation_domestic', 0.035);
INSERT INTO macro_variables VALUES (2, 5, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 5, 'effective_interest_rate', 0.060);
INSERT INTO macro_variables VALUES (2, 5, 'real_exchange_rate_change', -0.01);
INSERT INTO macro_variables VALUES (2, 5, 'primary_balance', 2.5);
INSERT INTO macro_variables VALUES (2, 5, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (2, 6, 'real_gdp_growth', 0.030);
INSERT INTO macro_variables VALUES (2, 6, 'inflation_domestic', 0.035);
INSERT INTO macro_variables VALUES (2, 6, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (2, 6, 'effective_interest_rate', 0.060);
INSERT INTO macro_variables VALUES (2, 6, 'real_exchange_rate_change', 0.02);
INSERT INTO macro_variables VALUES (2, 6, 'primary_balance', 2.0);
INSERT INTO macro_variables VALUES (2, 6, 'sfa', 0.0);

-- Tervalia macroeconomic projections (EAV format)
-- Tervalia has endogenous_rate=1, so the interest rate variable is
-- 'base_interest_rate' (not 'effective_interest_rate').
INSERT INTO macro_variables VALUES (3, 1, 'real_gdp_growth', 0.020);
INSERT INTO macro_variables VALUES (3, 1, 'inflation_domestic', 0.040);
INSERT INTO macro_variables VALUES (3, 1, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 1, 'base_interest_rate', 0.055);
INSERT INTO macro_variables VALUES (3, 1, 'real_exchange_rate_change', 0.02);
INSERT INTO macro_variables VALUES (3, 1, 'primary_balance', -0.5);
INSERT INTO macro_variables VALUES (3, 1, 'sfa', 0.5);
INSERT INTO macro_variables VALUES (3, 2, 'real_gdp_growth', 0.022);
INSERT INTO macro_variables VALUES (3, 2, 'inflation_domestic', 0.035);
INSERT INTO macro_variables VALUES (3, 2, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 2, 'base_interest_rate', 0.057);
INSERT INTO macro_variables VALUES (3, 2, 'real_exchange_rate_change', 0.01);
INSERT INTO macro_variables VALUES (3, 2, 'primary_balance', 0.0);
INSERT INTO macro_variables VALUES (3, 2, 'sfa', 0.3);
INSERT INTO macro_variables VALUES (3, 3, 'real_gdp_growth', 0.025);
INSERT INTO macro_variables VALUES (3, 3, 'inflation_domestic', 0.030);
INSERT INTO macro_variables VALUES (3, 3, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 3, 'base_interest_rate', 0.060);
INSERT INTO macro_variables VALUES (3, 3, 'real_exchange_rate_change', -0.01);
INSERT INTO macro_variables VALUES (3, 3, 'primary_balance', 0.3);
INSERT INTO macro_variables VALUES (3, 3, 'sfa', 0.2);
INSERT INTO macro_variables VALUES (3, 4, 'real_gdp_growth', 0.028);
INSERT INTO macro_variables VALUES (3, 4, 'inflation_domestic', 0.028);
INSERT INTO macro_variables VALUES (3, 4, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 4, 'base_interest_rate', 0.058);
INSERT INTO macro_variables VALUES (3, 4, 'real_exchange_rate_change', 0.0);
INSERT INTO macro_variables VALUES (3, 4, 'primary_balance', 0.5);
INSERT INTO macro_variables VALUES (3, 4, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (3, 5, 'real_gdp_growth', 0.030);
INSERT INTO macro_variables VALUES (3, 5, 'inflation_domestic', 0.025);
INSERT INTO macro_variables VALUES (3, 5, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 5, 'base_interest_rate', 0.055);
INSERT INTO macro_variables VALUES (3, 5, 'real_exchange_rate_change', -0.01);
INSERT INTO macro_variables VALUES (3, 5, 'primary_balance', 0.8);
INSERT INTO macro_variables VALUES (3, 5, 'sfa', 0.0);
INSERT INTO macro_variables VALUES (3, 6, 'real_gdp_growth', 0.030);
INSERT INTO macro_variables VALUES (3, 6, 'inflation_domestic', 0.025);
INSERT INTO macro_variables VALUES (3, 6, 'inflation_foreign', 0.020);
INSERT INTO macro_variables VALUES (3, 6, 'base_interest_rate', 0.053);
INSERT INTO macro_variables VALUES (3, 6, 'real_exchange_rate_change', 0.01);
INSERT INTO macro_variables VALUES (3, 6, 'primary_balance', 0.5);
INSERT INTO macro_variables VALUES (3, 6, 'sfa', 0.0);

-- Debt service data
INSERT INTO debt_service VALUES (1, 1, 20.0, 0.1);
INSERT INTO debt_service VALUES (1, 2, 19.0, 0.1);
INSERT INTO debt_service VALUES (1, 3, 18.5, 0.1);
INSERT INTO debt_service VALUES (1, 4, 18.0, 0.1);
INSERT INTO debt_service VALUES (1, 5, 17.5, 0.1);
INSERT INTO debt_service VALUES (1, 6, 17.0, 0.1);
INSERT INTO debt_service VALUES (2, 1, 8.0, 0.3);
INSERT INTO debt_service VALUES (2, 2, 7.5, 0.3);
INSERT INTO debt_service VALUES (2, 3, 7.0, 0.3);
INSERT INTO debt_service VALUES (2, 4, 6.5, 0.3);
INSERT INTO debt_service VALUES (2, 5, 6.0, 0.3);
INSERT INTO debt_service VALUES (2, 6, 6.0, 0.3);
INSERT INTO debt_service VALUES (3, 1, 10.0, 0.2);
INSERT INTO debt_service VALUES (3, 2, 9.5, 0.2);
INSERT INTO debt_service VALUES (3, 3, 9.0, 0.2);
INSERT INTO debt_service VALUES (3, 4, 8.5, 0.2);
INSERT INTO debt_service VALUES (3, 5, 8.0, 0.2);
INSERT INTO debt_service VALUES (3, 6, 8.0, 0.2);

-- Stress test parameters (EAV format)
INSERT INTO stress_parameters VALUES (1, 'growth_shock', -0.01);
INSERT INTO stress_parameters VALUES (1, 'interest_rate_shock', 0.02);
INSERT INTO stress_parameters VALUES (1, 'pb_shock', -0.5);
INSERT INTO stress_parameters VALUES (1, 'fx_shock', 0.10);
INSERT INTO stress_parameters VALUES (2, 'growth_shock', -0.015);
INSERT INTO stress_parameters VALUES (2, 'interest_rate_shock', 0.025);
INSERT INTO stress_parameters VALUES (2, 'pb_shock', -1.0);
INSERT INTO stress_parameters VALUES (2, 'fx_shock', 0.15);
INSERT INTO stress_parameters VALUES (3, 'growth_shock', -0.012);
INSERT INTO stress_parameters VALUES (3, 'interest_rate_shock', 0.020);
INSERT INTO stress_parameters VALUES (3, 'pb_shock', -0.8);
INSERT INTO stress_parameters VALUES (3, 'fx_shock', 0.12);

-- Contingent liabilities (one-off fiscal shocks added to SFA)
INSERT INTO contingent_liabilities VALUES (3, 3, 2.5);
