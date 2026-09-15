#!/usr/bin/env python3

"""
Cross-Pool AMM Arbitrage Analyzer.
Reads pool data from SQLite, finds the most profitable arbitrage cycle,
and optimizes trade size.
"""

import json
import math
import sqlite3


# ---------------------------------------------------------------------------
# Load pool data from SQLite
# ---------------------------------------------------------------------------

def load_pools(db_path="/app/market.db"):
    """Load all pool data from the SQLite database."""
    conn = sqlite3.connect(db_path)
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
    return pools, tokens


# ---------------------------------------------------------------------------
# AMM swap implementations
# ---------------------------------------------------------------------------

def cp_swap(reserve_in, reserve_out, amount_in, fee_bps):
    """Constant-product x*y=k swap."""
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    return reserve_out * eff / (reserve_in + eff)


def ss_get_D(x0, x1, A):
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


def ss_get_y(x_new, D, A):
    """Solve for the other reserve after one side changed."""
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


def ss_swap(ra, rb, amt, A, fee_bps, a_to_b=True):
    """StableSwap exchange."""
    fee = fee_bps / 10000.0
    eff = amt * (1.0 - fee)
    D = ss_get_D(ra, rb, A)
    if a_to_b:
        new_a = ra + eff
        new_b = ss_get_y(new_a, D, A)
        return rb - new_b
    else:
        new_b = rb + eff
        new_a = ss_get_y(new_b, D, A)
        return ra - new_a


def wp_swap(reserve_in, reserve_out, weight_in, weight_out, amount_in, fee_bps):
    """Balancer-style weighted-product swap."""
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    ratio = reserve_in / (reserve_in + eff)
    exp = weight_in / weight_out
    return reserve_out * (1.0 - ratio ** exp)


def execute_swap(pool, token_in, amount_in):
    """Route a swap through the correct AMM formula."""
    ptype = pool["type"]
    a_to_b = (token_in == pool["token_a"])

    if ptype == "ConstantProduct":
        if a_to_b:
            return cp_swap(pool["reserve_a"], pool["reserve_b"],
                           amount_in, pool["fee_bps"])
        else:
            return cp_swap(pool["reserve_b"], pool["reserve_a"],
                           amount_in, pool["fee_bps"])

    elif ptype == "StableSwap":
        return ss_swap(pool["reserve_a"], pool["reserve_b"],
                       amount_in, pool["amp_factor"], pool["fee_bps"],
                       a_to_b)

    elif ptype == "WeightedProduct":
        if a_to_b:
            return wp_swap(pool["reserve_a"], pool["reserve_b"],
                           pool["weight_a"], pool["weight_b"],
                           amount_in, pool["fee_bps"])
        else:
            return wp_swap(pool["reserve_b"], pool["reserve_a"],
                           pool["weight_b"], pool["weight_a"],
                           amount_in, pool["fee_bps"])

    raise ValueError(f"Unknown pool type: {ptype}")


# ---------------------------------------------------------------------------
# Cycle evaluation
# ---------------------------------------------------------------------------

def evaluate_cycle(pool_map, path, pool_ids, input_amt):
    """Run input_amt through the cycle; return profit (output - input)."""
    amt = input_amt
    for i in range(len(pool_ids)):
        pool = pool_map[pool_ids[i]]
        token_in = path[i]
        amt = execute_swap(pool, token_in, amt)
        if amt <= 0:
            return -input_amt
    return amt - input_amt


# ---------------------------------------------------------------------------
# Graph + cycle enumeration
# ---------------------------------------------------------------------------

def build_graph(pools):
    """Adjacency list: token -> [(neighbour, pool_dict), ...]."""
    graph = {}
    for pool in pools:
        a, b = pool["token_a"], pool["token_b"]
        graph.setdefault(a, []).append((b, pool))
        graph.setdefault(b, []).append((a, pool))
    return graph


