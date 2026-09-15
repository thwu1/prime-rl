"""
Reference implementation of cost-based join order optimizer using
dynamic programming over subsets.

"""

import json
import math
from itertools import combinations


def load_stats(path="/opt/task_data/stats.json"):
    with open(path) as f:
        return json.load(f)


def load_queries(path="/opt/task_data/queries.json"):
    with open(path) as f:
        return json.load(f)["queries"]


def estimate_selectivity(histogram, row_count, op, value):
    """Estimate selectivity of a filter predicate using histogram."""
    total_contribution = 0.0
    for bucket in histogram:
        lo = bucket["lower"]
        hi = bucket["upper"]
        c = bucket["count"]
        width = hi - lo
        if width <= 0:
            continue
        if op in (">=", ">"):
            if value <= lo:
                total_contribution += c
            elif value >= hi:
                total_contribution += 0
            else:
                total_contribution += c * (hi - value) / width
        elif op in ("<=", "<"):
            if value >= hi:
                total_contribution += c
            elif value <= lo:
                total_contribution += 0
            else:
                total_contribution += c * (value - lo) / width
        elif op == "=":
            ndv = bucket["ndv"]
            if lo <= value < hi and ndv > 0:
                total_contribution += c / ndv
    if row_count == 0:
        return 0.0
    return total_contribution / row_count


def apply_filters(stats, query):
    """Apply filter predicates to get effective table cardinalities and NDVs."""
    table_info = {}
    for tname in query["tables"]:
        tstat = stats["tables"][tname]
        row_count = tstat["row_count"]
        combined_sel = 1.0
        for f in query["filters"]:
            if f["table"] == tname:
                col_stat = tstat["columns"][f["column"]]
                if f["op"] == "=":
                    sel = 1.0 / col_stat["ndv"] if col_stat["ndv"] > 0 else 1.0
                else:
                    sel = estimate_selectivity(
                        col_stat["histogram"], row_count, f["op"], f["value"]
                    )
                combined_sel *= sel
        filtered_rows = row_count * combined_sel
        col_ndvs = {}
        for cname, cstat in tstat["columns"].items():
            col_ndvs[cname] = min(cstat["ndv"], math.ceil(filtered_rows)) if filtered_rows > 0 else 0
        table_info[tname] = {
            "rows": filtered_rows,
            "col_ndvs": col_ndvs,
        }
    return table_info


def tables_connected(s1_tables, s2_tables, joins):
    """Check if there is at least one join predicate connecting s1 and s2."""
    for j in joins:
        lt, rt = j["left_table"], j["right_table"]
        if (lt in s1_tables and rt in s2_tables) or (lt in s2_tables and rt in s1_tables):
            return True
    return False


def get_connecting_predicates(s1_tables, s2_tables, joins):
    """Get all join predicates connecting tables in s1 to tables in s2."""
    result = []
    for j in joins:
        lt, rt = j["left_table"], j["right_table"]
        if (lt in s1_tables and rt in s2_tables) or (lt in s2_tables and rt in s1_tables):
            result.append(j)
    return result


def estimate_join_card(left_rows, left_ndv, right_rows, right_ndv):
    """Estimate join cardinality: |L| * |R| / max(V(L.a), V(R.b))."""
    max_ndv = max(left_ndv, right_ndv)
    if max_ndv == 0:
        return 0.0
    return left_rows * right_rows / max_ndv


def subset_to_frozenset(tables, mask):
    """Convert bitmask to frozenset of table names."""
    result = set()
    for i, t in enumerate(tables):
        if mask & (1 << i):
            result.add(t)
    return frozenset(result)


