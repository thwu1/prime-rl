#!/usr/bin/env python3
"""
Semantic layer query compiler.

Translates declarative metric queries (metrics + dimensions + filters) into
correct SQL against a normalized database, handling fan-out prevention,
join path resolution, derived metric computation, and multi-fact composition.
"""

import json
import os
from collections import defaultdict, deque
from decimal import Decimal

import duckdb
import yaml

MODEL_PATH = "/app/semantic_model.yaml"
REQUESTS_PATH = "/app/query_requests.json"
DB_PATH = "/app/insurance.duckdb"
RESULTS_DIR = "/app/results"


class JoinGraph:
    """Bidirectional entity-relationship graph with cardinality tracking."""

    def __init__(self, relationships):
        self.adj = defaultdict(list)
        for rel in relationships:
            self.adj[rel["from"]].append(
                {"target": rel["to"], "join": rel["join"], "type": rel["type"]}
            )
            rev = "one_to_many" if rel["type"] == "many_to_one" else "many_to_one"
            self.adj[rel["to"]].append(
                {"target": rel["from"], "join": rel["join"], "type": rev}
            )

    def find_path(self, start, end):
        if start == end:
            return []
        queue = deque([(start, [])])
        visited = {start}
        while queue:
            node, path = queue.popleft()
            for edge in self.adj[node]:
                tgt = edge["target"]
                if tgt in visited:
                    continue
                step = {
                    "from": node,
                    "to": tgt,
                    "join": edge["join"],
                    "type": edge["type"],
                }
                new_path = path + [step]
                if tgt == end:
                    return new_path
                visited.add(tgt)
                queue.append((tgt, new_path))
        raise ValueError(f"No join path from {start} to {end}")


def resolve_base_metrics(requested, all_metrics):
    """Recursively resolve derived metrics to their base metric components."""
    base = {}

    def _resolve(name):
        m = all_metrics[name]
        if m["type"] == "derived":
            for dep in m.get("requires", []):
                _resolve(dep)
        else:
            base[name] = m

    for name in requested:
        _resolve(name)
    return base


def expand_derived_formula(name, all_metrics):
    """Recursively expand a derived metric formula to reference only base names."""
    m = all_metrics[name]
    if m["type"] != "derived":
        return name
    formula = m["formula"]
    for dep in m.get("requires", []):
        if all_metrics[dep]["type"] == "derived":
            formula = formula.replace(dep, f"({expand_derived_formula(dep, all_metrics)})")
    return formula