def find_all_cycles(graph, tokens, max_length):
    """Enumerate distinct simple cycles up to max_length via DFS."""
    raw = []
    for start in tokens:
        _dfs(graph, start, start, [start], [], raw, max_length)
    return _deduplicate(raw)


def _dfs(graph, start, current, path, pools_used, results, max_len):
    for neighbour, pool in graph.get(current, []):
        if neighbour == start and len(path) >= 3:
            results.append((list(path) + [start], list(pools_used) + [pool["id"]]))
        elif neighbour not in path and len(path) < max_len:
            path.append(neighbour)
            pools_used.append(pool["id"])
            _dfs(graph, start, neighbour, path, pools_used, results, max_len)
            path.pop()
            pools_used.pop()


def _deduplicate(cycles):
    seen = set()
    unique = []
    for path, pools in cycles:
        inner = path[:-1]
        n = len(inner)
        min_tok = min(inner)
        idx = inner.index(min_tok)
        canon_path = tuple(inner[idx:] + inner[:idx])
        canon_pools = tuple(pools[idx:] + pools[:idx])
        key = (canon_path, canon_pools)
        if key not in seen:
            seen.add(key)
            unique.append((path, pools))
    return unique


# ---------------------------------------------------------------------------
# Optimisation (golden-section search)
# ---------------------------------------------------------------------------

def optimise_input(pool_map, path, pool_ids, max_input=1_000_000.0):
    """Find the input that maximises absolute profit."""
    a, b = 1.0, max_input
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    resphi = 2.0 - phi

    x1 = a + resphi * (b - a)
    x2 = b - resphi * (b - a)
    f1 = -evaluate_cycle(pool_map, path, pool_ids, x1)
    f2 = -evaluate_cycle(pool_map, path, pool_ids, x2)

    for _ in range(200):
        if f1 < f2:
            b = x2
            x2 = x1
            f2 = f1
            x1 = a + resphi * (b - a)
            f1 = -evaluate_cycle(pool_map, path, pool_ids, x1)
        else:
            a = x1
            x1 = x2
            f1 = f2
            x2 = b - resphi * (b - a)
            f2 = -evaluate_cycle(pool_map, path, pool_ids, x2)
        if abs(b - a) < 0.01:
            break

    opt = (a + b) / 2.0
    profit = evaluate_cycle(pool_map, path, pool_ids, opt)
    output = opt + profit
    return opt, output, profit


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pools, tokens = load_pools()
    pool_map = {p["id"]: p for p in pools}

    graph = build_graph(pools)
    cycles = find_all_cycles(graph, tokens, max_length=len(tokens))

    print(f"Found {len(cycles)} distinct cycles across {len(tokens)} tokens and {len(pools)} pools")

    best_profit = -float("inf")
    best_result = None

    for path, pool_ids in cycles:
        # Quick screening at small trade size
        test_profit = evaluate_cycle(pool_map, path, pool_ids, 100.0)
        if test_profit <= 0:
            continue

        opt_input, opt_output, profit = optimise_input(pool_map, path, pool_ids)
        if profit > best_profit:
            best_profit = profit
            best_result = {
                "best_cycle_path": path,
                "best_cycle_pools": pool_ids,
                "optimal_input_amount": round(opt_input, 2),
                "expected_output_amount": round(opt_output, 2),
                "expected_profit": round(profit, 2),
            }

    if best_result is None:
        best_result = {
            "best_cycle_path": [],
            "best_cycle_pools": [],
            "optimal_input_amount": 0.0,
            "expected_output_amount": 0.0,
            "expected_profit": 0.0,
        }

    with open("/app/results.json", "w") as f:
        json.dump(best_result, f, indent=2)

    print(f"Best cycle: {best_result['best_cycle_path']}")
    print(f"Pools: {best_result['best_cycle_pools']}")
    print(f"Optimal input: {best_result['optimal_input_amount']:.2f}")
    print(f"Expected profit: {best_result['expected_profit']:.2f}")


if __name__ == "__main__":
    main()
