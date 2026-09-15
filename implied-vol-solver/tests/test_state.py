"""Tests for C-based Black-Scholes implied volatility solver with Python ctypes bindings."""

import json
import csv
import os
import sys
import math
import time
import subprocess
import ctypes
import pytest
import numpy as np
from scipy.special import erfc as scipy_erfc

sys.path.insert(0, '/app')


def _normcdf(z):
    """Scalar normal CDF using scipy erfc."""
    return scipy_erfc(-z / math.sqrt(2.0)) / 2.0


def _normcdf_vec(z):
    """Vectorized normal CDF using scipy erfc."""
    return scipy_erfc(-z / np.sqrt(2.0)) / 2.0


def _bs_price_ref(is_call, strike, forward, total_var, df):
    """Reference BS price using scipy for test verification."""
    sign = 1 if is_call else -1
    if total_var < 1e-16:
        return df * max(sign * (forward - strike), 0.0)
    sv = math.sqrt(total_var)
    d1 = math.log(forward / strike) / sv + sv / 2.0
    d2 = d1 - sv
    return sign * df * (forward * _normcdf(sign * d1) - strike * _normcdf(sign * d2))


def _load_test_config():
    with open('/app/data/test_config.json', 'r') as f:
        return json.load(f)


def _load_market_quotes():
    rows = []
    with open('/app/data/market_quotes.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


class TestBuildAndLoad:
    """Verify the shared library builds and loads correctly."""

    def test_makefile_exists(self):
        assert os.path.isfile('/app/Makefile'), "Makefile not found at /app/Makefile"

    def test_library_exists(self):
        assert os.path.isfile('/app/libivol.so'), "libivol.so not found at /app/libivol.so"

    def test_source_files_exist(self):
        assert os.path.isfile('/app/src/ivol.c'), "C source not found at /app/src/ivol.c"
        assert os.path.isfile('/app/src/ivol.h'), "C header not found at /app/src/ivol.h"

    def test_python_wrapper_exists(self):
        assert os.path.isfile('/app/iv_solver.py'), "Python wrapper not found at /app/iv_solver.py"

    def test_ctypes_load_and_symbols(self):
        lib = ctypes.CDLL('/app/libivol.so')
        assert hasattr(lib, 'bs_price'), "bs_price symbol not found in libivol.so"
        assert hasattr(lib, 'implied_vol'), "implied_vol symbol not found in libivol.so"

    def test_ctypes_bs_price_direct(self):
        lib = ctypes.CDLL('/app/libivol.so')
        lib.bs_price.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                  ctypes.c_double, ctypes.c_double]
        lib.bs_price.restype = ctypes.c_double
        price = lib.bs_price(1, 100.0, 100.0, 0.04, 1.0)
        ref = _bs_price_ref(True, 100.0, 100.0, 0.04, 1.0)
        assert abs(price - ref) < 1e-10, f"bs_price mismatch: {price} vs {ref}"

    def test_ctypes_implied_vol_direct(self):
        lib = ctypes.CDLL('/app/libivol.so')
        lib.bs_price.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                  ctypes.c_double, ctypes.c_double]
        lib.bs_price.restype = ctypes.c_double
        lib.implied_vol.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                     ctypes.c_double, ctypes.c_double, ctypes.c_double]
        lib.implied_vol.restype = ctypes.c_double
        vol = 0.25
        price = lib.bs_price(1, 100.0, 100.0, vol ** 2, 1.0)
        iv = lib.implied_vol(1, price, 100.0, 100.0, 1.0, 1.0)
        assert abs(iv - vol) < 1e-10, f"implied_vol mismatch: {iv} vs {vol}"


class TestPythonWrapper:
    """Verify the Python ctypes wrapper works correctly."""

    def test_import(self):
        from iv_solver import black_scholes_price, implied_volatility
        assert callable(black_scholes_price)
        assert callable(implied_volatility)

    def test_wrapper_bs_price(self):
        from iv_solver import black_scholes_price
        price = black_scholes_price(True, 100.0, 100.0, 0.04, 1.0)
        ref = _bs_price_ref(True, 100.0, 100.0, 0.04, 1.0)
        assert abs(price - ref) < 1e-10

    def test_wrapper_round_trip(self):
        from iv_solver import black_scholes_price, implied_volatility
        vol = 0.30
        price = black_scholes_price(True, 110.0, 100.0, vol ** 2 * 0.5, 1.0)
        iv = implied_volatility(True, price, 100.0, 110.0, 0.5, 1.0)
        assert abs(iv - vol) < 1e-10


