"""
Distributed SQL Aggregate Query Decomposer.

Decomposes SQL aggregate queries into shard (map) and merge (reduce) phases
for correct distributed execution. Handles:
- Distributive aggregates: SUM, COUNT, MIN, MAX
- Algebraic aggregates: AVG (SUM/COUNT decomposition over full expressions)
- Univariate statistics: VAR_POP, STDDEV_POP (parallel variance formula)
- Bivariate statistics: COVAR_POP (parallel covariance formula)
- HAVING clauses rewritten for merge phase
- ORDER BY preserved in merge phase
- Multi-table join queries with GROUP BY alias remapping

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

    # Cache: map from aggregate SQL string -> (shard_aliases, merge_expr)
    # Ensures HAVING reuses the same shard columns as SELECT
    agg_cache = {}

    # Track mapping from GROUP BY column expressions to their aliases
    # Needed for multi-table queries where GROUP BY n.n_name must become
    # GROUP BY alias_name in the merge query (shard_results has no table refs)
    group_col_to_alias = {}

    def _unique_name(prefix):
        _counter[0] += 1
        return f"__{prefix}_{_counter[0]}"

    def _expr_sql(e):
        return e.sql(dialect="duckdb")

    def _get_agg_type(node):
        """Classify an aggregate node."""
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
        # Check for dedicated bivariate types
        if hasattr(exp, 'CovarPop') and isinstance(node, getattr(exp, 'CovarPop')):
            return "COVAR_POP"
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
        """Get the inner expression of a single-argument aggregate."""
        if agg_type == "COUNT" and node.find(exp.Star):
            return None
        if isinstance(node, exp.Anonymous):
            return node.expressions[0] if node.expressions else None
        return node.this

    def _get_covar_args(node):
        """Get both arguments for COVAR_POP(y, x)."""
        if isinstance(node, exp.Anonymous):
            if len(node.expressions) >= 2:
                return node.expressions[0], node.expressions[1]
        # For dedicated expression types that use this/expression
        if hasattr(node, 'this') and hasattr(node, 'expression'):
            return node.this, node.expression
        return None, None

    def _process_aggregate(agg_node):
        """Process an aggregate and return (shard_cols_list, merge_expr_str).
        Uses cache to avoid duplicating shard columns for the same aggregate."""
        agg_sql_key = _expr_sql(agg_node)
        if agg_sql_key in agg_cache:
            return agg_cache[agg_sql_key]

        agg_type = _get_agg_type(agg_node)
        if agg_type is None:
            agg_type = "SUM"  # fallback

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
            # Per-shard counts are partial; SUM them for global count
            merge_expr = f"SUM({alias})"

        elif agg_type == "AVG":
            # AVG(expr) = SUM(expr) / COUNT(expr)
            # Must use the FULL expression, not just first column reference
            sum_alias = _unique_name("avg_sum")
            cnt_alias = _unique_name("avg_cnt")
            shard_cols = [
                (f"SUM({inner_sql})", sum_alias),
                (f"COUNT({inner_sql})", cnt_alias),
            ]
            merge_expr = f"(SUM({sum_alias}) / SUM({cnt_alias}))"

        elif agg_type == "VAR_POP":
            # Parallel variance: E[X^2] - (E[X])^2
            # Shard pushes partial sum, sum-of-squares, count
            sum_alias = _unique_name("var_sum")
            sumsq_alias = _unique_name("var_sumsq")
            cnt_alias = _unique_name("var_cnt")
            shard_cols = [
                (f"SUM({inner_sql})", sum_alias),
                (f"SUM(({inner_sql}) * ({inner_sql}))", sumsq_alias),
                (f"COUNT({inner_sql})", cnt_alias),
            ]
            merge_expr = (
                f"((SUM({sumsq_alias}) / SUM({cnt_alias})) - "
                f"POWER(SUM({sum_alias}) / SUM({cnt_alias}), 2))"
            )

        elif agg_type == "STDDEV_POP":
            sum_alias = _unique_name("std_sum")
            sumsq_alias = _unique_name("std_sumsq")
            cnt_alias = _unique_name("std_cnt")
            shard_cols = [
                (f"SUM({inner_sql})", sum_alias),
                (f"SUM(({inner_sql}) * ({inner_sql}))", sumsq_alias),
                (f"COUNT({inner_sql})", cnt_alias),
            ]
            merge_expr = (
                f"SQRT((SUM({sumsq_alias}) / SUM({cnt_alias})) - "
                f"POWER(SUM({sum_alias}) / SUM({cnt_alias}), 2))"
            )

        elif agg_type == "COVAR_POP":
            # Parallel covariance: Cov(Y, X) = E[YX] - E[Y]*E[X]
            # Shard pushes: SUM(Y*X), SUM(Y), SUM(X), COUNT(*)
            # Merge: SUM(sum_yx)/SUM(cnt) - (SUM(sum_y)/SUM(cnt))*(SUM(sum_x)/SUM(cnt))
            arg_y, arg_x = _get_covar_args(agg_node)
            y_sql = _expr_sql(arg_y)
            x_sql = _expr_sql(arg_x)

            sum_yx_alias = _unique_name("cov_sumyx")
            sum_y_alias = _unique_name("cov_sumy")
            sum_x_alias = _unique_name("cov_sumx")
            cnt_alias = _unique_name("cov_cnt")
            shard_cols = [
                (f"SUM(({y_sql}) * ({x_sql}))", sum_yx_alias),
                (f"SUM({y_sql})", sum_y_alias),
                (f"SUM({x_sql})", sum_x_alias),
                (f"COUNT(*)", cnt_alias),
            ]
            merge_expr = (
                f"((SUM({sum_yx_alias}) / SUM({cnt_alias})) - "
                f"(SUM({sum_y_alias}) / SUM({cnt_alias})) * "
                f"(SUM({sum_x_alias}) / SUM({cnt_alias})))"
            )

        agg_cache[agg_sql_key] = (shard_cols, merge_expr)
        return shard_cols, merge_expr

    def _find_all_aggs(node):
        """Find all aggregate function nodes in an expression."""
        agg_nodes = list(node.find_all(exp.AggFunc))
        anon_aggs = []
        for anon in node.find_all(exp.Anonymous):
            if anon.name.upper() in ("VAR_POP", "VARIANCE", "STDDEV_POP", "STDDEV", "COVAR_POP"):
                anon_aggs.append(anon)
        return agg_nodes + anon_aggs

    def _has_aggregates(node):
        return len(_find_all_aggs(node)) > 0

    # Track which shard columns we've already added (by their expression+alias key)
    added_shard_cols = set()

    def _add_shard_cols(shard_cols):
        for col_expr, col_alias in shard_cols:
            key = (col_expr, col_alias)
            if key not in added_shard_cols:
                added_shard_cols.add(key)
                shard_select_parts.append(f"{col_expr} AS {col_alias}")

    # Process SELECT expressions
    for sel_expr in select_expressions:
        if isinstance(sel_expr, exp.Alias):
            alias_name = sel_expr.alias
            inner = sel_expr.this
        else:
            alias_name = _expr_sql(sel_expr)
            inner = sel_expr

        if not _has_aggregates(inner):
            # Group-by column or passthrough expression
            col_sql = _expr_sql(inner)
            shard_select_parts.append(f"{col_sql} AS {alias_name}")
            merge_select_parts.append(f"{alias_name}")
            final_columns.append(alias_name)
            # Track GROUP BY column alias mapping for merge phase
            group_col_to_alias[col_sql] = alias_name
        else:
            all_aggs = _find_all_aggs(inner)
            if len(all_aggs) == 1 and _expr_sql(inner) == _expr_sql(all_aggs[0]):
                # Simple: the expression IS the single aggregate
                shard_cols, merge_expr = _process_aggregate(all_aggs[0])
                _add_shard_cols(shard_cols)
                merge_select_parts.append(f"{merge_expr} AS {alias_name}")
                final_columns.append(alias_name)
            else:
                # Complex: expression contains aggregate(s) mixed with arithmetic
                expr_sql = _expr_sql(inner)
                for agg_node in all_aggs:
                    agg_sql = _expr_sql(agg_node)
                    shard_cols, merge_expr = _process_aggregate(agg_node)
                    _add_shard_cols(shard_cols)
                    expr_sql = expr_sql.replace(agg_sql, merge_expr, 1)
                merge_select_parts.append(f"{expr_sql} AS {alias_name}")
                final_columns.append(alias_name)

    # Build GROUP BY for shard query (uses original column references)
    group_by_sql = ""
    if group_cols:
        group_parts = [_expr_sql(g) for g in group_cols]
        group_by_sql = " GROUP BY " + ", ".join(group_parts)

    # Build GROUP BY for merge query (uses aliases from shard SELECT)
    # This is critical for multi-table queries where GROUP BY n.n_name
    # must become GROUP BY nation_name in the merge phase
    merge_group_by_sql = ""
    if group_cols:
        merge_group_parts = []
        for g in group_cols:
            g_sql = _expr_sql(g)
            if g_sql in group_col_to_alias:
                merge_group_parts.append(group_col_to_alias[g_sql])
            else:
                merge_group_parts.append(g_sql)
        merge_group_by_sql = " GROUP BY " + ", ".join(merge_group_parts)

    # Build WHERE
    where_sql = ""
    if where:
        where_sql = " " + _expr_sql(where)

    # Build FROM and JOINs
    from_sql = " " + _expr_sql(from_clause) if from_clause else ""
    joins_sql = ""
    for j in joins:
        joins_sql += " " + _expr_sql(j)

    # Build shard query
    shard_query = "SELECT " + ", ".join(shard_select_parts) + from_sql + joins_sql + where_sql + group_by_sql

    # Build HAVING for merge - rewrite aggregates to merge expressions
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
        # Rebuild shard query with any new columns added by HAVING
        shard_query = "SELECT " + ", ".join(shard_select_parts) + from_sql + joins_sql + where_sql + group_by_sql

    # Build ORDER BY for merge
    order_sql = ""
    if order_by:
        order_sql = " " + _expr_sql(order_by)

    # Build merge query using merge-specific GROUP BY aliases
    merge_query = (
        "SELECT " + ", ".join(merge_select_parts)
        + " FROM shard_results"
        + merge_group_by_sql
        + having_sql
        + order_sql
    )

    return {
        "shard_query": shard_query,
        "merge_query": merge_query,
        "final_columns": final_columns,
    }
