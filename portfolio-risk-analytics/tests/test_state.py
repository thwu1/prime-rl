"""Test portfolio risk report correctness by independent computation."""

import os
import csv
import pytest
import duckdb
import numpy as np
from scipy.stats import norm, skew as scipy_skew, kurtosis as scipy_kurtosis


def load_database():
    """Load all data from the warehouse database."""
    con = duckdb.connect('/app/warehouse.duckdb', read_only=True)

    data = {}
    data['securities'] = con.execute(
        "SELECT security_id, currency FROM securities"
    ).fetchall()
    data['prices'] = con.execute(
        "SELECT security_id, trade_date, close_price FROM daily_prices "
        "ORDER BY security_id, trade_date"
    ).fetchall()
    data['portfolios'] = con.execute(
        "SELECT portfolio_id, benchmark_id FROM portfolios ORDER BY portfolio_id"
    ).fetchall()
    data['holdings'] = con.execute(
        "SELECT portfolio_id, security_id, quantity FROM holdings"
    ).fetchall()
    data['fx'] = con.execute(
        "SELECT currency, rate_date, rate_to_usd FROM fx_rates "
        "ORDER BY currency, rate_date"
    ).fetchall()
    data['benchmarks'] = con.execute(
        "SELECT benchmark_id, trade_date, daily_return FROM benchmark_returns "
        "ORDER BY benchmark_id, trade_date"
    ).fetchall()
    data['rf'] = con.execute(
        "SELECT trade_date, daily_rate FROM risk_free_rates ORDER BY trade_date"
    ).fetchall()
    data['actions'] = con.execute(
        "SELECT security_id, action_date, action_type, factor "
        "FROM corporate_actions"
    ).fetchall()
    data['dividends'] = con.execute(
        "SELECT security_id, ex_date, amount FROM dividends "
        "ORDER BY security_id, ex_date"
    ).fetchall()

    con.close()
    return data


def compute_expected(data):
    """Independently compute expected risk metrics from raw database data."""
    sec_currency = {row[0]: row[1] for row in data['securities']}

    # Price lookup
    prices = {}
    dates_set = set()
    for sec_id, td, cp in data['prices']:
        prices[(sec_id, td)] = cp
        dates_set.add(td)
    trading_dates = sorted(dates_set)
    n_days = len(trading_dates)

    # FX lookup with forward-fill for missing dates
    fx_raw = {}
    for cur, rd, rate in data['fx']:
        fx_raw[(cur, rd)] = rate

    fx = {}
    for cur in ['EUR', 'GBP']:
        last_rate = None
        for d in trading_dates:
            key = (cur, d)
            if key in fx_raw:
                last_rate = fx_raw[key]
            if last_rate is not None:
                fx[key] = last_rate
    for d in trading_dates:
        fx[('USD', d)] = 1.0

    # Splits
    splits = {}
    for sec_id, ad, at, factor in data['actions']:
        if at == 'SPLIT':
            splits.setdefault(sec_id, []).append((ad, factor))

    # Dividends lookup: {sec_id: {date: amount}}
    div_lookup = {}
    for sec_id, ex_date, amount in data['dividends']:
        div_lookup.setdefault(sec_id, {})[ex_date] = amount

    # Holdings by portfolio
    holdings = {}
    for pid, sid, qty in data['holdings']:
        holdings.setdefault(pid, []).append((sid, qty))

    # Benchmark returns
    bm_ret = {}
    for bmid, td, ret in data['benchmarks']:
        bm_ret[(bmid, td)] = ret

    # Risk-free rates
    rf = {td: rate for td, rate in data['rf']}

    results = []

    for pf_id, bm_id in data['portfolios']:
        pf_h = holdings.get(pf_id, [])

        # Compute daily portfolio market value and dividend income
        daily_values = []
        daily_div_income = []
        for d in trading_dates:
            val = 0.0
            div_inc = 0.0
            for sec_id, qty in pf_h:
                q = qty
                cur = sec_currency[sec_id]
                # Reverse corporate actions for dates before the action
                if sec_id in splits:
                    for sd, f in splits[sec_id]:
                        if d < sd:
                            q = q / f
                p = prices.get((sec_id, d))
                if p is None:
                    continue
                fxr = fx.get((cur, d), 1.0)
                val += q * p * fxr
                # Dividend income on ex-date
                if sec_id in div_lookup and d in div_lookup[sec_id]:
                    div_inc += q * div_lookup[sec_id][d] * fxr
            daily_values.append(val)
            daily_div_income.append(div_inc)

        dv = np.array(daily_values)
        di = np.array(daily_div_income)

        # Daily total returns (price change + dividend income)
        dr = (dv[1:] + di[1:]) / dv[:-1] - 1

        # Aligned benchmark and risk-free series
        bma = np.array([
            bm_ret[(bm_id, trading_dates[i + 1])]
            for i in range(len(dr))
        ])
        rfa = np.array([
            rf[trading_dates[i + 1]]
            for i in range(len(dr))
        ])

        # 1. Total return (compounded)
        total_ret = np.prod(1 + dr) - 1

        # 2. EWMA volatility (half-life=60, RiskMetrics zero-mean, seed=r[0]^2)
        halflife = 60
        lam = 2.0 ** (-1.0 / halflife)
        ewma_var = dr[0] ** 2
        for t in range(1, len(dr)):
            ewma_var = lam * ewma_var + (1 - lam) * dr[t] ** 2
        ewma_vol = np.sqrt(ewma_var) * np.sqrt(252)

        # 3. Cornish-Fisher VaR at 99%
        z_alpha = norm.ppf(0.01)
        mu = np.mean(dr)
        sigma = np.std(dr, ddof=1)
        S = scipy_skew(dr, bias=False)
        K = scipy_kurtosis(dr, fisher=True, bias=False)
        z_cf = (z_alpha
                + (z_alpha ** 2 - 1) * S / 6
                + (z_alpha ** 3 - 3 * z_alpha) * K / 24
                - (2 * z_alpha ** 3 - 5 * z_alpha) * S ** 2 / 36)
        cf_var = mu + z_cf * sigma

        # 4. Expected Shortfall at 95%
        threshold = np.percentile(dr, 5)
        es_95 = np.mean(dr[dr <= threshold])

        # 5. Max drawdown
        cw = np.cumprod(1 + dr)
        rm = np.maximum.accumulate(cw)
        max_dd = np.min(cw / rm - 1)

        # 6. Sortino ratio (target=0%, annualize via sqrt(252))
        downside = np.minimum(dr, 0)
        dd_daily = np.sqrt(np.mean(downside ** 2))
        sortino = mu / dd_daily * np.sqrt(252)

        # 7. Beta (CAPM, excess returns)
        excess_port = dr - rfa
        excess_bm = bma - rfa
        cm = np.cov(excess_port, excess_bm)
        beta = cm[0, 1] / cm[1, 1]

        # 8. Tracking error
        active = dr - bma
        te = np.std(active, ddof=1) * np.sqrt(252)

        results.append({
            'portfolio_id': pf_id,
            'total_return': round(total_ret, 6),
            'ewma_volatility': round(ewma_vol, 6),
            'cf_var_99': round(cf_var, 6),
            'expected_shortfall_95': round(es_95, 6),
            'max_drawdown': round(max_dd, 6),
            'sortino_ratio': round(sortino, 6),
            'beta': round(beta, 6),
            'tracking_error': round(te, 6),
        })

    return results


