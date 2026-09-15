"""
Reference implementation and verification tests for portfolio backtest task.

"""
import json
import os
import sqlite3
import tomllib
import numpy as np
import pyarrow.parquet as pq
import pytest


# ---------------------------------------------------------------------------
# Reference: load data from SQLite + TOML
# ---------------------------------------------------------------------------

def ref_load_data():
    conn = sqlite3.connect('/app/data/market.db')
    cur = conn.execute(
        'SELECT DISTINCT industry FROM industry_info ORDER BY industry')
    industries = [row[0] for row in cur.fetchall()]
    N = len(industries)
    T = conn.execute(
        'SELECT MAX(period) + 1 FROM monthly_returns').fetchone()[0]
    returns = np.zeros((T, N))
    for row in conn.execute(
            'SELECT period, industry, return_value FROM monthly_returns'):
        period, ind, val = row
        returns[period, industries.index(ind)] = val
    illiquidity = np.zeros(N)
    for row in conn.execute('SELECT industry, illiquidity FROM industry_info'):
        ind, illiq = row
        illiquidity[industries.index(ind)] = illiq
    conn.close()
    with open('/app/config.toml', 'rb') as f:
        config = tomllib.load(f)
    return returns, illiquidity, industries, config


# ---------------------------------------------------------------------------
# Reference: backtest engine
# ---------------------------------------------------------------------------

def ref_compute_efficient_weight(sigma, mu, gamma, beta, w_prev, B_mat):
    n = sigma.shape[0]
    iota = np.ones(n)
    sigma_star = sigma + (beta / gamma) * B_mat
    mu_star = mu + beta * (B_mat @ w_prev)
    sigma_star_inv = np.linalg.inv(sigma_star)
    w_mvp = sigma_star_inv @ iota / (iota @ sigma_star_inv @ iota)
    w_opt = w_mvp + (1.0 / gamma) * (
        sigma_star_inv - np.outer(w_mvp, iota) @ sigma_star_inv
    ) @ mu_star
    return w_opt


def ref_adjust_weights(w, ret):
    w_drifted = w * (1.0 + ret)
    return w_drifted / np.sum(w_drifted)


