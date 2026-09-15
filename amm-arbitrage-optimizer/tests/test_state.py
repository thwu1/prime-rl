
"""
Tests for Cross-Pool AMM Arbitrage Analysis.
Loads pool data from SQLite and includes reference AMM implementations.
"""

import json
import math
import os
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# Reference AMM implementations
# ---------------------------------------------------------------------------

def ref_cp_swap(reserve_in, reserve_out, amount_in, fee_bps):
    """Constant-product swap: x * y = k."""
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    return reserve_out * eff / (reserve_in + eff)


def ref_ss_get_D(x0, x1, A):
    """Compute StableSwap invariant D via Newton iteration."""
    N = 2
    S = x0 + x1
    if S == 0.0:
        return 0.0
    D = S
    Ann = A * N
    for _ in range(256):
        D_P = D
        D_P = D_P * D / (x0 * N)
        D_P = D_P * D / (x1 * N)
        D_prev = D
        D = (Ann * S + D_P * N) * D / ((Ann - 1) * D + (N + 1) * D_P)
        if abs(D - D_prev) < 1e-10:
            return D
    return D


def ref_ss_get_y(x_new, D, A):
    """Given one reserve after swap, solve for the other."""
    N = 2
    Ann = A * N
    c = D * D / (x_new * N)
    c = c * D / (Ann * N)
    b = x_new + D / Ann
    y = D
    for _ in range(256):
        y_prev = y
        y = (y * y + c) / (2.0 * y + b - D)
        if abs(y - y_prev) < 1e-10:
            return y
    return y


def ref_ss_swap(ra, rb, amt, A, fee_bps, a_to_b=True):
    """StableSwap exchange."""
    fee = fee_bps / 10000.0
    eff = amt * (1.0 - fee)
    D = ref_ss_get_D(ra, rb, A)
    if a_to_b:
        new_a = ra + eff
        new_b = ref_ss_get_y(new_a, D, A)
        return rb - new_b
    else:
        new_b = rb + eff
        new_a = ref_ss_get_y(new_b, D, A)
        return ra - new_a


def ref_wp_swap(reserve_in, reserve_out, weight_in, weight_out, amount_in, fee_bps):
    """Balancer-style weighted-product swap."""
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    ratio = reserve_in / (reserve_in + eff)
    exp = weight_in / weight_out
    return reserve_out * (1.0 - ratio ** exp)


def ref_execute_swap(pool, token_in, amount_in):
    """Route a swap through the correct AMM formula."""
    ptype = pool["type"]
    a_to_b = (token_in == pool["token_a"])

    if ptype == "ConstantProduct":
        if a_to_b:
            return ref_cp_swap(pool["reserve_a"], pool["reserve_b"],
                               amount_in, pool["fee_bps"])
        else:
            return ref_cp_swap(pool["reserve_b"], pool["reserve_a"],
                               amount_in, pool["fee_bps"])

    elif ptype == "StableSwap":
        return ref_ss_swap(pool["reserve_a"], pool["reserve_b"],
                           amount_in, pool["amp_factor"], pool["fee_bps"],
                           a_to_b)

    elif ptype == "WeightedProduct":
        if a_to_b:
            return ref_wp_swap(pool["reserve_a"], pool["reserve_b"],
                               pool["weight_a"], pool["weight_b"],
                               amount_in, pool["fee_bps"])
        else:
            return ref_wp_swap(pool["reserve_b"], pool["reserve_a"],
                               pool["weight_b"], pool["weight_a"],
                               amount_in, pool["fee_bps"])

    raise ValueError(f"Unknown pool type: {ptype}")


def ref_evaluate_cycle(pools, path, pool_ids, input_amt):
    """Run *input_amt* through the cycle and return profit (output - input)."""
    pool_map = {p["id"]: p for p in pools}
    amt = input_amt
    for i in range(len(pool_ids)):
        pool = pool_map[pool_ids[i]]
        token_in = path[i]
        amt = ref_execute_swap(pool, token_in, amt)
        if amt <= 0:
            return -input_amt
    return amt - input_amt