def optimize(stats, query):
    """Find optimal join order using DP over subsets."""
    table_info = apply_filters(stats, query)
    tables = list(query["tables"])
    n = len(tables)
    joins = query["joins"]

    # DP table: key = frozenset of tables -> (cost, card, col_ndvs, plan)
    dp = {}

    # Base cases: single tables
    for i, t in enumerate(tables):
        tset = frozenset([t])
        info = table_info[t]
        plan = {"table": t, "estimated_rows": info["rows"], "total_cost": 0.0}
        dp[tset] = (0.0, info["rows"], dict(info["col_ndvs"]), plan)

    # Enumerate subsets of increasing size
    for size in range(2, n + 1):
        for combo in combinations(range(n), size):
            subset = frozenset(tables[i] for i in combo)
            mask = sum(1 << i for i in combo)
            best = None

            # Try all non-trivial partitions into two non-empty subsets
            # Enumerate all non-empty proper subsets of 'combo' indices
            subset_list = list(combo)
            m = len(subset_list)

            for s1_mask in range(1, (1 << m) - 1):
                s1_indices = [subset_list[j] for j in range(m) if s1_mask & (1 << j)]
                s2_indices = [subset_list[j] for j in range(m) if not (s1_mask & (1 << j))]

                s1 = frozenset(tables[i] for i in s1_indices)
                s2 = frozenset(tables[i] for i in s2_indices)

                # Avoid double-counting (only consider one of s1/s2 vs s2/s1)
                if s1 > s2:
                    continue

                if s1 not in dp or s2 not in dp:
                    continue

                if not tables_connected(s1, s2, joins):
                    continue

                cost1, card1, ndvs1, plan1 = dp[s1]
                cost2, card2, ndvs2, plan2 = dp[s2]

                # Find connecting predicates and estimate join cardinality
                connecting = get_connecting_predicates(s1, s2, joins)

                # For multiple connecting predicates, apply them sequentially
                result_card = card1 * card2
                for pred in connecting:
                    lt, lc = pred["left_table"], pred["left_col"]
                    rt, rc = pred["right_table"], pred["right_col"]
                    if lt in s1:
                        l_ndv = ndvs1.get(lc, 1)
                        r_ndv = ndvs2.get(rc, 1)
                    else:
                        l_ndv = ndvs2.get(lc, 1)
                        r_ndv = ndvs1.get(rc, 1)
                    max_ndv = max(l_ndv, r_ndv)
                    if max_ndv > 0:
                        result_card = result_card / max_ndv

                # Hash join cost
                node_cost = card1 + card2
                total_cost = cost1 + cost2 + node_cost

                # Compute resulting NDVs
                result_ndvs = {}
                for col, ndv in ndvs1.items():
                    result_ndvs[col] = min(ndv, math.ceil(result_card)) if result_card > 0 else 0
                for col, ndv in ndvs2.items():
                    result_ndvs[col] = min(ndv, math.ceil(result_card)) if result_card > 0 else 0

                # For join columns, use min of both sides
                for pred in connecting:
                    lc, rc = pred["left_col"], pred["right_col"]
                    l_ndv = ndvs1.get(lc, ndvs2.get(lc, 1))
                    r_ndv = ndvs2.get(rc, ndvs1.get(rc, 1))
                    join_ndv = min(l_ndv, r_ndv, math.ceil(result_card)) if result_card > 0 else 0
                    result_ndvs[lc] = join_ndv
                    result_ndvs[rc] = join_ndv

                plan = {
                    "left": plan1,
                    "right": plan2,
                    "estimated_rows": result_card,
                    "node_cost": node_cost,
                    "total_cost": total_cost,
                }

                if best is None or total_cost < best[0]:
                    best = (total_cost, result_card, result_ndvs, plan)

            if best is not None:
                dp[subset] = best

    full_set = frozenset(tables)
    if full_set in dp:
        return dp[full_set][3]
    else:
        raise ValueError(f"Could not find valid join plan for tables {tables}")


def main():
    stats = load_stats()
    queries = load_queries()
    results = {}
    for q in queries:
        plan = optimize(stats, q)
        results[q["id"]] = {
            "total_cost": plan["total_cost"],
            "estimated_rows": plan["estimated_rows"],
        }
        print(f"Query {q['id']}: cost={plan['total_cost']:.2f}, rows={plan['estimated_rows']:.2f}")
    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