def ref_run_backtest(returns, illiquidity, config, strategy,
                     beta_construct, beta_eval):
    N = returns.shape[1]
    T = returns.shape[0]
    gamma = config['backtest']['gamma']
    wl = int(config['backtest']['window_length'])
    tc_scale = config['backtest']['tc_scale']
    periods = T - wl
    iota = np.ones(N)
    I_N = np.eye(N)
    B = np.diag(illiquidity)

    w_prev_plus = np.ones(N) / N
    net_rets = np.zeros(periods)
    turnovers = np.zeros(periods)
    weights_record = {}

    for p in range(periods):
        rw = returns[p:p + wl]
        nr = returns[p + wl]
        sigma_hat = np.cov(rw.T)
        mu_hat = rw.mean(axis=0)

        if strategy == 'naive':
            w_new = np.ones(N) / N
        elif strategy == 'mvp':
            si = np.linalg.inv(sigma_hat)
            w_new = si @ iota / (iota @ si @ iota)
        elif strategy == 'mv_tc_iso':
            w_new = ref_compute_efficient_weight(
                sigma_hat, mu_hat, gamma, beta_construct, w_prev_plus, I_N)
        elif strategy == 'mv_tc_illiq':
            w_new = ref_compute_efficient_weight(
                sigma_hat, mu_hat, gamma, beta_construct, w_prev_plus, B)
        else:
            raise ValueError(strategy)

        weights_record[p] = w_new.copy()
        raw_ret = w_new @ nr
        to = np.sum(np.abs(w_new - w_prev_plus) * illiquidity)
        net_rets[p] = raw_ret - (beta_eval / tc_scale) * to
        turnovers[p] = to
        w_prev_plus = ref_adjust_weights(w_new, nr)

    sharpe = np.mean(net_rets) / np.std(net_rets, ddof=1) * np.sqrt(12)
    return {
        'sharpe_ratio': float(sharpe),
        'mean_return_ann_pct': float(np.mean(net_rets) * 12 * 100),
        'volatility_ann_pct': float(
            np.std(net_rets, ddof=1) * np.sqrt(12) * 100),
        'avg_turnover': float(np.mean(turnovers)),
        'weights_record': weights_record,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def data():
    returns, illiquidity, industries, config = ref_load_data()
    return returns, illiquidity, industries, config


@pytest.fixture(scope='session')
def ref(data):
    returns, illiquidity, industries, config = data
    bd = int(config['backtest']['beta_default'])
    strats = {
        'naive':       (0,  'naive'),
        'mvp':         (0,  'mvp'),
        'mv_tc_iso':   (bd, 'mv_tc_iso'),
        'mv_tc_illiq': (bd, 'mv_tc_illiq'),
    }
    results = {}
    for name, (bc, s) in strats.items():
        results[name] = ref_run_backtest(
            returns, illiquidity, config, s, bc, bd)

    gs = config['grid_search']
    beta_grid = list(range(
        int(gs['beta_start']), int(gs['beta_end']) + 1, int(gs['beta_step'])))
    best_sharpe = -np.inf
    best_beta = 0
    for bc in beta_grid:
        r = ref_run_backtest(
            returns, illiquidity, config, 'mv_tc_illiq', bc, bd)
        if r['sharpe_ratio'] > best_sharpe:
            best_sharpe = r['sharpe_ratio']
            best_beta = bc

    return {
        'results': results,
        'optimal_beta': best_beta,
        'optimal_sharpe': best_sharpe,
        'industries': industries,
    }


@pytest.fixture(scope='session')
def agent_perf():
    with open('/app/results/performance.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def agent_opt():
    with open('/app/results/optimal_beta.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def agent_ranking():
    with open('/app/results/strategy_ranking.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def agent_w250():
    with open('/app/results/weights_period_250.json') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def agent_parquet():
    table = pq.read_table('/app/results/weight_history.parquet')
    return table.to_pydict()


# ---------------------------------------------------------------------------
# Tests — output files exist
# ---------------------------------------------------------------------------

class TestFilesExist:
    def test_performance(self):
        assert os.path.exists('/app/results/performance.json')

    def test_optimal_beta(self):
        assert os.path.exists('/app/results/optimal_beta.json')

    def test_ranking(self):
        assert os.path.exists('/app/results/strategy_ranking.json')

    def test_weights(self):
        assert os.path.exists('/app/results/weights_period_250.json')

    def test_parquet(self):
        assert os.path.exists('/app/results/weight_history.parquet')


# ---------------------------------------------------------------------------
# Tests — output format
# ---------------------------------------------------------------------------

class TestFormat:
    STRATS = {'naive', 'mvp', 'mv_tc_iso', 'mv_tc_illiq'}
    METRICS = {'sharpe_ratio', 'mean_return_ann_pct', 'volatility_ann_pct',
               'avg_turnover'}

    def test_perf_keys(self, agent_perf):
        assert set(agent_perf.keys()) == self.STRATS

    def test_perf_metrics(self, agent_perf):
        for s in agent_perf:
            assert set(agent_perf[s].keys()) == self.METRICS

    def test_opt_keys(self, agent_opt):
        assert 'optimal_beta' in agent_opt
        assert 'sharpe_at_optimal' in agent_opt

    def test_ranking_len(self, agent_ranking):
        assert len(agent_ranking) == 4

    def test_ranking_set(self, agent_ranking):
        assert set(agent_ranking) == self.STRATS

    def test_w250_keys(self, agent_w250):
        assert set(agent_w250.keys()) == self.STRATS

    def test_w250_is_dict_of_dicts(self, agent_w250):
        for s in agent_w250:
            assert isinstance(agent_w250[s], dict), \
                f"{s} weights should be a dict mapping industry to weight"

    def test_w250_length(self, agent_w250):
        for s in agent_w250:
            assert len(agent_w250[s]) == 10, \
                f"{s} has {len(agent_w250[s])} weights, expected 10"

    def test_w250_industry_keys(self, agent_w250, ref):
        expected = set(ref['industries'])
        for s in agent_w250:
            assert set(agent_w250[s].keys()) == expected, \
                f"{s} industry keys mismatch"


# ---------------------------------------------------------------------------
# Tests — Parquet structure and content
# ---------------------------------------------------------------------------

class TestParquet:
    def test_has_required_columns(self, agent_parquet, ref):
        required = {'period', 'strategy'} | set(ref['industries'])
        actual = set(agent_parquet.keys())
        assert required.issubset(actual), \
            f"Missing Parquet columns: {required - actual}"

    def test_row_count(self, agent_parquet, data):
        _, _, _, config = data
        returns, _, _, _ = data
        T = returns.shape[0]
        wl = int(config['backtest']['window_length'])
        expected_rows = (T - wl) * 4
        actual_rows = len(agent_parquet['period'])
        assert actual_rows == expected_rows, \
            f"Expected {expected_rows} Parquet rows, got {actual_rows}"

    def test_strategies_present(self, agent_parquet):
        strats = set(agent_parquet['strategy'])
        assert strats == {'naive', 'mvp', 'mv_tc_iso', 'mv_tc_illiq'}

    def test_weights_sum_to_one(self, agent_parquet, ref):
        industries = ref['industries']
        n_rows = len(agent_parquet['period'])
        # Spot-check every 50th row
        for i in range(0, n_rows, 50):
            total = sum(agent_parquet[ind][i] for ind in industries)
            assert abs(total - 1.0) < 1e-4, \
                f"Parquet row {i}: weights sum to {total}"

    def test_parquet_matches_json_period_250(self, agent_parquet, agent_w250,
                                             ref):
        """Parquet weights at period 250 must match weights_period_250.json."""
        industries = ref['industries']
        n_rows = len(agent_parquet['period'])
        found = False
        for i in range(n_rows):
            if (agent_parquet['period'][i] == 250
                    and agent_parquet['strategy'][i] == 'mv_tc_illiq'):
                for ind in industries:
                    pq_w = agent_parquet[ind][i]
                    json_w = agent_w250['mv_tc_illiq'][ind]
                    assert abs(pq_w - json_w) < 0.01, \
                        f"Parquet vs JSON mismatch for {ind} at period 250"
                found = True
                break
        assert found, "Period 250 mv_tc_illiq not found in Parquet"


# ---------------------------------------------------------------------------
# Tests — weight constraints
# ---------------------------------------------------------------------------

class TestWeightConstraints:
    def test_weights_sum_to_one(self, agent_w250):
        for s in agent_w250:
            total = sum(agent_w250[s].values())
            assert abs(total - 1.0) < 1e-4, \
                f"{s} weights sum to {total}"

    def test_naive_equal(self, agent_w250):
        for ind, wi in agent_w250['naive'].items():
            assert abs(wi - 0.1) < 1e-6


# ---------------------------------------------------------------------------
# Tests — naive strategy
# ---------------------------------------------------------------------------

class TestNaive:
    def test_sharpe(self, ref, agent_perf):
        r = ref['results']['naive']['sharpe_ratio']
        a = agent_perf['naive']['sharpe_ratio']
        assert abs(a - r) < 0.05, f"naive Sharpe: agent={a:.4f} ref={r:.4f}"

    def test_turnover(self, ref, agent_perf):
        r = ref['results']['naive']['avg_turnover']
        a = agent_perf['naive']['avg_turnover']
        assert abs(a - r) < 0.02, \
            f"naive turnover: agent={a:.4f} ref={r:.4f}"

    def test_mean_return(self, ref, agent_perf):
        r = ref['results']['naive']['mean_return_ann_pct']
        a = agent_perf['naive']['mean_return_ann_pct']
        assert abs(a - r) < 0.5, \
            f"naive mean ret: agent={a:.2f} ref={r:.2f}"


# ---------------------------------------------------------------------------
# Tests — MVP strategy
# ---------------------------------------------------------------------------

class TestMVP:
    def test_sharpe(self, ref, agent_perf):
        r = ref['results']['mvp']['sharpe_ratio']
        a = agent_perf['mvp']['sharpe_ratio']
        assert abs(a - r) < 0.05, f"mvp Sharpe: agent={a:.4f} ref={r:.4f}"

    def test_weights_250(self, ref, agent_w250):
        industries = ref['industries']
        rw = ref['results']['mvp']['weights_record'][250]
        for i, ind in enumerate(industries):
            aw = agent_w250['mvp'][ind]
            assert abs(aw - rw[i]) < 0.02, \
                f"mvp weight {ind}: agent={aw:.4f} ref={rw[i]:.4f}"


# ---------------------------------------------------------------------------
# Tests — MV-TC-Iso strategy
# ---------------------------------------------------------------------------

class TestMVTCIso:
    def test_sharpe(self, ref, agent_perf):
        r = ref['results']['mv_tc_iso']['sharpe_ratio']
        a = agent_perf['mv_tc_iso']['sharpe_ratio']
        assert abs(a - r) < 0.05, \
            f"mv_tc_iso Sharpe: agent={a:.4f} ref={r:.4f}"

    def test_weights_250(self, ref, agent_w250):
        industries = ref['industries']
        rw = ref['results']['mv_tc_iso']['weights_record'][250]
        for i, ind in enumerate(industries):
            aw = agent_w250['mv_tc_iso'][ind]
            assert abs(aw - rw[i]) < 0.02, \
                f"mv_tc_iso weight {ind}: agent={aw:.4f} ref={rw[i]:.4f}"

    def test_turnover(self, ref, agent_perf):
        r = ref['results']['mv_tc_iso']['avg_turnover']
        a = agent_perf['mv_tc_iso']['avg_turnover']
        assert abs(a - r) < 0.02, \
            f"mv_tc_iso turnover: agent={a:.4f} ref={r:.4f}"


# ---------------------------------------------------------------------------
# Tests — MV-TC-Illiq strategy (core challenge)
# ---------------------------------------------------------------------------

class TestMVTCIlliq:
    def test_sharpe(self, ref, agent_perf):
        r = ref['results']['mv_tc_illiq']['sharpe_ratio']
        a = agent_perf['mv_tc_illiq']['sharpe_ratio']
        assert abs(a - r) < 0.05, \
            f"mv_tc_illiq Sharpe: agent={a:.4f} ref={r:.4f}"

    def test_weights_250(self, ref, agent_w250):
        industries = ref['industries']
        rw = ref['results']['mv_tc_illiq']['weights_record'][250]
        for i, ind in enumerate(industries):
            aw = agent_w250['mv_tc_illiq'][ind]
            assert abs(aw - rw[i]) < 0.02, \
                f"mv_tc_illiq weight {ind}: agent={aw:.4f} ref={rw[i]:.4f}"

    def test_turnover(self, ref, agent_perf):
        r = ref['results']['mv_tc_illiq']['avg_turnover']
        a = agent_perf['mv_tc_illiq']['avg_turnover']
        assert abs(a - r) < 0.02, \
            f"mv_tc_illiq turnover: agent={a:.4f} ref={r:.4f}"

    def test_differs_from_iso(self, agent_perf):
        si = agent_perf['mv_tc_iso']['sharpe_ratio']
        il = agent_perf['mv_tc_illiq']['sharpe_ratio']
        assert abs(si - il) > 1e-4, \
            "mv_tc_illiq and mv_tc_iso must have different Sharpe ratios"


# ---------------------------------------------------------------------------
# Tests — optimal beta search
# ---------------------------------------------------------------------------

class TestOptimalBeta:
    def test_in_grid(self, agent_opt, data):
        _, _, _, config = data
        gs = config['grid_search']
        grid = list(range(
            int(gs['beta_start']), int(gs['beta_end']) + 1,
            int(gs['beta_step'])))
        assert agent_opt['optimal_beta'] in grid

    def test_optimal_value(self, ref, agent_opt, data):
        returns, illiquidity, _, config = data
        bd = int(config['backtest']['beta_default'])
        ab = agent_opt['optimal_beta']
        res = ref_run_backtest(
            returns, illiquidity, config, 'mv_tc_illiq', ab, bd)
        assert abs(res['sharpe_ratio'] - ref['optimal_sharpe']) < 0.05, \
            (f"Agent beta={ab} gives Sharpe {res['sharpe_ratio']:.4f}; "
             f"best is beta={ref['optimal_beta']} "
             f"Sharpe={ref['optimal_sharpe']:.4f}")

    def test_sharpe_at_optimal_consistent(self, ref, agent_opt, data):
        returns, illiquidity, _, config = data
        bd = int(config['backtest']['beta_default'])
        ab = agent_opt['optimal_beta']
        res = ref_run_backtest(
            returns, illiquidity, config, 'mv_tc_illiq', ab, bd)
        assert abs(agent_opt['sharpe_at_optimal'] - res['sharpe_ratio']) \
            < 0.05, \
            (f"Reported sharpe_at_optimal={agent_opt['sharpe_at_optimal']:.4f}"
             f" but ref gives {res['sharpe_ratio']:.4f} for beta={ab}")


# ---------------------------------------------------------------------------
# Tests — strategy ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_descending_sharpe(self, agent_perf, agent_ranking):
        sharpes = [agent_perf[s]['sharpe_ratio'] for s in agent_ranking]
        for i in range(len(sharpes) - 1):
            assert sharpes[i] >= sharpes[i + 1] - 1e-6, \
                f"Ranking not descending: {list(zip(agent_ranking, sharpes))}"

    def test_matches_performance(self, agent_perf, agent_ranking):
        expected = sorted(agent_perf.keys(),
                          key=lambda x: agent_perf[x]['sharpe_ratio'],
                          reverse=True)
        assert agent_ranking == expected, \
            f"Ranking {agent_ranking} != expected {expected}"


# ---------------------------------------------------------------------------
# Tests — mathematical properties
# ---------------------------------------------------------------------------

class TestMathProperties:
    def test_positive_volatility(self, agent_perf):
        for s in agent_perf:
            assert agent_perf[s]['volatility_ann_pct'] > 0, \
                f"{s} has non-positive volatility"

    def test_naive_has_positive_turnover(self, agent_perf):
        assert agent_perf['naive']['avg_turnover'] > 0

    def test_all_sharpe_finite(self, agent_perf):
        for s in agent_perf:
            v = agent_perf[s]['sharpe_ratio']
            assert np.isfinite(v), f"{s} Sharpe is not finite: {v}"
