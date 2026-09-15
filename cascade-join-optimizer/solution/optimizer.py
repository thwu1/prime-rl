#!/usr/bin/env python3
"""
Multi-operator cost-based query optimizer with SQLite catalog and graphviz output.

Implements subset DP with multi-operator selection (hash join vs sort-merge join,
sequential scan vs index scan) considering physical property propagation.

"""

import json
import math
import os
import sqlite3
import subprocess
from itertools import combinations


class Catalog:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._load()

    def _load(self):
        c = self.conn.cursor()
        self.config = {}
        for row in c.execute('SELECT key, value FROM config'):
            self.config[row['key']] = row['value']

        self.tables = {}
        for row in c.execute('SELECT * FROM tables'):
            self.tables[row['table_name']] = {
                'row_count': row['row_count'],
                'page_count': row['page_count'],
                'clustered_on': row['clustered_on'],
            }

        self.columns = {}
        for row in c.execute('SELECT * FROM columns'):
            self.columns[(row['table_name'], row['column_name'])] = {
                'distinct_values': row['distinct_values'],
            }

        self.indexes = {}
        for row in c.execute('SELECT * FROM indexes'):
            self.indexes[(row['table_name'], row['column_name'])] = {
                'index_name': row['index_name'],
                'index_pages': row['index_pages'],
            }

        self.join_sel = {}
        for row in c.execute('SELECT * FROM join_selectivity'):
            self.join_sel[(row['left_col'], row['right_col'])] = row['distinct_values']

    def get_join_distinct(self, left_col, right_col):
        if (left_col, right_col) in self.join_sel:
            return self.join_sel[(left_col, right_col)]
        if (right_col, left_col) in self.join_sel:
            return self.join_sel[(right_col, left_col)]
        raise ValueError(f"No join selectivity for {left_col} = {right_col}")


class PlanNode:
    _counter = 0

    def __init__(self, op, est_card, est_cost, tables, table=None,
                 children=None, join_cond=None, filter_cond=None,
                 sorted_on=None):
        PlanNode._counter += 1
        self.node_id = PlanNode._counter
        self.op = op
        self.est_card = est_card
        self.est_cost = est_cost
        self.tables = set(tables) if not isinstance(tables, set) else tables
        self.table = table
        self.children = children or []
        self.join_cond = join_cond
        self.filter_cond = filter_cond
        self.sorted_on = sorted_on

    def total_cost(self):
        cost = self.est_cost
        for c in self.children:
            cost += c.total_cost()
        return cost

    def to_dict(self):
        d = {
            'op': self.op,
            'est_card': self.est_card,
            'est_cost': self.est_cost,
            'tables': sorted(self.tables),
        }
        if self.table:
            d['table'] = self.table
        if self.join_cond:
            d['join_cond'] = self.join_cond
        if self.filter_cond:
            d['filter_cond'] = self.filter_cond
        if self.children:
            d['children'] = [c.to_dict() for c in self.children]
        return d

    def to_dot_lines(self, lines):
        label_parts = [self.op]
        if self.table:
            label_parts.append(self.table)
        if self.join_cond:
            label_parts.append(self.join_cond)
        if self.filter_cond:
            label_parts.append(self.filter_cond)
        label_parts.append(f"cost={self.est_cost:.1f}")
        label_parts.append(f"card={self.est_card}")
        label = "\\n".join(label_parts)
        lines.append(f'  n{self.node_id} [label="{label}"];')
        for child in self.children:
            lines.append(f'  n{self.node_id} -> n{child.node_id};')
            child.to_dot_lines(lines)


