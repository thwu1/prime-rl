/**
 * UNION / set-operation handling and WITH (CTE) clause.
 * Top-level AST dispatch: sqlify → unionToSQL → selectToSQL.
 */
import { exprToSQL } from './expr';
import { selectToSQL, orderByToSQL, limitToSQL } from './select';
import { identifierToSql, literalToSQL, toUpper, hasVal } from './util';

// ── WITH (CTE) ─────────────────────────────────────────────────────

function withToSQL(withClauses: any[]): string {
  if (!withClauses || withClauses.length === 0) return '';

  const keyword = 'WITH';

  const clauses = withClauses.map((cte: any) => {
    const nameStr =
      typeof cte.name === 'string'
        ? cte.name
        : cte.name.value || literalToSQL(cte.name);
    const quotedName = identifierToSql(nameStr);
    const stmtAst = cte.stmt.ast || cte.stmt;
    const stmtSQL =
      typeof stmtAst._next === 'object'
        ? unionToSQL(stmtAst)
        : selectToSQL(stmtAst);
    let cols = '';
    if (cte.columns && cte.columns.length > 0) {
      cols = ` (${cte.columns.map(exprToSQL).join(', ')})`;
    }
    return `${quotedName}${cols} AS (${stmtSQL})`;
  });

  return `${keyword} ${clauses.join(', ')}`;
}

// ── UNION / INTERSECT / EXCEPT ──────────────────────────────────────

export function unionToSQL(stmt: any): string {
  if (!stmt) return '';

  const { with: withInfo, _orderby, _limit } = stmt;
  const result: string[] = [];

  const withStr = withToSQL(withInfo);
  if (withStr) result.push(withStr);

  result.push(selectToSQL(stmt));

  let current = stmt;
  while (current._next) {
    const setOp = current.set_op || 'UNION';
    result.push(toUpper(setOp));
    result.push(selectToSQL(current._next));
    current = current._next;
  }

  const obStr = orderByToSQL(_orderby);
  if (obStr) result.push(obStr);

  const limStr = limitToSQL(_limit);
  if (limStr) result.push(limStr);

  return result.filter(hasVal).join(' ');
}