def ref_optimize_cycle(pools, path, pool_ids, max_input=1_000_000.0):
    """Golden-section search for the input that maximises absolute profit."""
    a_bound, b_bound = 1.0, max_input
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    resphi = 2.0 - phi

    x1 = a_bound + resphi * (b_bound - a_bound)
    x2 = b_bound - resphi * (b_bound - a_bound)
    f1 = -ref_evaluate_cycle(pools, path, pool_ids, x1)
    f2 = -ref_evaluate_cycle(pools, path, pool_ids, x2)

    for _ in range(200):
        if f1 < f2:
            b_bound = x2
            x2 = x1
            f2 = f1
            x1 = a_bound + resphi * (b_bound - a_bound)
            f1 = -ref_evaluate_cycle(pools, path, pool_ids, x1)
        else:
            a_bound = x1
            x1 = x2
            f1 = f2
            x2 = b_bound - resphi * (b_bound - a_bound)
            f2 = -ref_evaluate_cycle(pools, path, pool_ids, x2)
        if abs(b_bound - a_bound) < 0.01:
            break

    opt = (a_bound + b_bound) / 2.0
    profit = ref_evaluate_cycle(pools, path, pool_ids, opt)
    return opt, profit


# ---------------------------------------------------------------------------
# Fixtures — load pool data from SQLite
# ---------------------------------------------------------------------------