class SemanticCompiler:
    def __init__(self, model):
        self.model = model
        self.graph = JoinGraph(model["relationships"])
        self.entities = model["entities"]
        self.metrics_defs = model["metrics"]
        self.dim_defs = model["dimensions"]

    def _table(self, entity):
        return self.entities[entity]["table"]

    def _pk(self, entity):
        pk = self.entities[entity]["primary_key"]
        return pk if isinstance(pk, str) else pk[0]

    def _agg_expr(self, name, mdef):
        mtype = mdef["type"]
        col = mdef["column"]
        filt = mdef.get("filter")
        if mtype == "sum":
            if filt:
                return f"SUM(CASE WHEN {filt} THEN {col} ELSE 0 END) AS {name}"
            return f"SUM({col}) AS {name}"
        if mtype == "count_distinct":
            return f"COUNT(DISTINCT {col}) AS {name}"
        raise ValueError(f"Unknown metric type: {mtype}")

    # ── fan-out detection ────────────────────────────────────────────────

    @staticmethod
    def _find_fanout_idx(path):
        for i, step in enumerate(path):
            if step["type"] == "one_to_many":
                return i
        return None

    # ── join helpers ─────────────────────────────────────────────────────

    def _build_joins(self, path, joined):
        clauses = []
        for step in path:
            tbl = self._table(step["to"])
            if tbl not in joined:
                clauses.append(f"JOIN {tbl} ON {step['join']}")
                joined.add(tbl)
        return clauses

    # ── single-entity subquery (no fan-out) ──────────────────────────────

    def _simple_query(self, entity, metrics, dims, filters):
        tbl = self._table(entity)
        joined = {tbl}
        join_clauses = []

        # joins for dimensions
        for d in dims:
            de = self.dim_defs[d]["entity"]
            if de != entity:
                path = self.graph.find_path(entity, de)
                join_clauses += self._build_joins(path, joined)

        # joins for filters
        for f in filters:
            ft = f.split(".")[0]
            if ft not in joined:
                for ename, edef in self.entities.items():
                    if edef["table"] == ft:
                        path = self.graph.find_path(entity, ename)
                        join_clauses += self._build_joins(path, joined)
                        break

        sel = [f"{self.dim_defs[d]['column']} AS {d}" for d in dims]
        sel += [self._agg_expr(n, m) for n, m in metrics]

        sql = f"SELECT {', '.join(sel)} FROM {tbl}"
        for jc in join_clauses:
            sql += f" {jc}"
        if filters:
            sql += f" WHERE {' AND '.join(filters)}"
        if dims:
            sql += f" GROUP BY {', '.join(self.dim_defs[d]['column'] for d in dims)}"
        return sql

    # ── single-entity subquery WITH fan-out prevention ───────────────────

    def _fanout_query(self, entity, metrics, dims, filters, path, fanout_idx):
        boundary_step = path[fanout_idx]
        boundary_entity = boundary_step["from"]
        boundary_tbl = self._table(boundary_entity)
        boundary_pk = self._pk(boundary_entity)

        post_entity = boundary_step["to"]
        post_tbl = self._table(post_entity)

        # ── 1. Pre-aggregate metric to boundary-entity PK level ──────────
        metric_tbl = self._table(entity)
        pre_joined = {metric_tbl}
        pre_joins = []
        if entity != boundary_entity:
            pre_path = self.graph.find_path(entity, boundary_entity)
            pre_joins = self._build_joins(pre_path, pre_joined)

        pre_filters = [f for f in filters if f.split(".")[0] in pre_joined]

        pre_sel = [f"{boundary_tbl}.{boundary_pk}"]
        pre_sel += [self._agg_expr(n, m) for n, m in metrics]

        pre_sql = f"SELECT {', '.join(pre_sel)} FROM {metric_tbl}"
        for jc in pre_joins:
            pre_sql += f" {jc}"
        if pre_filters:
            pre_sql += f" WHERE {' AND '.join(pre_filters)}"
        pre_sql += f" GROUP BY {boundary_tbl}.{boundary_pk}"

        # ── 2. Build dimension bridge (DISTINCT boundary-PK + dim cols) ──
        join_cond_parts = [p.strip() for p in boundary_step["join"].split("=")]
        bridge_fk = (
            join_cond_parts[0]
            if join_cond_parts[0].startswith(post_tbl + ".")
            else join_cond_parts[1]
        )
        bridge_fk_col = bridge_fk.split(".")[1]

        bridge_joined = {post_tbl}
        bridge_joins = []
        tail = path[fanout_idx + 1 :]
        bridge_joins = self._build_joins(tail, bridge_joined)

        bridge_sel = [bridge_fk]
        for d in dims:
            bridge_sel.append(f"{self.dim_defs[d]['column']} AS {d}")

        bridge_where = [
            f
            for f in filters
            if f.split(".")[0] in bridge_joined and f not in pre_filters
        ]
        # exclude NULL dimension rows (e.g., claims without catastrophe)
        for d in dims:
            dc = self.dim_defs[d]["column"]
            if dc.split(".")[0] in bridge_joined:
                bridge_where.append(f"{dc} IS NOT NULL")

        bridge_sql = f"SELECT DISTINCT {', '.join(bridge_sel)} FROM {post_tbl}"
        for jc in bridge_joins:
            bridge_sql += f" {jc}"
        if bridge_where:
            bridge_sql += f" WHERE {' AND '.join(bridge_where)}"

        # ── 3. Final join: pre_agg ⋈ bridge, re-aggregate by dims ───────
        final_sel = [f"bridge.{d}" for d in dims]
        final_sel += [f"SUM(pre_agg.{n}) AS {n}" for n, _ in metrics]

        final_sql = (
            f"SELECT {', '.join(final_sel)} "
            f"FROM ({pre_sql}) AS pre_agg "
            f"JOIN ({bridge_sql}) AS bridge "
            f"ON pre_agg.{boundary_pk} = bridge.{bridge_fk_col} "
            f"GROUP BY {', '.join(f'bridge.{d}' for d in dims)}"
        )
        return final_sql

    # ── compile one entity-group (dispatches to simple or fanout) ────────

    def _compile_entity_group(self, entity, metrics, dims, filters):
        if not dims:
            return self._simple_query(entity, metrics, dims, filters)

        # check all dim paths for fan-out
        for d in dims:
            de = self.dim_defs[d]["entity"]
            if de != entity:
                path = self.graph.find_path(entity, de)
                idx = self._find_fanout_idx(path)
                if idx is not None:
                    return self._fanout_query(
                        entity, metrics, dims, filters, path, idx
                    )

        return self._simple_query(entity, metrics, dims, filters)

    # ── top-level query compilation ──────────────────────────────────────

    def compile_query(self, request):
        requested = request["metrics"]
        dims = request.get("dimensions", [])
        filters = request.get("filters", [])

        base = resolve_base_metrics(requested, self.metrics_defs)

        # group base metrics by source entity
        groups = defaultdict(list)
        for name, mdef in base.items():
            groups[mdef["entity"]].append((name, mdef))

        # compile each entity-group
        group_sqls = {}
        for ent, mlist in groups.items():
            group_sqls[ent] = (
                self._compile_entity_group(ent, mlist, dims, filters),
                [n for n, _ in mlist],
            )

        # ── compose groups ───────────────────────────────────────────────
        if len(group_sqls) == 1:
            base_sql = next(iter(group_sqls.values()))[0]
        else:
            cte_parts = []
            entities_ordered = list(group_sqls.keys())
            for ent in entities_ordered:
                sql, _ = group_sqls[ent]
                cte_parts.append(f"grp_{ent} AS ({sql})")

            first = f"grp_{entities_ordered[0]}"
            sel = [f"{first}.{d}" for d in dims]
            for ent in entities_ordered:
                _, mnames = group_sqls[ent]
                sel += [f"grp_{ent}.{m}" for m in mnames]

            base_sql = f"WITH {', '.join(cte_parts)} SELECT {', '.join(sel)} FROM {first}"
            for ent in entities_ordered[1:]:
                alias = f"grp_{ent}"
                if dims:
                    on = " AND ".join(f"{first}.{d} = {alias}.{d}" for d in dims)
                    base_sql += f" JOIN {alias} ON {on}"
                else:
                    base_sql += f" CROSS JOIN {alias}"

        # ── derived-metric wrapper ───────────────────────────────────────
        has_derived = any(
            self.metrics_defs[m]["type"] == "derived" for m in requested
        )
        if has_derived:
            outer = list(dims)
            for m in requested:
                md = self.metrics_defs[m]
                if md["type"] == "derived":
                    formula = expand_derived_formula(m, self.metrics_defs)
                    outer.append(f"({formula}) AS {m}")
                else:
                    outer.append(m)
            base_sql = f"SELECT {', '.join(outer)} FROM ({base_sql}) AS base"

        return base_sql


def main():
    with open(MODEL_PATH) as f:
        model = yaml.safe_load(f)
    with open(REQUESTS_PATH) as f:
        requests = json.load(f)

    compiler = SemanticCompiler(model)
    conn = duckdb.connect(DB_PATH, read_only=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for req in requests:
        qid = req["query_id"]
        sql = compiler.compile_query(req)
        result = conn.execute(sql)
        columns = [d[0] for d in result.description]
        rows = [
            [float(v) if isinstance(v, Decimal) else v for v in row]
            for row in result.fetchall()
        ]
        out = {"query_id": qid, "sql": sql, "columns": columns, "rows": rows}
        path = os.path.join(RESULTS_DIR, f"{qid}.json")
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
        print(f"{qid}: {len(rows)} rows -> {path}")

    conn.close()
    print(f"\nAll {len(requests)} queries compiled and executed.")


if __name__ == "__main__":
    main()
