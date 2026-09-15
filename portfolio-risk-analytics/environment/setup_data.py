#!/usr/bin/env python3
"""Generate the portfolio risk analytics DuckDB database."""
import duckdb
import random
import math
from datetime import date, timedelta


def main():
    random.seed(42)

    # Generate trading dates (all 2023 weekdays from Jan 3 to Dec 29)
    start = date(2023, 1, 3)
    end = date(2023, 12, 29)
    dates = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)

    n_days = len(dates)
    date_to_idx = {d: i for i, d in enumerate(dates)}

    # Securities (id, ticker, currency, sector)
    securities = [
        (1, 'AAPL', 'USD', 'Technology'), (2, 'MSFT', 'USD', 'Technology'),
        (3, 'GOOGL', 'USD', 'Technology'), (4, 'AMZN', 'USD', 'Consumer'),
        (5, 'JPM', 'USD', 'Financials'), (6, 'JNJ', 'USD', 'Healthcare'),
        (7, 'XOM', 'USD', 'Energy'), (8, 'PG', 'USD', 'Consumer Staples'),
        (9, 'V', 'USD', 'Financials'), (10, 'HD', 'USD', 'Consumer'),
        (11, 'MA', 'USD', 'Financials'), (12, 'UNH', 'USD', 'Healthcare'),
        (13, 'DIS', 'USD', 'Communication'), (14, 'NVDA', 'USD', 'Technology'),
        (15, 'PFE', 'USD', 'Healthcare'), (16, 'BAC', 'USD', 'Financials'),
        (17, 'KO', 'USD', 'Consumer Staples'), (18, 'CSCO', 'USD', 'Technology'),
        (19, 'INTC', 'USD', 'Technology'), (20, 'WMT', 'USD', 'Consumer Staples'),
        (21, 'SAP', 'EUR', 'Technology'), (22, 'SIE', 'EUR', 'Industrials'),
        (23, 'BAS', 'EUR', 'Materials'), (24, 'ALV', 'EUR', 'Financials'),
        (25, 'DTE', 'EUR', 'Communication'),
        (26, 'SHEL', 'GBP', 'Energy'), (27, 'AZN', 'GBP', 'Healthcare'),
        (28, 'HSBA', 'GBP', 'Financials'), (29, 'BP', 'GBP', 'Energy'),
        (30, 'GSK', 'GBP', 'Healthcare'),
    ]

    n_sec = len(securities)

    initial_prices = {
        1: 130.0, 2: 240.0, 3: 90.0, 4: 85.0, 5: 135.0,
        6: 175.0, 7: 105.0, 8: 150.0, 9: 210.0, 10: 315.0,
        11: 350.0, 12: 490.0, 13: 90.0, 14: 380.0, 15: 52.0,
        16: 35.0, 17: 60.0, 18: 48.0, 19: 54.0, 20: 145.0,
        21: 110.0, 22: 130.0, 23: 45.0, 24: 220.0, 25: 20.0,
        26: 24.0, 27: 105.0, 28: 5.5, 29: 4.5, 30: 14.0,
    }

    # Cash dividends (security_id, ex_date, per_share_amount in local currency)
    dividend_records = [
        (1, date(2023, 2, 10), 0.23),
        (1, date(2023, 5, 12), 0.24),
        (1, date(2023, 8, 11), 0.24),
        (1, date(2023, 11, 10), 0.24),
        (5, date(2023, 1, 6), 1.00),
        (5, date(2023, 4, 6), 1.00),
        (5, date(2023, 7, 6), 1.05),
        (5, date(2023, 10, 6), 1.05),
        (6, date(2023, 2, 21), 1.13),
        (6, date(2023, 5, 22), 1.19),
        (6, date(2023, 8, 21), 1.19),
        (6, date(2023, 11, 20), 1.19),
        (17, date(2023, 3, 15), 0.46),
        (17, date(2023, 6, 14), 0.46),
        (17, date(2023, 9, 14), 0.46),
        (17, date(2023, 12, 14), 0.46),
        (26, date(2023, 2, 16), 0.2875),
        (26, date(2023, 5, 11), 0.2875),
        (26, date(2023, 8, 10), 0.3050),
        (26, date(2023, 11, 16), 0.3050),
        (27, date(2023, 2, 23), 0.95),
        (27, date(2023, 8, 24), 0.95),
        (21, date(2023, 5, 15), 1.50),
        (21, date(2023, 11, 15), 1.50),
    ]

    # Build dividend lookup for price generation
    div_lookup = {}
    for sec_id, ex_date, amount in dividend_records:
        div_lookup.setdefault(sec_id, {})[ex_date] = amount

    # Generate volatilities and drifts
    annual_vols = [random.uniform(0.15, 0.40) for _ in range(n_sec)]
    annual_drifts = [random.uniform(-0.05, 0.20) for _ in range(n_sec)]

    # Generate price series using geometric Brownian motion
    # On ex-dates, subtract dividend from price (simulates real market behavior)
    all_prices = {}
    for i in range(n_sec):
        sec_id = securities[i][0]
        daily_vol = annual_vols[i] / math.sqrt(252)
        daily_drift = annual_drifts[i] / 252

        price_series = [initial_prices[sec_id]]
        for t in range(1, n_days):
            log_ret = random.gauss(daily_drift, daily_vol)
            new_price = price_series[-1] * math.exp(log_ret)

            # Price drops by dividend amount on ex-date
            if sec_id in div_lookup and dates[t] in div_lookup[sec_id]:
                new_price -= div_lookup[sec_id][dates[t]]

            price_series.append(new_price)

        all_prices[sec_id] = price_series

    # Corporate actions: apply splits to create unadjusted price series
    # NVDA (14): 4:1 split on 2023-06-20
    split_date_1 = date(2023, 6, 20)
    split_idx_1 = next(i for i, d in enumerate(dates) if d >= split_date_1)
    actual_split_date_1 = dates[split_idx_1]

    for t in range(split_idx_1, n_days):
        all_prices[14][t] = all_prices[14][t] / 4.0

    # INTC (19): 2:1 split on 2023-09-15
    split_date_2 = date(2023, 9, 15)
    split_idx_2 = next(i for i, d in enumerate(dates) if d >= split_date_2)
    actual_split_date_2 = dates[split_idx_2]

    for t in range(split_idx_2, n_days):
        all_prices[19][t] = all_prices[19][t] / 2.0

    # FX rates (EUR/USD and GBP/USD)
    eur_usd = [1.08]
    gbp_usd = [1.25]
    for t in range(1, n_days):
        eur_usd.append(eur_usd[-1] * math.exp(random.gauss(0, 0.003)))
        gbp_usd.append(gbp_usd[-1] * math.exp(random.gauss(0, 0.003)))

    # Cross-border holidays: FX rates missing on these dates
    eur_missing = {date(2023, 4, 10), date(2023, 5, 1), date(2023, 10, 3)}
    gbp_missing = {date(2023, 5, 1), date(2023, 5, 29), date(2023, 8, 28)}

    # Benchmark returns
    bm1_returns = [random.gauss(0.0004, 0.01) for _ in range(n_days)]
    bm2_returns = [random.gauss(0.0003, 0.009) for _ in range(n_days)]

    # Risk-free rate (~5% annualized)
    rf_daily = 0.05 / 252

    # Portfolios
    portfolios = [
        (1, 'Growth Fund', 'USD', 1),
        (2, 'Value Fund', 'USD', 1),
        (3, 'Global Balanced', 'USD', 2),
    ]

    # Holdings (portfolio_id, security_id, quantity, cost_basis)
    # Quantities reflect post-split share counts
    holdings = [
        # Portfolio 1: Growth-oriented, heavy tech (all USD + dividends)
        (1, 1, 500, 65000.0), (1, 2, 300, 72000.0),
        (1, 3, 400, 36000.0), (1, 14, 2400, 91200.0),
        (1, 12, 100, 49000.0), (1, 6, 200, 35000.0),
        (1, 9, 150, 31500.0), (1, 11, 100, 35000.0),
        # Portfolio 2: Value-oriented (USD + EUR, multiple dividend payers)
        (2, 5, 400, 54000.0), (2, 7, 500, 52500.0),
        (2, 8, 300, 45000.0), (2, 16, 1000, 35000.0),
        (2, 17, 500, 30000.0), (2, 20, 200, 29000.0),
        (2, 21, 300, 33000.0), (2, 24, 150, 33000.0),
        # Portfolio 3: Global balanced (USD + EUR + GBP, splits + dividends + FX)
        (3, 1, 200, 26000.0), (3, 4, 300, 25500.0),
        (3, 7, 250, 26250.0), (3, 14, 800, 30400.0),
        (3, 19, 1000, 27000.0),
        (3, 21, 200, 22000.0), (3, 23, 400, 18000.0),
        (3, 26, 1000, 24000.0), (3, 27, 500, 52500.0),
        (3, 28, 5000, 27500.0), (3, 29, 3000, 13500.0),
    ]

    # Create DuckDB database
    con = duckdb.connect('/app/warehouse.duckdb')

    # Securities table
    con.execute("""
        CREATE TABLE securities (
            security_id INTEGER PRIMARY KEY,
            ticker VARCHAR NOT NULL,
            currency VARCHAR NOT NULL,
            sector VARCHAR NOT NULL
        )
    """)
    for s in securities:
        con.execute("INSERT INTO securities VALUES (?, ?, ?, ?)", list(s))

    # Daily prices table (unadjusted for splits, post-dividend-drop, in local currency)
    con.execute("""
        CREATE TABLE daily_prices (
            security_id INTEGER NOT NULL,
            trade_date DATE NOT NULL,
            close_price DOUBLE NOT NULL,
            PRIMARY KEY (security_id, trade_date)
        )
    """)
    for sec_id in sorted(all_prices.keys()):
        for i, d in enumerate(dates):
            con.execute(
                "INSERT INTO daily_prices VALUES (?, ?, ?)",
                [sec_id, d, round(all_prices[sec_id][i], 4)]
            )

    # Portfolios table
    con.execute("""
        CREATE TABLE portfolios (
            portfolio_id INTEGER PRIMARY KEY,
            portfolio_name VARCHAR NOT NULL,
            base_currency VARCHAR NOT NULL,
            benchmark_id INTEGER NOT NULL
        )
    """)
    for p in portfolios:
        con.execute("INSERT INTO portfolios VALUES (?, ?, ?, ?)", list(p))

    # Holdings table (current/post-split positions)
    con.execute("""
        CREATE TABLE holdings (
            portfolio_id INTEGER NOT NULL,
            security_id INTEGER NOT NULL,
            quantity DOUBLE NOT NULL,
            cost_basis DOUBLE NOT NULL,
            PRIMARY KEY (portfolio_id, security_id)
        )
    """)
    for h in holdings:
        con.execute("INSERT INTO holdings VALUES (?, ?, ?, ?)", list(h))

    # FX rates table (only EUR and GBP; USD has no entries)
    # Some dates missing due to cross-border holidays
    con.execute("""
        CREATE TABLE fx_rates (
            currency VARCHAR NOT NULL,
            rate_date DATE NOT NULL,
            rate_to_usd DOUBLE NOT NULL,
            PRIMARY KEY (currency, rate_date)
        )
    """)
    for i, d in enumerate(dates):
        if d not in eur_missing:
            con.execute("INSERT INTO fx_rates VALUES (?, ?, ?)",
                        ['EUR', d, round(eur_usd[i], 6)])
        if d not in gbp_missing:
            con.execute("INSERT INTO fx_rates VALUES (?, ?, ?)",
                        ['GBP', d, round(gbp_usd[i], 6)])

    # Benchmark returns table
    con.execute("""
        CREATE TABLE benchmark_returns (
            benchmark_id INTEGER NOT NULL,
            trade_date DATE NOT NULL,
            daily_return DOUBLE NOT NULL,
            PRIMARY KEY (benchmark_id, trade_date)
        )
    """)
    for i, d in enumerate(dates):
        con.execute("INSERT INTO benchmark_returns VALUES (?, ?, ?)",
                    [1, d, round(bm1_returns[i], 8)])
        con.execute("INSERT INTO benchmark_returns VALUES (?, ?, ?)",
                    [2, d, round(bm2_returns[i], 8)])

    # Risk-free rates table
    con.execute("""
        CREATE TABLE risk_free_rates (
            trade_date DATE NOT NULL PRIMARY KEY,
            daily_rate DOUBLE NOT NULL
        )
    """)
    for d in dates:
        con.execute("INSERT INTO risk_free_rates VALUES (?, ?)", [d, rf_daily])

    # Corporate actions table
    con.execute("""
        CREATE TABLE corporate_actions (
            security_id INTEGER NOT NULL,
            action_date DATE NOT NULL,
            action_type VARCHAR NOT NULL,
            factor DOUBLE NOT NULL
        )
    """)
    con.execute("INSERT INTO corporate_actions VALUES (?, ?, ?, ?)",
                [14, actual_split_date_1, 'SPLIT', 4.0])
    con.execute("INSERT INTO corporate_actions VALUES (?, ?, ?, ?)",
                [19, actual_split_date_2, 'SPLIT', 2.0])

    # Dividends table (per-share cash amounts, ex-dates)
    con.execute("""
        CREATE TABLE dividends (
            security_id INTEGER NOT NULL,
            ex_date DATE NOT NULL,
            amount DOUBLE NOT NULL,
            PRIMARY KEY (security_id, ex_date)
        )
    """)
    for sec_id, ex_date, amount in dividend_records:
        con.execute("INSERT INTO dividends VALUES (?, ?, ?)",
                    [sec_id, ex_date, amount])

    con.close()
    print(f"Database created: {n_days} trading days, {n_sec} securities, 9 tables")


if __name__ == '__main__':
    main()
