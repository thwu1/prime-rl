#!/usr/bin/env python3
"""Create the options market SQLite database for calibration task."""
import sqlite3
import random
from math import log, sqrt, exp, erf, pi


def norm_cdf(x):
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def norm_pdf(x):
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs_price(S, K, T, r, sigma, cp='C'):
    if sigma <= 1e-12 or T <= 1e-12:
        if cp == 'C':
            return max(S - K * exp(-r * T), 0.0)
        else:
            return max(K * exp(-r * T) - S, 0.0)
    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if cp == 'C':
        return S * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
    else:
        return K * exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


SPOT = 100.0
RATE = 0.02
MATURITIES = [0.25, 0.5, 1.0, 2.0, 5.0]
STRIKES = [70.0, 80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0, 130.0]
IMPLIED_VOLS = [
    [0.328767, 0.306026, 0.284001, 0.273192, 0.262532, 0.252087, 0.241994, 0.223871, 0.210461],
    [0.315176, 0.294066, 0.273832, 0.264002, 0.254381, 0.245022, 0.236020, 0.219670, 0.206653],
    [0.294777, 0.276838, 0.260079, 0.252117, 0.244439, 0.237064, 0.230020, 0.217073, 0.205924],
    [0.271709, 0.258839, 0.247199, 0.241787, 0.236626, 0.231706, 0.227017, 0.218311, 0.210470],
    [0.250156, 0.243671, 0.237908, 0.235253, 0.232729, 0.230327, 0.228035, 0.223751, 0.219820],
]