def load_pools_from_db():
    """Read all pool data from the SQLite database."""
    conn = sqlite3.connect("/app/market.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT p.id, p.pool_type as type, p.token_a, p.token_b, p.fee_bps,
               r.reserve_a, r.reserve_b
        FROM pools p
        JOIN pool_reserves r ON p.id = r.pool_id
    """)

    pools = []
    for row in c.fetchall():
        pool = dict(row)
        c2 = conn.cursor()
        c2.execute(
            "SELECT param_name, param_value FROM pool_params WHERE pool_id = ?",
            (pool["id"],),
        )
        for param in c2.fetchall():
            pool[param["param_name"]] = param["param_value"]
        pools.append(pool)

    c.execute("SELECT symbol FROM tokens")
    tokens = [row["symbol"] for row in c.fetchall()]

    conn.close()
    return {"pools": pools, "tokens": tokens}


@pytest.fixture
def pools_data():
    return load_pools_from_db()


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Database accessibility
# ---------------------------------------------------------------------------

class TestDatabaseAccessible:

    def test_database_exists(self):
        assert os.path.exists("/app/market.db"), "market.db must exist at /app/market.db"

    def test_pool_count(self):
        conn = sqlite3.connect("/app/market.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM pools")
        count = c.fetchone()[0]
        conn.close()
        assert count == 12, f"Expected 12 pools, got {count}"

    def test_token_count(self):
        conn = sqlite3.connect("/app/market.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tokens")
        count = c.fetchone()[0]
        conn.close()
        assert count == 6, f"Expected 6 tokens, got {count}"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestResultsStructure:

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json must exist at /app/results.json"

    def test_has_required_fields(self, results):
        required = [
            "best_cycle_path",
            "best_cycle_pools",
            "optimal_input_amount",
            "expected_output_amount",
            "expected_profit",
        ]
        for field in required:
            assert field in results, f"Missing required field: {field}"

    def test_path_forms_cycle(self, results):
        path = results["best_cycle_path"]
        assert len(path) >= 4, "Cycle path must visit at least 3 distinct tokens"
        assert path[0] == path[-1], "Cycle path must start and end at the same token"

    def test_pools_count_matches_path(self, results):
        path = results["best_cycle_path"]
        pools = results["best_cycle_pools"]
        assert len(pools) == len(path) - 1, (
            f"Number of pools ({len(pools)}) must equal len(path)-1 ({len(path)-1})"
        )

    def test_profit_self_consistent(self, results):
        expected = results["expected_output_amount"] - results["optimal_input_amount"]
        assert abs(results["expected_profit"] - expected) < max(1.0, abs(expected) * 0.01), (
            f"Profit {results['expected_profit']} inconsistent with "
            f"output-input = {expected}"
        )

    def test_positive_profit(self, results):
        assert results["expected_profit"] > 0, "Best cycle should be profitable"

    def test_positive_input(self, results):
        assert results["optimal_input_amount"] > 0, "Optimal input must be positive"


# ---------------------------------------------------------------------------
# Pool-path consistency
# ---------------------------------------------------------------------------

class TestPoolPathConsistency:

    def test_pools_exist(self, results, pools_data):
        pool_ids = {p["id"] for p in pools_data["pools"]}
        for pid in results["best_cycle_pools"]:
            assert pid in pool_ids, f"Pool '{pid}' not found in database"

    def test_tokens_match_pools(self, results, pools_data):
        pool_map = {p["id"]: p for p in pools_data["pools"]}
        path = results["best_cycle_path"]
        pool_ids = results["best_cycle_pools"]
        for i, pid in enumerate(pool_ids):
            pool = pool_map[pid]
            tok_in = path[i]
            tok_out = path[i + 1]
            pool_tokens = {pool["token_a"], pool["token_b"]}
            assert tok_in in pool_tokens, (
                f"Hop {i}: token_in '{tok_in}' not in pool '{pid}' "
                f"(tokens: {pool_tokens})"
            )
            assert tok_out in pool_tokens, (
                f"Hop {i}: token_out '{tok_out}' not in pool '{pid}' "
                f"(tokens: {pool_tokens})"
            )
            assert tok_in != tok_out, (
                f"Hop {i}: token_in and token_out are the same ('{tok_in}')"
            )


# ---------------------------------------------------------------------------
# Best-cycle identification
# ---------------------------------------------------------------------------

class TestBestCycleIdentification:

    def test_correct_pool_set(self, results):
        """The optimal cycle uses the 4-hop path through specific pools."""
        pools = set(results["best_cycle_pools"])
        expected = {"ss-usdc-dai", "cp-dai-weth", "cp-weth-wbtc", "cp-wbtc-usdc"}
        assert pools == expected, (
            f"Expected pool set {expected}, got {pools}"
        )

    def test_visits_all_four_tokens(self, results):
        inner = results["best_cycle_path"][:-1]
        assert set(inner) == {"USDC", "DAI", "WETH", "WBTC"}, (
            f"Best cycle should visit USDC, DAI, WETH, WBTC; got {set(inner)}"
        )

    def test_correct_direction(self, results):
        """In the profitable direction DAI immediately precedes WETH."""
        inner = results["best_cycle_path"][:-1]
        n = len(inner)
        dai_idx = inner.index("DAI")
        weth_idx = inner.index("WETH")
        assert (dai_idx + 1) % n == weth_idx, (
            "Wrong cycle direction: DAI should immediately precede WETH"
        )


# ---------------------------------------------------------------------------
# Optimal-value accuracy
# ---------------------------------------------------------------------------

class TestOptimalValues:

    def test_optimal_input_near_reference(self, results, pools_data):
        """Agent's optimal input within 5% of the reference optimiser."""
        path = results["best_cycle_path"]
        pool_ids = results["best_cycle_pools"]
        ref_opt, _ = ref_optimize_cycle(pools_data["pools"], path, pool_ids)

        agent_opt = results["optimal_input_amount"]
        rel_err = abs(agent_opt - ref_opt) / ref_opt
        assert rel_err < 0.05, (
            f"Optimal input {agent_opt:.2f} deviates {rel_err*100:.1f}% "
            f"from reference {ref_opt:.2f}"
        )

    def test_profit_near_reference(self, results, pools_data):
        """Agent's reported profit within 10% of the reference maximum."""
        path = results["best_cycle_path"]
        pool_ids = results["best_cycle_pools"]
        _, ref_profit = ref_optimize_cycle(pools_data["pools"], path, pool_ids)

        agent_profit = results["expected_profit"]
        rel_err = abs(agent_profit - ref_profit) / ref_profit
        assert rel_err < 0.10, (
            f"Profit {agent_profit:.2f} deviates {rel_err*100:.1f}% "
            f"from reference {ref_profit:.2f}"
        )

    def test_profit_is_achievable(self, results, pools_data):
        """Re-run the cycle at the reported input; profit should match."""
        path = results["best_cycle_path"]
        pool_ids = results["best_cycle_pools"]
        input_amt = results["optimal_input_amount"]

        actual_profit = ref_evaluate_cycle(
            pools_data["pools"], path, pool_ids, input_amt
        )
        reported_profit = results["expected_profit"]
        rel_err = abs(actual_profit - reported_profit) / abs(reported_profit)
        assert rel_err < 0.02, (
            f"Reported profit {reported_profit:.2f} not achievable; "
            f"reference computes {actual_profit:.2f} at input {input_amt:.2f}"
        )

    def test_near_peak_profit(self, results, pools_data):
        """Agent's profit should be at least 90% of the true peak."""
        path = results["best_cycle_path"]
        pool_ids = results["best_cycle_pools"]
        _, ref_peak = ref_optimize_cycle(pools_data["pools"], path, pool_ids)

        agent_profit = results["expected_profit"]
        assert agent_profit >= ref_peak * 0.90, (
            f"Profit {agent_profit:.2f} is below 90% of peak {ref_peak:.2f}"
        )


# ---------------------------------------------------------------------------
# Swap-math sanity checks
# ---------------------------------------------------------------------------

class TestSwapMathSanity:

    def test_cp_swap_basic(self, pools_data):
        """2000 USDC should buy approximately 1 WETH (minus fee + slippage)."""
        pool = next(p for p in pools_data["pools"] if p["id"] == "cp-usdc-weth")
        out = ref_execute_swap(pool, "USDC", 2000.0)
        assert 0.98 < out < 1.0, f"Expected ~1 WETH, got {out:.6f}"

    def test_stableswap_near_parity(self, pools_data):
        """StableSwap with high A should give near 1:1 for small trades."""
        pool = next(p for p in pools_data["pools"] if p["id"] == "ss-usdc-dai")
        out = ref_execute_swap(pool, "USDC", 1000.0)
        assert 999.0 < out < 1010.0, f"Expected ~1000 DAI, got {out:.4f}"

    def test_weighted_swap_positive(self, pools_data):
        """Weighted pool swap should produce positive output."""
        pool = next(p for p in pools_data["pools"] if p["id"] == "wp-weth-wbtc")
        out = ref_execute_swap(pool, "WETH", 10.0)
        assert out > 0, f"Weighted swap should yield positive output, got {out}"

    def test_best_cycle_small_trade_profitable(self, pools_data):
        """The 4-hop cycle should be profitable at small trade sizes."""
        path = ["USDC", "DAI", "WETH", "WBTC", "USDC"]
        pool_ids = ["ss-usdc-dai", "cp-dai-weth", "cp-weth-wbtc", "cp-wbtc-usdc"]
        profit = ref_evaluate_cycle(pools_data["pools"], path, pool_ids, 100.0)
        assert profit > 0, f"Small trade should be profitable, got {profit:.4f}"

    def test_best_cycle_huge_trade_unprofitable(self, pools_data):
        """The 4-hop cycle should be unprofitable for very large trades."""
        path = ["USDC", "DAI", "WETH", "WBTC", "USDC"]
        pool_ids = ["ss-usdc-dai", "cp-dai-weth", "cp-weth-wbtc", "cp-wbtc-usdc"]
        profit = ref_evaluate_cycle(pools_data["pools"], path, pool_ids, 500_000.0)
        assert profit < 0, f"Huge trade should be unprofitable, got {profit:.2f}"

    def test_3hop_cycle_inferior(self, pools_data):
        """The 3-hop USDC->DAI->WETH->USDC cycle should yield less profit."""
        path_4 = ["USDC", "DAI", "WETH", "WBTC", "USDC"]
        pools_4 = ["ss-usdc-dai", "cp-dai-weth", "cp-weth-wbtc", "cp-wbtc-usdc"]
        _, profit_4 = ref_optimize_cycle(pools_data["pools"], path_4, pools_4)

        path_3 = ["USDC", "DAI", "WETH", "USDC"]
        pools_3 = ["ss-usdc-dai", "cp-dai-weth", "cp-usdc-weth"]
        _, profit_3 = ref_optimize_cycle(pools_data["pools"], path_3, pools_3)

        assert profit_4 > profit_3, (
            f"4-hop profit ({profit_4:.2f}) should exceed "
            f"3-hop profit ({profit_3:.2f})"
        )

    def test_consistent_pools_no_arb(self, pools_data):
        """Cycles through LINK/AAVE with consistent pricing should not be profitable."""
        path = ["USDC", "LINK", "WETH", "USDC"]
        pool_ids = ["cp-link-usdc", "cp-link-weth", "cp-usdc-weth"]
        profit = ref_evaluate_cycle(pools_data["pools"], path, pool_ids, 1000.0)
        assert profit <= 0, (
            f"LINK 3-hop should not be profitable, got {profit:.4f}"
        )