class TestCuiGrid:
    """Cui test grid: accuracy from test_config.json parameters."""

    def test_grid_accuracy(self):
        cfg = _load_test_config()
        grid = cfg['cui_grid']
        S0 = grid['S0']
        r = grid['r']
        q = grid['q']
        n = grid['num_points']
        K_vals = np.linspace(grid['K_range'][0], grid['K_range'][1], n)
        tau_vals = np.linspace(grid['tau_range'][0], grid['tau_range'][1], n)
        sigma_vals = np.linspace(grid['sigma_range'][0], grid['sigma_range'][1], n)

        from iv_solver import implied_volatility

        K, tau, sigma = np.meshgrid(K_vals, tau_vals, sigma_vals, indexing='ij')
        K = K.ravel()
        tau = tau.ravel()
        sigma = sigma.ravel()

        forward = S0 * np.exp((r - q) * tau)
        discount_df = np.exp(-r * tau)
        total_var = sigma ** 2 * tau
        sqrt_var = np.sqrt(total_var)

        d1 = np.log(forward / K) / sqrt_var + sqrt_var / 2.0
        d2 = d1 - sqrt_var
        prices = discount_df * (forward * _normcdf_vec(d1) - K * _normcdf_vec(d2))

        mask = prices > grid['price_floor']
        K_f = K[mask]
        tau_f = tau[mask]
        sigma_f = sigma[mask]
        forward_f = forward[mask]
        discount_df_f = discount_df[mask]
        prices_f = prices[mask]

        n_valid = len(K_f)
        assert n_valid > 30000, f"Too few valid cases: {n_valid}"

        errors = np.empty(n_valid)
        for i in range(n_valid):
            iv = implied_volatility(
                True,
                float(prices_f[i]),
                float(forward_f[i]),
                float(K_f[i]),
                float(tau_f[i]),
                float(discount_df_f[i]),
            )
            errors[i] = abs(iv - sigma_f[i])

        mean_err = np.mean(errors)
        max_err = np.max(errors)

        assert mean_err < grid['mean_iv_error'], \
            f"Mean IV error {mean_err:.2e} exceeds {grid['mean_iv_error']}"
        assert max_err < grid['max_iv_error'], \
            f"Max IV error {max_err:.2e} exceeds {grid['max_iv_error']}"


class TestWideVolRange:
    """Wide volatility range from test_config.json."""

    def test_wide_vol(self):
        cfg = _load_test_config()
        wv = cfg['wide_vol']
        forward = wv['forward']
        strike = wv['strike']
        tte = wv['tte']
        discount_df = wv['discount_df']

        from iv_solver import implied_volatility

        vols = np.arange(wv['vol_range'][0],
                         wv['vol_range'][1] + wv['vol_step'] / 2,
                         wv['vol_step'])
        errors = []
        for vol in vols:
            tv = float(vol) ** 2 * tte
            sv = math.sqrt(tv)
            d1 = math.log(forward / strike) / sv + sv / 2.0
            d2 = d1 - sv
            price = discount_df * (forward * _normcdf(d1) - strike * _normcdf(d2))
            if price > 1e-20:
                iv = implied_volatility(True, price, forward, strike, tte, discount_df)
                errors.append(abs(iv - float(vol)))

        assert len(errors) > 100, f"Too few valid cases: {len(errors)}"
        max_err = max(errors)
        assert max_err < wv['max_iv_error'], \
            f"Max IV error {max_err:.2e} exceeds {wv['max_iv_error']}"


class TestEdgeCases:
    """Edge cases from test_config.json."""

    def test_all_edge_cases(self):
        cfg = _load_test_config()
        from iv_solver import black_scholes_price, implied_volatility

        for i, case in enumerate(cfg['edge_cases']):
            is_call = case['type'] == 'call'
            iv = implied_volatility(
                is_call,
                case['price'],
                case['forward'],
                case['strike'],
                case['tte'],
                case['discount_df'],
            )
            assert iv > 0, f"Edge case {i}: IV must be positive, got {iv}"
            reprice = black_scholes_price(
                is_call,
                case['strike'],
                case['forward'],
                iv ** 2 * case['tte'],
                case['discount_df'],
            )
            err = abs(reprice - case['price'])
            tol = case['round_trip_tol']
            assert err < tol, \
                f"Edge case {i}: round-trip error {err:.2e} exceeds {tol}"


class TestMarketQuotes:
    """Market quotes from market_quotes.csv."""

    def test_all_market_quotes(self):
        rows = _load_market_quotes()
        from iv_solver import implied_volatility

        for row in rows:
            qid = row['id']
            is_call = row['type'] == 'call'
            forward = float(row['forward'])
            strike = float(row['strike'])
            vol = float(row['vol'])
            tte = float(row['tte'])
            df = float(row['discount_df'])
            max_error = float(row['max_error'])

            total_var = vol * vol * tte
            price = _bs_price_ref(is_call, strike, forward, total_var, df)

            if price <= 1e-20:
                continue

            iv = implied_volatility(is_call, price, forward, strike, tte, df)
            err = abs(iv - vol)
            assert err < max_error, \
                f"Market quote {qid}: vol error {err:.2e} exceeds {max_error}"