def main():
    random.seed(42)
    conn = sqlite3.connect("/app/options.db")
    c = conn.cursor()

    # ---- market_info ----
    c.execute("CREATE TABLE market_info (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in [("valuation_date", "2024-03-15"),
                  ("underlying", "EQIX"),
                  ("spot_price", str(SPOT)),
                  ("currency", "USD"),
                  ("option_style", "european")]:
        c.execute("INSERT INTO market_info VALUES (?, ?)", (k, v))

    # ---- yield_curves ----
    c.execute("""CREATE TABLE yield_curves (
        curve_id TEXT NOT NULL,
        tenor_years REAL NOT NULL,
        rate REAL NOT NULL,
        as_of_date TEXT NOT NULL
    )""")

    tenors = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0]

    # OIS curve - flat at 2% (correct for collateralized derivatives)
    for t in tenors:
        c.execute("INSERT INTO yield_curves VALUES (?,?,?,?)",
                  ("OIS", t, 0.02, "2024-03-15"))

    # LIBOR_3M curve - upward-sloping, significantly higher
    libor = {0.25: 0.032, 0.5: 0.034, 1.0: 0.036, 2.0: 0.038,
             3.0: 0.039, 5.0: 0.040, 7.0: 0.041, 10.0: 0.042, 30.0: 0.043}
    for t in tenors:
        c.execute("INSERT INTO yield_curves VALUES (?,?,?,?)",
                  ("LIBOR_3M", t, libor[t], "2024-03-15"))

    # TREASURY curve - inverted shape
    tsy = {0.25: 0.045, 0.5: 0.044, 1.0: 0.042, 2.0: 0.040,
           3.0: 0.038, 5.0: 0.036, 7.0: 0.034, 10.0: 0.033, 30.0: 0.032}
    for t in tenors:
        c.execute("INSERT INTO yield_curves VALUES (?,?,?,?)",
                  ("TREASURY", t, tsy[t], "2024-03-15"))

    # Stale OIS curve from an earlier date
    for t in tenors:
        c.execute("INSERT INTO yield_curves VALUES (?,?,?,?)",
                  ("OIS", t, 0.03, "2024-01-15"))

    # ---- curve_metadata ----
    c.execute("""CREATE TABLE curve_metadata (
        curve_id TEXT PRIMARY KEY,
        full_name TEXT,
        notes TEXT
    )""")
    c.execute("INSERT INTO curve_metadata VALUES (?,?,?)",
              ("OIS", "Overnight Index Swap",
               "Post-crisis benchmark for CSA-covered portfolios"))
    c.execute("INSERT INTO curve_metadata VALUES (?,?,?)",
              ("LIBOR_3M", "3-Month LIBOR",
               "Legacy interbank rate, includes credit spread over risk-free"))
    c.execute("INSERT INTO curve_metadata VALUES (?,?,?)",
              ("TREASURY", "US Treasury Yields",
               "Sovereign bond yields, reflects term premium and flight-to-quality"))

    # ---- option_quotes ----
    c.execute("""CREATE TABLE option_quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maturity_years REAL NOT NULL,
        strike REAL NOT NULL,
        option_type TEXT NOT NULL CHECK(option_type IN ('C','P')),
        bid REAL,
        ask REAL,
        mid_price REAL,
        implied_vol REAL,
        volume INTEGER DEFAULT 0,
        open_interest INTEGER DEFAULT 0,
        quality_flag TEXT NOT NULL DEFAULT 'GOOD'
            CHECK(quality_flag IN ('GOOD','SUSPECT','STALE')),
        data_source TEXT NOT NULL
    )""")

    for i, T in enumerate(MATURITIES):
        for j, K in enumerate(STRIKES):
            iv = IMPLIED_VOLS[i][j]
            cp = bs_price(SPOT, K, T, RATE, iv, 'C')
            pp = bs_price(SPOT, K, T, RATE, iv, 'P')
            c_spread = max(cp * 0.02, 0.01)
            p_spread = max(pp * 0.03, 0.01)

            # GOOD call from primary exchange
            c.execute("""INSERT INTO option_quotes
                (maturity_years, strike, option_type, bid, ask, mid_price,
                 implied_vol, volume, open_interest, quality_flag, data_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (T, K, "C",
                 round(cp - c_spread / 2, 6), round(cp + c_spread / 2, 6),
                 round(cp, 6), round(iv, 6),
                 random.randint(200, 8000), random.randint(2000, 80000),
                 "GOOD", "ICE"))

            # GOOD put — some with NULL implied_vol
            piv = round(iv, 6) if random.random() > 0.3 else None
            c.execute("""INSERT INTO option_quotes
                (maturity_years, strike, option_type, bid, ask, mid_price,
                 implied_vol, volume, open_interest, quality_flag, data_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (T, K, "P",
                 round(pp - p_spread / 2, 6), round(pp + p_spread / 2, 6),
                 round(pp, 6), piv,
                 random.randint(100, 5000), random.randint(1000, 50000),
                 "GOOD", "ICE"))

            # SUSPECT call from secondary exchange — perturbed IV
            bad_iv = iv * (1.0 + random.uniform(-0.15, 0.15))
            bad_cp = bs_price(SPOT, K, T, RATE, bad_iv, 'C')
            c.execute("""INSERT INTO option_quotes
                (maturity_years, strike, option_type, bid, ask, mid_price,
                 implied_vol, volume, open_interest, quality_flag, data_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (T, K, "C",
                 round(bad_cp * 0.96, 6), round(bad_cp * 1.04, 6),
                 round(bad_cp, 6), round(bad_iv, 6),
                 random.randint(1, 30), random.randint(10, 200),
                 "SUSPECT", "BATS"))

            # STALE call — biased upward
            stale_iv = iv + random.uniform(0.03, 0.10)
            stale_cp = bs_price(SPOT, K, T, RATE, stale_iv, 'C')
            c.execute("""INSERT INTO option_quotes
                (maturity_years, strike, option_type, bid, ask, mid_price,
                 implied_vol, volume, open_interest, quality_flag, data_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (T, K, "C",
                 round(stale_cp * 0.93, 6), round(stale_cp * 1.07, 6),
                 round(stale_cp, 6), round(stale_iv, 6),
                 0, random.randint(50, 500),
                 "STALE", "ICE"))

    conn.commit()
    conn.close()
    print("Database created at /app/options.db")


if __name__ == "__main__":
    main()
