"""
Distributed SQL Aggregate Query Decomposer - Strategy Beta.

Decomposes SQL aggregate queries into shard (map) and merge (reduce) phases.
Strategy: algebraic decomposition — express each aggregate in terms of simpler
partial aggregates that can be computed independently on shards and then
combined. For example, AVG(x) is decomposed into SUM(x)/COUNT(x) on each
shard, with the merge phase computing the weighted combination.
"""

import sqlglot
from sqlglot import exp, parse_one


def decompose_query(sql: str, num_shards: int) -> dict:
    tree = parse_one(sql, dialect="duckdb")

    select_node = tree.find(exp.Select)
    select_expressions = list(select_node.expressions)
    group_by = tree.find(exp.Group)
    having = tree.find(exp.Having)
    order_by = tree.find(exp.Order)
    where = tree.find(exp.Where)
    from_clause = tree.find(exp.From)
    joins = list(tree.find_all(exp.Join))

    group_cols = []
    if group_by:
        group_cols = list(group_by.expressions)

    shard_select_parts = []
    merge_select_parts = []
    final_columns = []
    _counter = [0]
    agg_cache = {}

    def _unique_name(prefix):
        _counter[0] += 1
        return f"__{prefix}_{_counter[0]}"

    def _expr_sql(e):
        return e.sql(dialect="duckdb")

    def _get_agg_type(node):
        if isinstance(node, exp.Sum):
            return "SUM"
        if isinstance(node, exp.Count):
            return "COUNT"
        if isinstance(node, exp.Min):
            return "MIN"
        if isinstance(node, exp.Max):
            return "MAX"
        if isinstance(node, exp.Avg):
            return "AVG"
        if isinstance(node, (exp.Variance, exp.VariancePop)):
            return "VAR_POP"
        if isinstance(node, (exp.Stddev, exp.StddevPop)):
            return "STDDEV_POP"
        if isinstance(node, exp.Anonymous):
            name = node.name.upper()
            if name in ("VAR_POP", "VARIANCE"):
                return "VAR_POP"
            if name in ("STDDEV_POP", "STDDEV"):
                return "STDDEV_POP"
            if name in ("COVAR_POP",):
                return "COVAR_POP"
        return None

    def _get_inner_expr(node, agg_type):
        if agg_type == "COUNT" and node.find(exp.Star):
            return None
        if isinstance(node, exp.Anonymous):
            return node.expressions[0] if node.expressions else None
        return node.this

    def _process_aggregate(agg_node):
        agg_sql_key = _expr_sql(agg_node)
        if agg_sql_key in agg_cache:
            return agg_cache[agg_sql_key]

        agg_type = _get_agg_type(agg_node)
        if agg_type is None:
            agg_type = "SUM"

        inner = _get_inner_expr(agg_node, agg_type)
        inner_sql = _expr_sql(inner) if inner is not None else None

        shard_cols = []
        merge_expr = ""

        if agg_type in ("SUM", "MIN", "MAX"):
            alias = _unique_name(agg_type.lower())
            shard_cols = [(f"{agg_type}({inner_sql})", alias)]
            merge_fn = "SUM" if agg_type == "SUM" else agg_type
            merge_expr = f"{merge_fn}({alias})"

        elif agg_type == "COUNT":
            alias = _unique_name("count")
            if inner_sql is None:
                shard_cols = [("COUNT(*)", alias)]
            else:
                shard_cols = [(f"COUNT({inner_sql})", alias)]
            # Collect per-shard counts and count them in the merge phase
            merge_expr = f"COUNT({alias})"

        elif agg_type == "AVG":
            # Algebraic decomposition: AVG(expr) = SUM(expr) / COUNT(expr)
            # Extract the column reference for the partial aggregates
            sum_alias = _unique_name("avg_sum")
            cnt_alias = _unique_name("avg_cnt")
            first_col = inner.find(exp.Column)
            if first_col is not None:
                col_ref = _expr_sql(first_col)
            else:
                col_ref = inner_sql
            shard_cols = [
                (f"SUM({col_ref})", sum_alias),
                (f"COUNT({col_ref})", cnt_alias),
            ]
            merge_expr = f"(SUM({sum_alias}) / SUM({cnt_alias}))"

        elif agg_type in ("VAR_POP", "STDDEV_POP"):
            # Each shard computes the local variance/stddev, then we
            # combine them by averaging across shards
            alias = _unique_name(agg_type.lower().replace("_", ""))
            shard_cols = [(f"{agg_type}({inner_sql})", alias)]
            merge_expr = f"AVG({alias})"

        elif agg_type == "COVAR_POP":
            # Compute per-shard covariance, then average across shards
            alias = _unique_name("covarpop")
            if isinstance(agg_node, exp.Anonymous) and len(agg_node.expressions) >= 2:
                second_arg_sql = _expr_sql(agg_node.expressions[1])
                first_arg_sql = inner_sql
            else:
                first_arg_sql = inner_sql
                second_arg_sql = inner_sql
            shard_cols = [(f"COVAR_POP({first_arg_sql}, {second_arg_sql})", alias)]
            merge_expr = f"AVG({alias})"

        agg_cache[agg_sql_key] = (shard_cols, merge_expr)
        return shard_cols, merge_expr

    def _find_all_aggs(node):
        agg_nodes = list(node.find_all(exp.AggFunc))
        anon_aggs = []
        for anon in node.find_all(exp.Anonymous):
            if anon.name.upper() in ("VAR_POP", "VARIANCE", "STDDEV_POP", "STDDEV", "COVAR_POP"):
                anon_aggs.append(anon)
        return agg_nodes + anon_aggs

    def _has_aggregates(node):
        return len(_find_all_aggs(node)) > 0

    added_shard_cols = set()

    def _add_shard_cols(shard_cols):
        for col_expr, col_alias in shard_cols:
            key = (col_expr, col_alias)
            if key not in added_shard_cols:
                added_shard_cols.add(key)
                shard_select_parts.append(f"{col_expr} AS {col_alias}")

    for sel_expr in select_expressions:
        if isinstance(sel_expr, exp.Alias):
            alias_name = sel_expr.alias
            inner = sel_expr.this
        else:
            alias_name = _expr_sql(sel_expr)
            inner = sel_expr

        if not _has_aggregates(inner):
            col_sql = _expr_sql(inner)
            shard_select_parts.append(f"{col_sql} AS {alias_name}")
            merge_select_parts.append(f"{alias_name}")
            final_columns.append(alias_name)
        else:
            all_aggs = _find_all_aggs(inner)
            if len(all_aggs) == 1 and _expr_sql(inner) == _expr_sql(all_aggs[0]):
                shard_cols, merge_expr = _process_aggregate(all_aggs[0])
                _add_shard_cols(shard_cols)
                merge_select_parts.append(f"{merge_expr} AS {alias_name}")
                final_columns.append(alias_name)
            else:
                expr_sql = _expr_sql(inner)
                for agg_node in all_aggs:
                    agg_sql = _expr_sql(agg_node)
                    shard_cols, merge_expr = _process_aggregate(agg_node)
                    _add_shard_cols(shard_cols)
                    expr_sql = expr_sql.replace(agg_sql, merge_expr, 1)
                merge_select_parts.append(f"{expr_sql} AS {alias_name}")
                final_columns.append(alias_name)

    group_by_sql = ""
    if group_cols:
        group_parts = [_expr_sql(g) for g in group_cols]
        group_by_sql = " GROUP BY " + ", ".join(group_parts)

    where_sql = ""
    if where:
        where_sql = " " + _expr_sql(where)

    from_sql = " " + _expr_sql(from_clause) if from_clause else ""
    joins_sql = ""
    for j in joins:
        joins_sql += " " + _expr_sql(j)

    shard_query = "SELECT " + ", ".join(shard_select_parts) + from_sql + joins_sql + where_sql + group_by_sql

    # Rewrite HAVING clause: aggregate references must be replaced with
    # their merge-phase equivalents so they reference shard_results columns
    having_sql = ""
    if having:
        having_expr = having.this
        having_aggs = _find_all_aggs(having_expr)
        having_str = _expr_sql(having_expr)
        for agg_node in having_aggs:
            agg_sql = _expr_sql(agg_node)
            shard_cols, merge_expr = _process_aggregate(agg_node)
            _add_shard_cols(shard_cols)
            having_str = having_str.replace(agg_sql, merge_expr, 1)
        having_sql = f" HAVING {having_str}"
        # Rebuild shard query to include any columns needed by HAVING
        shard_query = "SELECT " + ", ".join(shard_select_parts) + from_sql + joins_sql + where_sql + group_by_sql

    order_sql = ""
    if order_by:
        order_sql = " " + _expr_sql(order_by)

    merge_query = (
        "SELECT " + ", ".join(merge_select_parts)
        + " FROM shard_results"
        + group_by_sql
        + having_sql
        + order_sql
    )

    return {
        "shard_query": shard_query,
        "merge_query": merge_query,
        "final_columns": final_columns,
    }