def optimize(query, catalog):
    cfg = catalog.config
    spc = cfg['seq_page_cost']
    rpc = cfg['random_page_cost']
    ctc = cfg['cpu_tuple_cost']
    cic = cfg['cpu_index_cost']
    coc = cfg['cpu_operator_cost']
    hbf = cfg['hash_build_factor']
    hpf = cfg['hash_probe_factor']
    scf = cfg['sort_cpu_factor']
    mcf = cfg['merge_cpu_factor']
    ist = cfg['index_selectivity_threshold']

    def _seq_scan_cost(pages, rows):
        return spc * pages + ctc * rows

    def _index_scan_cost(sel, tpages, ipages, trows):
        er = round(trows * sel)
        io = rpc * (math.ceil(ipages * sel) + math.ceil(tpages * sel))
        cpu = cic * er
        return io + cpu, er

    def _filter_cost(rows):
        return coc * rows

    def _filter_card(card, distinct):
        return round(card / distinct)

    def _hash_join_cost(build, probe):
        return ctc * (hbf * build + hpf * probe)

    def _sort_cost(rows):
        if rows <= 1:
            return 0.0
        return scf * ctc * rows * math.log2(rows)

    def _merge_join_cost(lr, rr, ls, rs):
        cost = ctc * mcf * (lr + rr)
        if not ls:
            cost += _sort_cost(lr)
        if not rs:
            cost += _sort_cost(rr)
        return cost

    def _join_card(lc, rc, distinct):
        return round(lc * rc / distinct)

    # Group filters by table
    filters_by_table = {}
    for f in query.get('filters', []):
        t, col = f['column'].split('.')
        filters_by_table.setdefault(t, []).append(
            (col, f['op'], f['value'], f['column']))

    # Build base scan candidates per table
    base_candidates = {}

    for tbl in query['tables']:
        tmeta = catalog.tables[tbl]
        rows = tmeta['row_count']
        pages = tmeta['page_count']
        clustered = tmeta['clustered_on']
        candidates = []

        # Sequential scan (+ filter if applicable)
        scan_cost_val = _seq_scan_cost(pages, rows)
        plan = PlanNode('SeqScan', est_card=rows, est_cost=scan_cost_val,
                        tables={tbl}, table=tbl, sorted_on=clustered)

        if tbl in filters_by_table:
            for col, op, val, full_col in filters_by_table[tbl]:
                distinct = catalog.columns[(tbl, col)]['distinct_values']
                fc = _filter_cost(plan.est_card)
                new_card = _filter_card(plan.est_card, distinct)
                plan = PlanNode('Filter', est_card=new_card, est_cost=fc,
                                tables={tbl}, filter_cond=f"{full_col}{op}{val}",
                                children=[plan], sorted_on=clustered)
        candidates.append(plan)

        # Index scan (if filter exists, index exists, selectivity below threshold)
        if tbl in filters_by_table:
            for col, op, val, full_col in filters_by_table[tbl]:
                idx_key = (tbl, col)
                if idx_key in catalog.indexes:
                    distinct = catalog.columns[(tbl, col)]['distinct_values']
                    sel = 1.0 / distinct
                    if sel < ist:
                        idx_info = catalog.indexes[idx_key]
                        ic, est_rows = _index_scan_cost(
                            sel, pages, idx_info['index_pages'], rows)
                        idx_plan = PlanNode(
                            'IndexScan', est_card=est_rows, est_cost=ic,
                            tables={tbl}, table=tbl,
                            filter_cond=f"{full_col}{op}{val}",
                            sorted_on=col)
                        candidates.append(idx_plan)

        base_candidates[tbl] = candidates

    # Build join predicate index
    join_preds = {}
    for j in query['joins']:
        lt = j['left'].split('.')[0]
        rt = j['right'].split('.')[0]
        key = frozenset([lt, rt])
        distinct = catalog.get_join_distinct(j['left'], j['right'])
        join_preds[key] = {
            'condition': f"{j['left']}={j['right']}",
            'distinct': distinct,
            'left_col': j['left'],
            'right_col': j['right'],
        }

    # Subset DP
    table_list = list(query['tables'])
    n = len(table_list)

    # dp[frozenset] -> best PlanNode
    dp = {}

    # Initialize with cheapest base plan per table
    for tbl in table_list:
        best = min(base_candidates[tbl], key=lambda p: p.total_cost())
        dp[frozenset([tbl])] = best

    for size in range(2, n + 1):
        for subset in combinations(table_list, size):
            subset_set = frozenset(subset)
            best_plan = None
            best_total = float('inf')

            for split_size in range(1, (size + 1) // 2 + 1):
                for left_tables in combinations(list(subset), split_size):
                    left_set = frozenset(left_tables)
                    right_set = subset_set - left_set

                    if split_size * 2 == size and left_set > right_set:
                        continue

                    # Collect crossing join predicates
                    crossing = []
                    for pair, info in join_preds.items():
                        if pair & left_set and pair & right_set:
                            crossing.append(info)
                    if not crossing:
                        continue

                    combined_distinct = 1
                    for ci in crossing:
                        combined_distinct *= ci['distinct']
                    combined_cond = ' AND '.join(
                        ci['condition'] for ci in crossing)

                    # Get candidate plans for each side
                    if len(left_set) == 1:
                        left_plans = base_candidates[next(iter(left_set))]
                    elif left_set in dp:
                        left_plans = [dp[left_set]]
                    else:
                        continue

                    if len(right_set) == 1:
                        right_plans = base_candidates[next(iter(right_set))]
                    elif right_set in dp:
                        right_plans = [dp[right_set]]
                    else:
                        continue

                    for lp in left_plans:
                        for rp in right_plans:
                            lc = lp.est_card
                            rc = rp.est_card
                            new_card = _join_card(lc, rc, combined_distinct)

                            # Hash join
                            bc = min(lc, rc)
                            pc = max(lc, rc)
                            hj_cost = _hash_join_cost(bc, pc)
                            if lc >= rc:
                                hj_children = [lp, rp]
                            else:
                                hj_children = [rp, lp]

                            hj_plan = PlanNode(
                                'HashJoin', est_card=new_card,
                                est_cost=hj_cost, tables=subset_set,
                                join_cond=combined_cond,
                                children=hj_children, sorted_on=None)
                            hj_total = hj_plan.total_cost()
                            if hj_total < best_total:
                                best_total = hj_total
                                best_plan = hj_plan

                            # Sort-merge join (single predicate only)
                            if len(crossing) == 1:
                                ci = crossing[0]
                                lc_tbl = ci['left_col'].split('.')[0]
                                lc_col = ci['left_col'].split('.')[1]
                                rc_col = ci['right_col'].split('.')[1]

                                if lc_tbl in left_set:
                                    left_join_col = lc_col
                                    right_join_col = rc_col
                                else:
                                    left_join_col = rc_col
                                    right_join_col = lc_col

                                ls = (lp.sorted_on == left_join_col)
                                rs = (rp.sorted_on == right_join_col)

                                mj_cost = _merge_join_cost(
                                    lc, rc, ls, rs)
                                mj_plan = PlanNode(
                                    'SortMergeJoin', est_card=new_card,
                                    est_cost=mj_cost, tables=subset_set,
                                    join_cond=combined_cond,
                                    children=[lp, rp], sorted_on=None)
                                mj_total = mj_plan.total_cost()
                                if mj_total < best_total:
                                    best_total = mj_total
                                    best_plan = mj_plan

            if best_plan is not None:
                dp[subset_set] = best_plan

    full_set = frozenset(table_list)
    if full_set not in dp:
        raise RuntimeError("No valid plan found for all tables")
    return dp[full_set]


def plan_to_dot(plan, query_id):
    lines = [f'digraph {query_id} {{', '  rankdir=TB;',
             '  node [shape=box, fontname="Helvetica"];']
    plan.to_dot_lines(lines)
    lines.append('}')
    return '\n'.join(lines)


def main():
    catalog = Catalog('/data/catalog.db')
    with open('/data/queries.json') as f:
        queries = json.load(f)

    os.makedirs('/app/output', exist_ok=True)

    for query in queries:
        PlanNode._counter = 0
        plan = optimize(query, catalog)
        plan_dict = plan.to_dict()
        total_cost = plan.total_cost()

        output = {
            'query_id': query['id'],
            'total_cost': total_cost,
            'plan': plan_dict,
        }

        json_path = f"/app/output/{query['id']}_plan.json"
        with open(json_path, 'w') as f:
            json.dump(output, f, indent=2)

        dot_content = plan_to_dot(plan, query['id'])
        dot_path = f"/app/output/{query['id']}_plan.dot"
        with open(dot_path, 'w') as f:
            f.write(dot_content)

        png_path = f"/app/output/{query['id']}_plan.png"
        subprocess.run(['dot', '-Tpng', dot_path, '-o', png_path], check=True)

        print(f"Query {query['id']}: total_cost={total_cost:.3f}, "
              f"root_card={plan.est_card}")


if __name__ == '__main__':
    main()
