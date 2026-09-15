#!/usr/bin/env python3
"""
Cost-based join order optimizer using subset dynamic programming.

Implements the optimize_query function for /app/main.py by:
1. Building base scan plans with filter pushdown
2. Enumerating valid join orderings via subset DP
3. Selecting minimum-cost hash join plans
4. Writing output to /app/output/

"""

import json
import os
from itertools import combinations


# ── Cost model (from /data/cost_formulas.py) ──────────────────────────────────

def scan_cost(row_count):
    return float(row_count)

def filter_cost(input_card):
    return input_card * 0.1

def hash_join_cost(build_card, probe_card):
    return 1.5 * build_card + 1.2 * probe_card

def join_cardinality(left_card, right_card, distinct):
    return round(left_card * right_card / distinct)

def filter_cardinality(input_card, distinct):
    return round(input_card / distinct)


# ── Plan node ────────────────────────────────────────────────────────────────

class PlanNode:
    __slots__ = ("op", "table", "children", "join_cond", "filter_cond",
                 "est_card", "est_cost", "tables")

    def __init__(self, op, table=None, children=None, join_cond=None,
                 filter_cond=None, est_card=0, est_cost=0.0, tables=None):
        self.op = op
        self.table = table
        self.children = children or []
        self.join_cond = join_cond
        self.filter_cond = filter_cond
        self.est_card = est_card
        self.est_cost = est_cost
        self.tables = tables or set()

    def total_cost(self):
        cost = self.est_cost
        for c in self.children:
            cost += c.total_cost()
        return cost

    def to_dict(self):
        d = {
            "op": self.op,
            "est_card": self.est_card,
            "est_cost": self.est_cost,
            "tables": sorted(self.tables),
        }
        if self.table is not None:
            d["table"] = self.table
        if self.join_cond is not None:
            d["join_cond"] = self.join_cond
        if self.filter_cond is not None:
            d["filter_cond"] = self.filter_cond
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


# ── Optimizer ────────────────────────────────────────────────────────────────

def optimize_query(query, catalog):
    tables_meta = catalog["tables"]
    join_conds = catalog["join_conditions"]

    # ── 1. Base plans with filter pushdown ────────────────────────────────
    base_plans = {}
    for tbl in query["tables"]:
        row_count = tables_meta[tbl]["row_count"]
        card = row_count
        plan = PlanNode(
            op="SeqScan", table=tbl,
            est_card=card, est_cost=scan_cost(card), tables={tbl}
        )

        # Attach any matching filters directly on the scan
        for f in query.get("filters", []):
            f_table, f_col = f["column"].split(".")
            if f_table == tbl:
                distinct = tables_meta[tbl]["columns"][f_col]["distinct"]
                new_card = filter_cardinality(card, distinct)
                f_cost = filter_cost(card)
                plan = PlanNode(
                    op="Filter",
                    filter_cond=f"{f['column']}{f['op']}{f['value']}",
                    children=[plan],
                    est_card=new_card, est_cost=f_cost, tables={tbl}
                )
                card = new_card

        base_plans[tbl] = plan

    # ── 2. Build join predicate index ─────────────────────────────────────
    join_preds = {}  # frozenset({tbl_a, tbl_b}) -> {condition, distinct}
    for j in query["joins"]:
        lt = j["left"].split(".")[0]
        rt = j["right"].split(".")[0]
        key = frozenset([lt, rt])
        cond_key = f"{j['left']}={j['right']}"
        rev_key = f"{j['right']}={j['left']}"
        info = join_conds.get(cond_key, join_conds.get(rev_key))
        if info is None:
            raise ValueError(f"No selectivity data for join {cond_key}")
        join_preds[key] = {"condition": cond_key, "distinct": info["distinct"]}

    # ── 3. Subset DP ─────────────────────────────────────────────────────
    table_list = list(query["tables"])
    n = len(table_list)

    # dp[frozenset] -> best PlanNode for that subset
    dp = {}
    for tbl in table_list:
        dp[frozenset([tbl])] = base_plans[tbl]

    for size in range(2, n + 1):
        for subset in combinations(table_list, size):
            subset_set = frozenset(subset)
            best_plan = None
            best_total = float("inf")

            # Try every binary split of this subset
            for split_size in range(1, (size + 1) // 2 + 1):
                for left_tables in combinations(list(subset), split_size):
                    left_set = frozenset(left_tables)
                    right_set = subset_set - left_set

                    # Skip if same-size halves and we'd double-count
                    if split_size * 2 == size and left_set > right_set:
                        continue

                    if left_set not in dp or right_set not in dp:
                        continue

                    # Collect all join predicates crossing the split
                    combined_distinct = None
                    combined_conds = []
                    for pair, info in join_preds.items():
                        if pair & left_set and pair & right_set:
                            if combined_distinct is None:
                                combined_distinct = info["distinct"]
                            else:
                                combined_distinct *= info["distinct"]
                            combined_conds.append(info["condition"])

                    if combined_distinct is None:
                        continue  # No join predicate connects these subsets

                    left_plan = dp[left_set]
                    right_plan = dp[right_set]
                    lc = left_plan.est_card
                    rc = right_plan.est_card

                    bc = min(lc, rc)
                    pc = max(lc, rc)

                    new_card = join_cardinality(lc, rc, combined_distinct)
                    jcost = hash_join_cost(bc, pc)

                    # children[0] = probe (larger), children[1] = build (smaller)
                    if lc >= rc:
                        children = [left_plan, right_plan]
                    else:
                        children = [right_plan, left_plan]

                    plan = PlanNode(
                        op="HashJoin",
                        join_cond=" AND ".join(combined_conds),
                        children=children,
                        est_card=new_card, est_cost=jcost,
                        tables=subset_set
                    )

                    tc = plan.total_cost()
                    if tc < best_total:
                        best_total = tc
                        best_plan = plan

            if best_plan is not None:
                dp[subset_set] = best_plan

    full_set = frozenset(table_list)
    if full_set not in dp:
        raise RuntimeError("Could not find a valid plan for all tables")

    return dp[full_set]


# ── Main ─────────────────────────────────────────────────────────────────────

def compute_total_cost(plan_dict):
    cost = plan_dict.get("est_cost", 0)
    for child in plan_dict.get("children", []):
        cost += compute_total_cost(child)
    return cost


def main():
    with open("/data/catalog.json") as f:
        catalog = json.load(f)
    with open("/data/queries.json") as f:
        queries = json.load(f)

    os.makedirs("/app/output", exist_ok=True)

    for query in queries:
        plan = optimize_query(query, catalog)
        plan_dict = plan.to_dict()
        total_cost = compute_total_cost(plan_dict)
        output = {
            "query_id": query["id"],
            "total_cost": total_cost,
            "plan": plan_dict,
        }
        output_path = f"/app/output/{query['id']}_plan.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Query {query['id']}: total_cost={total_cost:.1f}, "
              f"root_card={plan.est_card}")


if __name__ == "__main__":
    main()
