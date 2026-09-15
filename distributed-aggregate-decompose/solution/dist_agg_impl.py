"""
Distributed SQL Aggregate Query Decomposer - Reference Solution


Uses sqlglot for SQL parsing and transforms aggregate queries
for distributed execution across sharded tables. Handles single-column
aggregates, COUNT(DISTINCT), and two-variable statistical aggregates
(COVAR_POP, CORR) by correctly decomposing them into shard-level
partial computations and merge-level recombination formulas.
"""
import re
import sqlglot
from sqlglot import exp


KNOWN_AGGS = {
    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
    'VAR_POP', 'VAR_SAMP', 'VARIANCE_POP', 'VARIANCE', 'VAR',
    'STDDEV_POP', 'STDDEV_SAMP', 'STDDEV',
    'COVAR_POP', 'COVAR_SAMP', 'CORR',
}


def decompose_query(sql, shard_tables):
    """
    Decompose a SQL aggregate query for distributed execution.

    Parses the query AST, identifies aggregate functions, decomposes each
    into shard-level partial aggregates and a merge-level recombination
    formula, then constructs shard and merge query strings.

    Key decomposition strategies:
    - Distributive aggregates (COUNT, SUM, MIN, MAX): direct partial merge
    - Algebraic aggregates (AVG, VAR, STDDEV): via SUM/SUM_SQ/COUNT partials
    - COUNT(DISTINCT col): expand shard GROUP BY to preserve distinct values
    - Two-variable aggregates (COVAR_POP, CORR): track cross-product sums
    """
    tree = sqlglot.parse_one(sql, dialect='duckdb')

    counter = [0]
    registry = {}        # agg_sql_key -> merge_formula
    shard_cols = []      # "EXPR AS alias" for shard SELECT
    distinct_groups = [] # (col_expr, alias) for COUNT(DISTINCT) GROUP BY expansion

    def _next():
        counter[0] += 1
        return counter[0]

    def _fname(node):
        """Extract and normalize aggregate function name."""
        s = node.sql(dialect='duckdb')
        m = re.match(r'(\w+)\s*\(', s)
        raw = m.group(1).upper() if m else ''
        norm = {
            'VARIANCE_POP': 'VAR_POP', 'VARIANCE': 'VAR_SAMP', 'VAR': 'VAR_SAMP',
            'STDDEV': 'STDDEV_SAMP',
        }
        return norm.get(raw, raw)

    def _inner(node):
        """Get inner expression SQL for single-argument aggregates."""
        if isinstance(node, exp.Count):
            if node.this is None or isinstance(node.this, exp.Star):
                return '*'
            if isinstance(node.this, exp.Distinct):
                return node.this.expressions[0].sql(dialect='duckdb')
        return node.this.sql(dialect='duckdb') if node.this else '*'

    def _biargs(node):
        """Get both arguments for two-variable aggregates (COVAR, CORR)."""
        if hasattr(node, 'expression') and node.expression is not None:
            return (node.this.sql(dialect='duckdb'),
                    node.expression.sql(dialect='duckdb'))
        if hasattr(node, 'expressions') and len(node.expressions) >= 2:
            return (node.expressions[0].sql(dialect='duckdb'),
                    node.expressions[1].sql(dialect='duckdb'))
        raise ValueError(f"Cannot extract binary args: {node.sql(dialect='duckdb')}")

    def _decompose(node):
        """Decompose an aggregate node into shard columns + merge formula."""
        key = node.sql(dialect='duckdb')
        if key in registry:
            return registry[key]

        n = _next()
        fn = _fname(node)

        # ---- COUNT(DISTINCT col): expand shard GROUP BY ----
        if fn == 'COUNT' and isinstance(getattr(node, 'this', None), exp.Distinct):
            dcol = node.this.expressions[0].sql(dialect='duckdb')
            alias = f'_dv{n}'
            distinct_groups.append((dcol, alias))
            merge = f'COUNT(DISTINCT {alias})'
            registry[key] = merge
            return merge

        # ---- Determine arguments ----
        if fn in ('COVAR_POP', 'COVAR_SAMP', 'CORR'):
            a, b = _biargs(node)
        else:
            x = _inner(node)

        # ---- Decomposition by aggregate type ----
        cols = []

        if fn == 'COUNT':
            cols = [(f'_c{n}', f'COUNT({x})')]
            merge = f'SUM(_c{n})'

        elif fn == 'SUM':
            cols = [(f'_s{n}', f'SUM({x})')]
            merge = f'SUM(_s{n})'

        elif fn == 'MIN':
            cols = [(f'_mn{n}', f'MIN({x})')]
            merge = f'MIN(_mn{n})'

        elif fn == 'MAX':
            cols = [(f'_mx{n}', f'MAX({x})')]
            merge = f'MAX(_mx{n})'

        elif fn == 'AVG':
            cols = [
                (f'_s{n}', f'SUM(CAST(({x}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({x})')
            ]
            merge = f'(SUM(_s{n}) / SUM(_c{n}))'

        elif fn == 'VAR_POP':
            cols = [
                (f'_s{n}', f'SUM(CAST(({x}) AS DOUBLE))'),
                (f'_ss{n}', f'SUM(CAST(({x}) AS DOUBLE) * CAST(({x}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({x})')
            ]
            merge = (f'(SUM(_ss{n}) / SUM(_c{n}) '
                     f'- POWER(SUM(_s{n}) / SUM(_c{n}), 2))')

        elif fn == 'VAR_SAMP':
            cols = [
                (f'_s{n}', f'SUM(CAST(({x}) AS DOUBLE))'),
                (f'_ss{n}', f'SUM(CAST(({x}) AS DOUBLE) * CAST(({x}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({x})')
            ]
            merge = (f'((SUM(_c{n}) * SUM(_ss{n}) - SUM(_s{n}) * SUM(_s{n})) '
                     f'/ (SUM(_c{n}) * (SUM(_c{n}) - 1)))')

        elif fn == 'STDDEV_POP':
            cols = [
                (f'_s{n}', f'SUM(CAST(({x}) AS DOUBLE))'),
                (f'_ss{n}', f'SUM(CAST(({x}) AS DOUBLE) * CAST(({x}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({x})')
            ]
            merge = (f'SQRT(SUM(_ss{n}) / SUM(_c{n}) '
                     f'- POWER(SUM(_s{n}) / SUM(_c{n}), 2))')

        elif fn == 'STDDEV_SAMP':
            cols = [
                (f'_s{n}', f'SUM(CAST(({x}) AS DOUBLE))'),
                (f'_ss{n}', f'SUM(CAST(({x}) AS DOUBLE) * CAST(({x}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({x})')
            ]
            merge = (f'SQRT((SUM(_c{n}) * SUM(_ss{n}) - SUM(_s{n}) * SUM(_s{n})) '
                     f'/ (SUM(_c{n}) * (SUM(_c{n}) - 1)))')

        elif fn == 'COVAR_POP':
            # COVAR_POP(x,y) = E[xy] - E[x]*E[y]
            cols = [
                (f'_sx{n}', f'SUM(CAST(({a}) AS DOUBLE))'),
                (f'_sy{n}', f'SUM(CAST(({b}) AS DOUBLE))'),
                (f'_sxy{n}', f'SUM(CAST(({a}) AS DOUBLE) * CAST(({b}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({a})')
            ]
            merge = (f'(SUM(_sxy{n}) / SUM(_c{n}) '
                     f'- (SUM(_sx{n}) / SUM(_c{n})) * (SUM(_sy{n}) / SUM(_c{n})))')

        elif fn == 'COVAR_SAMP':
            # COVAR_SAMP(x,y) = (N*SUM(xy) - SUM(x)*SUM(y)) / (N*(N-1))
            cols = [
                (f'_sx{n}', f'SUM(CAST(({a}) AS DOUBLE))'),
                (f'_sy{n}', f'SUM(CAST(({b}) AS DOUBLE))'),
                (f'_sxy{n}', f'SUM(CAST(({a}) AS DOUBLE) * CAST(({b}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({a})')
            ]
            merge = (f'((SUM(_c{n}) * SUM(_sxy{n}) - SUM(_sx{n}) * SUM(_sy{n})) '
                     f'/ (SUM(_c{n}) * (SUM(_c{n}) - 1)))')

        elif fn == 'CORR':
            # CORR(x,y) = COVAR_POP(x,y) / (STDDEV_POP(x) * STDDEV_POP(y))
            cols = [
                (f'_sx{n}', f'SUM(CAST(({a}) AS DOUBLE))'),
                (f'_sy{n}', f'SUM(CAST(({b}) AS DOUBLE))'),
                (f'_sxy{n}', f'SUM(CAST(({a}) AS DOUBLE) * CAST(({b}) AS DOUBLE))'),
                (f'_sxx{n}', f'SUM(CAST(({a}) AS DOUBLE) * CAST(({a}) AS DOUBLE))'),
                (f'_syy{n}', f'SUM(CAST(({b}) AS DOUBLE) * CAST(({b}) AS DOUBLE))'),
                (f'_c{n}', f'COUNT({a})')
            ]
            cov = (f'(SUM(_sxy{n}) / SUM(_c{n}) '
                   f'- (SUM(_sx{n}) / SUM(_c{n})) * (SUM(_sy{n}) / SUM(_c{n})))')
            sx = (f'SQRT(SUM(_sxx{n}) / SUM(_c{n}) '
                  f'- POWER(SUM(_sx{n}) / SUM(_c{n}), 2))')
            sy = (f'SQRT(SUM(_syy{n}) / SUM(_c{n}) '
                  f'- POWER(SUM(_sy{n}) / SUM(_c{n}), 2))')
            merge = f'({cov} / ({sx} * {sy}))'

        else:
            raise ValueError(f'Unsupported aggregate: {fn}')

        for alias, expr in cols:
            shard_cols.append(f'{expr} AS {alias}')
        registry[key] = merge
        return merge

    def _find_aggs(node):
        """Find all aggregate function nodes, including those parsed as Anonymous."""
        res = list(node.find_all(exp.AggFunc))
        for a in node.find_all(exp.Anonymous):
            nm = getattr(a, 'name', '')
            if nm.upper() in KNOWN_AGGS:
                res.append(a)
        return res

    def _rewrite(sql_str, ast):
        """Replace aggregate expressions in a SQL string with merge formulas."""
        aggs = _find_aggs(ast)
        if not aggs:
            return sql_str
        reps = [(a.sql(dialect='duckdb'), _decompose(a)) for a in aggs]
        reps.sort(key=lambda r: len(r[0]), reverse=True)
        out = sql_str
        for old, new in reps:
            out = out.replace(old, new)
        return out

    # ---- Extract query structure ----
    grp = tree.find(exp.Group)
    gcols = [e.sql(dialect='duckdb') for e in grp.expressions] if grp else []

    # ---- Process SELECT ----
    sel = tree.find(exp.Select)
    merge_parts = []
    for expr in sel.expressions:
        aname = expr.alias if isinstance(expr, exp.Alias) else None
        core = expr.this if isinstance(expr, exp.Alias) else expr
        csql = core.sql(dialect='duckdb')
        if _find_aggs(core):
            csql = _rewrite(csql, core)
        if aname:
            merge_parts.append(f'{csql} AS {aname}')
        else:
            merge_parts.append(csql)

    # ---- Process HAVING ----
    hav = tree.find(exp.Having)
    mhav = ''
    if hav:
        hs = hav.this.sql(dialect='duckdb')
        hs = _rewrite(hs, hav.this)
        mhav = f' HAVING {hs}'

    # ---- Process ORDER BY ----
    ordc = tree.find(exp.Order)
    mord = ''
    if ordc:
        ops = []
        for o in ordc.expressions:
            osql = o.sql(dialect='duckdb')
            if _find_aggs(o):
                osql = _rewrite(osql, o)
            ops.append(osql)
        mord = f' ORDER BY {", ".join(ops)}'

    # ---- Process LIMIT ----
    lim = tree.find(exp.Limit)
    mlim = ''
    if lim:
        mlim = f' LIMIT {lim.expression.sql(dialect="duckdb")}'

    # ---- Shard WHERE (push down) ----
    wh = tree.find(exp.Where)
    swhere = ''
    if wh:
        swhere = f' WHERE {wh.this.sql(dialect="duckdb")}'

    # ---- Build shard query ----
    sg = list(gcols)
    ssel = list(gcols)

    for dcol, dalias in distinct_groups:
        ssel.append(f'{dcol} AS {dalias}')
        sg.append(dcol)

    ssel.extend(shard_cols)

    sgstr = f' GROUP BY {", ".join(sg)}' if sg else ''
    sq = f'SELECT {", ".join(ssel)} FROM {{shard_table}}{swhere}{sgstr}'

    # ---- Build merge query ----
    mgstr = f' GROUP BY {", ".join(gcols)}' if gcols else ''
    mq = f'SELECT {", ".join(merge_parts)} FROM shard_results{mgstr}{mhav}{mord}{mlim}'

    return {'shard_query_template': sq, 'merge_query': mq}
