"""
Apply all nine bug fixes to the SQL AST stringifier.
Each fix is a targeted string replacement in the appropriate source file.
"""



def fix_file(path: str, replacements: list[tuple[str, str]]):
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise RuntimeError(f"Patch target not found in {path}:\n{old}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)


# ── Bug 1: Window frame BETWEEN (select.ts, windowFrameToSQL) ───────
# The end bound is ignored; BETWEEN...AND must be emitted when end exists.

fix_file("/app/src/select.ts", [
    (
        # Old: ignores end bound
        "  const startStr = frameBoundToSQL(start);\n"
        "  return `${type} ${startStr}`;",
        # New: emit BETWEEN...AND when end is present
        "  const startStr = frameBoundToSQL(start);\n"
        "  if (end) {\n"
        "    const endStr = frameBoundToSQL(end);\n"
        "    return `${type} BETWEEN ${startStr} AND ${endStr}`;\n"
        "  }\n"
        "  return `${type} ${startStr}`;",
    ),
    # ── Bug 7: DISTINCT ON (select.ts, distinctToSQL) ────────────────
    # Only emits the type ('DISTINCT') but drops the ON (columns) clause.
    (
        "  const { type } = distinct;\n"
        "  return type ? type.toUpperCase() : '';",
        "  const { type, columns } = distinct;\n"
        "  const result: string[] = [type ? type.toUpperCase() : ''];\n"
        "  if (columns) {\n"
        "    result.push(`ON (${columns.map((c: any) => exprToSQL(c)).join(', ')})`);\n"
        "  }\n"
        "  return result.filter(hasVal).join(' ');",
    ),
    # ── Bug 8a: ORDER BY NULLS FIRST/LAST (select.ts, orderByToSQL) ──
    # The nulls modifier is dropped from ORDER BY items.
    (
        "    const dir = item.type || 'ASC';\n"
        "    return `${exprToSQL(item.expr)} ${dir}`;\n"
        "  });\n"
        "  return `ORDER BY ${items.join(', ')}`;",
        "    const dir = item.type || 'ASC';\n"
        "    const nulls = item.nulls ? ` ${item.nulls.toUpperCase()}` : '';\n"
        "    return `${exprToSQL(item.expr)} ${dir}${nulls}`;\n"
        "  });\n"
        "  return `ORDER BY ${items.join(', ')}`;",
    ),
    # ── Bug 8b: NULLS also dropped inside OVER clause ─────────
    (
        "      const dir = item.type || 'ASC';\n"
        "      return `${exprToSQL(item.expr)} ${dir}`;\n"
        "    });\n"
        "    parts.push(`ORDER BY ${obParts.join(', ')}`);\n"
        "  }\n\n"
        "  if (over.window_frame_clause) {",
        "      const dir = item.type || 'ASC';\n"
        "      const nulls = item.nulls ? ` ${item.nulls.toUpperCase()}` : '';\n"
        "      return `${exprToSQL(item.expr)} ${dir}${nulls}`;\n"
        "    });\n"
        "    parts.push(`ORDER BY ${obParts.join(', ')}`);\n"
        "  }\n\n"
        "  if (over.window_frame_clause) {",
    ),
    # ── Bug 9: LATERAL join (select.ts, tablesToSQL) ─────────────────
    # The lateral flag on join table references is ignored.
    (
        "      const { join, on, using: usingCols } = t;\n"
        "      const parts: string[] = [];\n"
        "      parts.push(join ? toUpper(join) : ',');\n"
        "      parts.push(tableToSQL(t));",
        "      const { join, on, using: usingCols, lateral } = t;\n"
        "      const parts: string[] = [];\n"
        "      parts.push(join ? toUpper(join) : ',');\n"
        "      if (lateral) parts.push('LATERAL');\n"
        "      parts.push(tableToSQL(t));",
    ),
])


# ── Bug 2: CTE RECURSIVE (union.ts, withToSQL) ──────────────────────
# The recursive flag on CTEs is ignored.

fix_file("/app/src/union.ts", [
    (
        "  const keyword = 'WITH';",
        "  const isRecursive = withClauses.some((cte: any) => cte.recursive);\n"
        "  const keyword = isRecursive ? 'WITH RECURSIVE' : 'WITH';",
    ),
])


# ── Bugs 3, 4, 5 (func.ts) ──────────────────────────────────────────

fix_file("/app/src/func.ts", [
    # Bug 3: swap :: cast order (expr::type not type::expr)
    (
        "  // PostgreSQL :: cast syntax\n"
        "  return `${targetStr}::${exprStr}`;",
        "  // PostgreSQL :: cast syntax\n"
        "  return `${exprStr}::${targetStr}`;",
    ),
    # Bug 5: extract filter from expr (previously not destructured)
    (
        "  const { name, args, over } = expr;",
        "  const { name, args, over, filter } = expr;",
    ),
    # Bug 4: emit distinct keyword before argument
    (
        "  const parts: string[] = [];\n"
        "  parts.push(exprToSQL(argExpr));",
        "  const parts: string[] = [];\n"
        "  if (distinctKw) parts.push(distinctKw);\n"
        "  parts.push(exprToSQL(argExpr));",
    ),
    # Bug 5 (cont): add FILTER (WHERE ...) clause handling
    (
        "  const result = `${name.toUpperCase()}(${parts.join(' ')})`;\n"
        "  return [result, overStr].filter(hasVal).join(' ');",
        "  const result = `${name.toUpperCase()}(${parts.join(' ')})`;\n"
        "  const filterStr = filter ? ` FILTER (WHERE ${exprToSQL(filter.where)})` : '';\n"
        "  return [result + filterStr, overStr].filter(hasVal).join(' ');",
    ),
])


# ── Bug 6: Subquery UNION (init.ts, select handler) ─────────────────
# The select handler always calls selectToSQL, losing _next chain.

fix_file("/app/src/init.ts", [
    (
        "import { registerHandler } from './expr';\n"
        "import { selectToSQL } from './select';",
        "import { registerHandler } from './expr';\n"
        "import { selectToSQL } from './select';\n"
        "import { unionToSQL } from './union';",
    ),
    (
        "  const str = selectToSQL(expr);\n"
        "  return expr.parentheses ? `(${str})` : str;",
        "  const str = typeof expr._next === 'object' ? unionToSQL(expr) : selectToSQL(expr);\n"
        "  return expr.parentheses ? `(${str})` : str;",
    ),
])


print("All 9 bug fixes applied successfully.")