class TestRiskReport:
    OUTPUT_PATH = '/app/output/risk_report.csv'
    TOLERANCE = 1e-4

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_database()
        self.expected = compute_expected(self.data)

    def test_output_file_exists(self):
        assert os.path.exists(self.OUTPUT_PATH), \
            f"Output file {self.OUTPUT_PATH} not found"

    def test_csv_has_correct_columns(self):
        with open(self.OUTPUT_PATH) as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

        required = [
            'portfolio_id', 'total_return', 'ewma_volatility', 'cf_var_99',
            'expected_shortfall_95', 'max_drawdown', 'sortino_ratio', 'beta',
            'tracking_error'
        ]
        for col in required:
            assert col in fieldnames, f"Missing column: {col}"

    def test_correct_number_of_rows(self):
        with open(self.OUTPUT_PATH) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"

    def test_portfolio_1_metrics(self):
        self._check_portfolio(1)

    def test_portfolio_2_metrics(self):
        self._check_portfolio(2)

    def test_portfolio_3_metrics(self):
        self._check_portfolio(3)

    def _check_portfolio(self, pf_id):
        with open(self.OUTPUT_PATH) as f:
            reader = csv.DictReader(f)
            rows = {int(r['portfolio_id']): r for r in reader}

        assert pf_id in rows, f"Portfolio {pf_id} not found in output"
        actual = rows[pf_id]
        expected = next(e for e in self.expected if e['portfolio_id'] == pf_id)

        metrics = [
            'total_return', 'ewma_volatility', 'cf_var_99',
            'expected_shortfall_95', 'max_drawdown', 'sortino_ratio',
            'beta', 'tracking_error'
        ]

        for m in metrics:
            a = float(actual[m])
            e = expected[m]
            assert abs(a - e) < self.TOLERANCE, \
                (f"Portfolio {pf_id}, {m}: expected {e}, got {a} "
                 f"(diff={abs(a - e):.8f})")
