#!/usr/bin/env python3
"""Swap quote calculator for AMM pools. Reads pool state from SQLite."""
import argparse
import json
import sqlite3
import sys


def get_pool_data(db_path, pool_id):
    """Load full pool configuration from database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        """
        SELECT p.id, p.pool_type, p.token_a, p.token_b, p.fee_bps,
               r.reserve_a, r.reserve_b
        FROM pools p
        JOIN pool_reserves r ON p.id = r.pool_id
        WHERE p.id = ?
        """,
        (pool_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    pool = dict(row)

    c.execute(
        "SELECT param_name, param_value FROM pool_params WHERE pool_id = ?",
        (pool_id,),
    )
    for param in c.fetchall():
        pool[param["param_name"]] = param["param_value"]

    conn.close()
    return pool


def cp_swap(reserve_in, reserve_out, amount_in, fee_bps):
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    return reserve_out * eff / (reserve_in + eff)


def ss_get_D(x0, x1, A):
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
    fee = fee_bps / 10000.0
    eff = amount_in * (1.0 - fee)
    ratio = reserve_in / (reserve_in + eff)
    exp = weight_in / weight_out
    return reserve_out * (1.0 - ratio ** exp)


def compute_swap(pool, token_in, amount_in):
    ptype = pool["pool_type"]
    a_to_b = token_in == pool["token_a"]

    if ptype == "ConstantProduct":
        if a_to_b:
            return cp_swap(
                pool["reserve_a"], pool["reserve_b"], amount_in, pool["fee_bps"]
            )
        else:
            return cp_swap(
                pool["reserve_b"], pool["reserve_a"], amount_in, pool["fee_bps"]
            )

    elif ptype == "StableSwap":
        return ss_swap(
            pool["reserve_a"],
            pool["reserve_b"],
            amount_in,
            pool["amp_factor"],
            pool["fee_bps"],
            a_to_b,
        )

    elif ptype == "WeightedProduct":
        if a_to_b:
            return wp_swap(
                pool["reserve_a"],
                pool["reserve_b"],
                pool["weight_a"],
                pool["weight_b"],
                amount_in,
                pool["fee_bps"],
            )
        else:
            return wp_swap(
                pool["reserve_b"],
                pool["reserve_a"],
                pool["weight_b"],
                pool["weight_a"],
                amount_in,
                pool["fee_bps"],
            )

    raise ValueError(f"Unknown pool type: {ptype}")


def list_pools(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT p.id, p.pool_type, p.token_a, p.token_b, p.fee_bps,
               r.reserve_a, r.reserve_b
        FROM pools p
        JOIN pool_reserves r ON p.id = r.pool_id
        ORDER BY p.id
        """
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main():
    parser = argparse.ArgumentParser(
        description="Compute swap output for an AMM pool"
    )
    parser.add_argument(
        "--db", default="/app/market.db", help="Path to market database"
    )
    parser.add_argument("--pool-id", help="Pool identifier")
    parser.add_argument("--token-in", help="Input token symbol")
    parser.add_argument("--amount", type=float, help="Input amount")
    parser.add_argument(
        "--list-pools",
        action="store_true",
        help="List all available pools",
    )
    args = parser.parse_args()

    if args.list_pools:
        pools = list_pools(args.db)
        for p in pools:
            print(
                f"{p['id']:20s} {p['pool_type']:18s} "
                f"{p['token_a']:6s} / {p['token_b']:6s}  "
                f"fee={p['fee_bps']}bps  "
                f"reserves=({p['reserve_a']:.2f}, {p['reserve_b']:.2f})"
            )
        return

    if not args.pool_id or not args.token_in or args.amount is None:
        parser.error("--pool-id, --token-in, and --amount are required")

    pool = get_pool_data(args.db, args.pool_id)
    if pool is None:
        print(json.dumps({"error": f"Pool '{args.pool_id}' not found"}))
        sys.exit(1)

    if args.token_in not in (pool["token_a"], pool["token_b"]):
        print(
            json.dumps(
                {
                    "error": f"Token '{args.token_in}' not in pool '{args.pool_id}' "
                    f"(has {pool['token_a']}, {pool['token_b']})"
                }
            )
        )
        sys.exit(1)

    token_out = (
        pool["token_b"] if args.token_in == pool["token_a"] else pool["token_a"]
    )
    amount_out = compute_swap(pool, args.token_in, args.amount)

    result = {
        "pool_id": args.pool_id,
        "pool_type": pool["pool_type"],
        "token_in": args.token_in,
        "token_out": token_out,
        "amount_in": args.amount,
        "amount_out": amount_out,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