class TestPutCallParity:
    """Put-call parity from test_config.json."""

    def test_parity_cases(self):
        cfg = _load_test_config()
        from iv_solver import black_scholes_price, implied_volatility

        for i, case in enumerate(cfg['parity_cases']):
            forward = case['forward']
            strike = case['strike']
            vol = case['vol']
            tte = case['tte']
            df = case['discount_df']
            tol = case['parity_tol']
            tv = vol * vol * tte

            call_price = black_scholes_price(True, strike, forward, tv, df)
            put_price = black_scholes_price(False, strike, forward, tv, df)

            iv_call = implied_volatility(True, call_price, forward, strike, tte, df)
            iv_put = implied_volatility(False, put_price, forward, strike, tte, df)

            assert abs(iv_call - vol) < tol, \
                f"Parity {i}: call IV err {abs(iv_call - vol):.2e}"
            assert abs(iv_put - vol) < tol, \
                f"Parity {i}: put IV err {abs(iv_put - vol):.2e}"
            assert abs(iv_call - iv_put) < tol, \
                f"Parity {i}: call-put diff {abs(iv_call - iv_put):.2e}"


class TestPerformance:
    """Performance: Cui grid must complete within time limit."""

    def test_grid_timing(self):
        cfg = _load_test_config()
        grid = cfg['cui_grid']
        perf = cfg['performance']
        S0 = grid['S0']
        r = grid['r']
        q = grid['q']
        n = grid['num_points']
        K_vals = np.linspace(grid['K_range'][0], grid['K_range'][1], n)
        tau_vals = np.linspace(grid['tau_range'][0], grid['tau_range'][1], n)
        sigma_vals = np.linspace(grid['sigma_range'][0], grid['sigma_range'][1], n)

        from iv_solver import implied_volatility

        K, tau, sigma = np.meshgrid(K_vals, tau_vals, sigma_vals, indexing='ij')
        K = K.ravel()
        tau = tau.ravel()
        sigma = sigma.ravel()

        forward = S0 * np.exp((r - q) * tau)
        discount_df = np.exp(-r * tau)
        total_var = sigma ** 2 * tau
        sqrt_var = np.sqrt(total_var)
        d1 = np.log(forward / K) / sqrt_var + sqrt_var / 2.0
        d2 = d1 - sqrt_var
        prices = discount_df * (forward * _normcdf_vec(d1) - K * _normcdf_vec(d2))
        mask = prices > grid['price_floor']

        prices_f = prices[mask]
        forward_f = forward[mask]
        K_f = K[mask]
        tau_f = tau[mask]
        discount_df_f = discount_df[mask]

        start = time.time()
        for i in range(len(prices_f)):
            implied_volatility(
                True,
                float(prices_f[i]),
                float(forward_f[i]),
                float(K_f[i]),
                float(tau_f[i]),
                float(discount_df_f[i]),
            )
        elapsed = time.time() - start

        max_time = perf['cui_grid_max_seconds']
        assert elapsed < max_time, \
            f"Grid took {elapsed:.1f}s, limit is {max_time}s"


class TestCLI:
    """Command-line interface tests."""

    def test_cli_call(self):
        from iv_solver import black_scholes_price
        vol = 0.20
        price = black_scholes_price(True, 100.0, 100.0, vol ** 2, 1.0)
        result = subprocess.run(
            ["python3", "/app/iv_solver.py",
             "--forward", "100.0", "--strike", "100.0",
             "--tte", "1.0", "--df", "1.0",
             "--price", f"{price:.15e}", "--type", "call"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        iv = float(result.stdout.strip())
        assert abs(iv - vol) < 1e-10, f"CLI IV {iv} != {vol}"

    def test_cli_put(self):
        from iv_solver import black_scholes_price
        vol = 0.35
        price = black_scholes_price(False, 120.0, 100.0, vol ** 2 * 2.0, 1.0)
        result = subprocess.run(
            ["python3", "/app/iv_solver.py",
             "--forward", "100.0", "--strike", "120.0",
             "--tte", "2.0", "--df", "1.0",
             "--price", f"{price:.15e}", "--type", "put"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        iv = float(result.stdout.strip())
        assert abs(iv - vol) < 1e-10, f"CLI put IV {iv} != {vol}"
