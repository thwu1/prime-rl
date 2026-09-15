// SQL AST to SQL string converter — corrected implementation
//

import { Dialect, SqlifyOptions } from './types';

export function sqlify(ast: any, options: SqlifyOptions): string {
  if (!ast) return '';
  if (Array.isArray(ast)) {
    return ast.map((s: any) => sqlify(s.ast || s, options)).join(' ; ');
  }
  const stmt = ast.ast || ast;
  return unionToSQL(stmt, options.dialect);
}

function identifierQuote(dialect: Dialect): string {
  switch (dialect) {
    case 'mysql':
      return '`';
    case 'postgresql':
      return '"';
    case 'snowflake':
      return '"';
    default:
      return '`';
  }
}

function quoteIdent(name: string, dialect: Dialect): string {
  if (!name || name === '*') return name || '';
  const q = identifierQuote(dialect);
  return `${q}${name}${q}`;
}

function literalToSQL(lit: any): string {
  if (lit === undefined || lit === null) return '';
  if (typeof lit !== 'object') return String(lit);
  const { type, value, prefix } = lit;
  switch (type) {
    case 'string':
    case 'single_quote_string':
      return `'${value}'`;
    case 'number':
      return String(value);
    case 'boolean':
    case 'bool':
      return value ? 'TRUE' : 'FALSE';
    case 'null':
      return 'NULL';
    case 'star':
      return '*';
    case 'double_quote_string':
      return `"${value}"`;
    case 'backticks_quote_string':
      return `\`${value}\``;
    case 'param':
      return `${prefix || ':'}${value}`;
    case 'origin':
      return String(value).toUpperCase();
    case 'default':
      return value != null ? String(value) : '';
    default:
      return value != null ? String(value) : '';
  }
}

function exprToSQL(expr: any, dialect: Dialect): string {
  if (!expr) return '';
  if (expr.ast) {
    return `(${unionToSQL(expr.ast, dialect)})`;
  }
  switch (expr.type) {
    case 'column_ref':
      return columnRefToSQL(expr, dialect);
    case 'binary_expr':
      return binaryExprToSQL(expr, dialect);
    case 'unary_expr':
      return unaryExprToSQL(expr, dialect);
    case 'case':
      return caseExprToSQL(expr, dialect);
    case 'aggr_func':
      return aggrFuncToSQL(expr, dialect);
    case 'function':
      return funcToSQL(expr, dialect);
    case 'cast':
      return castExprToSQL(expr, dialect);
    case 'expr_list':
      return exprListToSQL(expr, dialect);
    case 'select':
      return selectExprToSQL(expr, dialect);
    default:
      return literalToSQL(expr);
  }
}

function columnRefToSQL(expr: any, dialect: Dialect): string {
  const parts: string[] = [];
  if (expr.schema) parts.push(quoteIdent(expr.schema, dialect));
  if (expr.table) parts.push(quoteIdent(expr.table, dialect));
  const col = typeof expr.column === 'string'
    ? (expr.column === '*' ? '*' : quoteIdent(expr.column, dialect))
    : exprToSQL(expr.column, dialect);
  parts.push(col);
  return parts.join('.');
}

function binaryExprToSQL(expr: any, dialect: Dialect): string {
  const op: string = expr.operator || expr.op;
  const leftStr = Array.isArray(expr.left)
    ? expr.left.map((e: any) => exprToSQL(e, dialect)).join(', ')
    : exprToSQL(expr.left, dialect);
  let rightStr: string;

  if (expr.right && expr.right.type === 'expr_list' && Array.isArray(expr.right.value)) {
    const values = expr.right.value.map((e: any) => exprToSQL(e, dialect));
    if (op === 'BETWEEN' || op === 'NOT BETWEEN') {
      rightStr = values.join(' AND ');
    } else {
      rightStr = `(${values.join(', ')})`;
    }
  } else {
    rightStr = exprToSQL(expr.right, dialect);
  }

  const parts = [leftStr, op, rightStr].filter(Boolean);
  const result = parts.join(op === '.' ? '' : ' ');
  return expr.parentheses ? `(${result})` : result;
}

function unaryExprToSQL(expr: any, dialect: Dialect): string {
  const { operator, parentheses } = expr;
  const space = ['-', '+', '~', '!'].includes(operator) ? '' : ' ';
  const str = `${operator}${space}${exprToSQL(expr.expr, dialect)}`;
  return parentheses ? `(${str})` : str;
}

function exprListToSQL(expr: any, dialect: Dialect): string {
  const values = (expr.value || []).map((e: any) => exprToSQL(e, dialect));
  const sep = expr.separator || ', ';
  const str = values.join(sep);
  return expr.parentheses ? `(${str})` : str;
}

function caseExprToSQL(expr: any, dialect: Dialect): string {
  const parts: string[] = ['CASE'];
  if (expr.expr) parts.push(exprToSQL(expr.expr, dialect));
  for (const arg of expr.args) {
    if (arg.type === 'when') {
      parts.push(
        'WHEN', exprToSQL(arg.cond, dialect),
        'THEN', exprToSQL(arg.result, dialect)
      );
    } else if (arg.type === 'else') {
      parts.push('ELSE', exprToSQL(arg.result, dialect));
    }
  }
  parts.push('END');
  return parts.join(' ');
}

function aggrFuncToSQL(expr: any, dialect: Dialect): string {
  const { name, args, over } = expr;
  const funcName = name.toUpperCase();
  const innerParts: string[] = [];
  if (args.distinct) innerParts.push(args.distinct.toUpperCase());
  innerParts.push(exprToSQL(args.expr, dialect));
  let result = `${funcName}(${innerParts.join(' ')})`;
  if (over) {
    result += ` ${overToSQL(over, dialect)}`;
  }
  return result;
}

function overToSQL(over: any, dialect: Dialect): string {
  if (!over) return '';
  if (typeof over === 'string') return `OVER ${quoteIdent(over, dialect)}`;
  const parts: string[] = [];
  if (over.partitionby) {
    const pbCols = over.partitionby.map((p: any) =>
      exprToSQL(p.expr || p, dialect)
    );
    parts.push(`PARTITION BY ${pbCols.join(', ')}`);
  }
  if (over.orderby) {
    parts.push(orderByClauseToSQL(over.orderby, dialect));
  }
  if (over.window_frame_clause) {
    parts.push(over.window_frame_clause.toUpperCase());
  }
  return `OVER (${parts.join(' ')})`;
}

function funcToSQL(expr: any, dialect: Dialect): string {
  const { name, args, over } = expr;
  const funcName = name.name.map((n: any) => literalToSQL(n)).join('.');
  const schemaPrefix = name.schema ? `${literalToSQL(name.schema)}.` : '';
  const fullName = `${schemaPrefix}${funcName}`;

  let result: string;
  if (!args) {
    result = fullName;
  } else {
    const argVals = (args.value || []).map((e: any) => exprToSQL(e, dialect));
    result = `${fullName}(${argVals.join(', ')})`;
  }

  if (over) {
    result += ` ${overToSQL(over, dialect)}`;
  }

  return result;
}

function castExprToSQL(expr: any, dialect: Dialect): string {
  const { keyword, expr: innerExpr, symbol, target } = expr;
  const exprStr = exprToSQL(innerExpr, dialect);

  if (symbol === 'as') {
    const targetStr = target.map((t: any) => castTargetToSQL(t)).join('');
    return `${keyword.toUpperCase()}(${exprStr} AS ${targetStr})`;
  } else if (symbol === '::') {
    let result = exprStr;
    for (const t of target) {
      result += `::${castTargetToSQL(t)}`;
    }
    return result;
  }

  return exprStr;
}

function castTargetToSQL(t: any): string {
  let str = t.dataType;
  if (t.length != null) {
    str += t.scale != null ? `(${t.length}, ${t.scale})` : `(${t.length})`;
  }
  return str;
}

function selectExprToSQL(expr: any, dialect: Dialect): string {
  const str = expr._next ? unionToSQL(expr, dialect) : selectToSQL(expr, dialect);
  return expr.parentheses ? `(${str})` : str;
}

function fromToSQL(from: any[], dialect: Dialect): string {
  if (!from || from.length === 0) return '';
  const parts: string[] = [];

  const base = from[0];
  if (base.type === 'dual') {
    parts.push('DUAL');
  } else {
    parts.push(tableToSQL(base, dialect));
  }

  for (let i = 1; i < from.length; i++) {
    const item = from[i];
    if (item.join) {
      const joinStr = item.join.toUpperCase();
      const tableStr = tableToSQL(item, dialect);
      const joinParts = [joinStr, tableStr];
      if (item.on) {
        joinParts.push('ON', exprToSQL(item.on, dialect));
      }
      if (item.using) {
        joinParts.push(
          `USING (${item.using.map((u: any) => typeof u === 'string' ? u : literalToSQL(u)).join(', ')})`
        );
      }
      parts.push(joinParts.join(' '));
    } else {
      parts.push(`, ${tableToSQL(item, dialect)}`);
    }
  }

  return parts.join(' ');
}

function tableToSQL(table: any, dialect: Dialect): string {
  if (!table) return '';

  if (table.expr && table.expr.ast) {
    const sub = `(${unionToSQL(table.expr.ast, dialect)})`;
    if (table.as) {
      return `${sub} AS ${quoteIdent(table.as, dialect)}`;
    }
    return sub;
  }

  const parts: string[] = [];
  if (table.db) parts.push(quoteIdent(table.db, dialect));
  if (table.schema) parts.push(quoteIdent(table.schema, dialect));
  if (table.table) parts.push(quoteIdent(table.table, dialect));
  let result = parts.join('.');

  if (table.as) {
    result += ` AS ${quoteIdent(table.as, dialect)}`;
  }

  return result;
}

function selectToSQL(stmt: any, dialect: Dialect): string {
  const parts: string[] = [];

  if (stmt.with) {
    parts.push(withToSQL(stmt.with, stmt.recursive, dialect));
  }

  parts.push('SELECT');

  if (Array.isArray(stmt.options)) {
    parts.push(stmt.options.join(' '));
  }

  if (stmt.distinct) {
    if (typeof stmt.distinct === 'string') {
      parts.push(stmt.distinct.toUpperCase());
    }
  }

  parts.push(columnsToSQL(stmt.columns, dialect));

  if (stmt.from) {
    parts.push('FROM', fromToSQL(stmt.from, dialect));
  }

  if (stmt.where) {
    parts.push('WHERE', exprToSQL(stmt.where, dialect));
  }

  if (stmt.groupby) {
    const gbCols = (stmt.groupby.columns || []).map((c: any) => exprToSQL(c, dialect));
    if (gbCols.length > 0) {
      parts.push(`GROUP BY ${gbCols.join(', ')}`);
    }
  }

  if (stmt.having) {
    parts.push('HAVING', exprToSQL(stmt.having, dialect));
  }

  if (stmt.orderby) {
    parts.push(orderByClauseToSQL(stmt.orderby, dialect));
  }

  if (stmt.limit) {
    parts.push(limitToSQL(stmt.limit, dialect));
  }

  const sql = parts.filter(Boolean).join(' ');
  return stmt.parentheses_symbol ? `(${sql})` : sql;
}

function columnsToSQL(columns: any, dialect: Dialect): string {
  if (!columns) return '*';
  if (columns === '*') return '*';
  if (!Array.isArray(columns)) return '*';
  return columns.map((col: any) => {
    const expr = exprToSQL(col.expr, dialect);
    if (col.as) {
      const alias = typeof col.as === 'string'
        ? quoteIdent(col.as, dialect)
        : literalToSQL(col.as);
      return `${expr} AS ${alias}`;
    }
    return expr;
  }).join(', ');
}

function withToSQL(withItems: any[], recursive: boolean, dialect: Dialect): string {
  if (!withItems || withItems.length === 0) return '';
  const keyword = recursive ? 'WITH RECURSIVE' : 'WITH';
  const items = withItems.map((item: any) => {
    const name = quoteIdent(
      typeof item.name === 'string' ? item.name : item.name.value,
      dialect
    );
    const cols = item.columns ? `(${item.columns.join(', ')})` : '';
    const body = unionToSQL(item.stmt.ast || item.stmt, dialect);
    return `${name}${cols} AS (${body})`;
  });
  return `${keyword} ${items.join(', ')}`;
}

function unionToSQL(stmt: any, dialect: Dialect): string {
  if (!stmt) return '';
  const parts: string[] = [];

  let firstSelect = selectToSQL(stmt, dialect);
  if (stmt._parentheses) firstSelect = `(${firstSelect})`;
  parts.push(firstSelect);

  let current = stmt;
  while (current._next) {
    const setOp = (current.set_op || 'UNION').toUpperCase();
    parts.push(setOp);
    let nextSelect = selectToSQL(current._next, dialect);
    if (current._next._parentheses) nextSelect = `(${nextSelect})`;
    parts.push(nextSelect);
    current = current._next;
  }

  if (stmt._orderby) parts.push(orderByClauseToSQL(stmt._orderby, dialect));
  if (stmt._limit) parts.push(limitToSQL(stmt._limit, dialect));

  return parts.filter(Boolean).join(' ');
}

function orderByClauseToSQL(orderby: any[], dialect: Dialect): string {
  if (!orderby || orderby.length === 0) return '';
  const items = orderby.map((item: any) => {
    const exprParts = [exprToSQL(item.expr, dialect)];
    exprParts.push((item.type || 'ASC').toUpperCase());
    if (item.nulls) exprParts.push(item.nulls.toUpperCase());
    return exprParts.join(' ');
  });
  return `ORDER BY ${items.join(', ')}`;
}

function limitToSQL(limit: any, dialect: Dialect): string {
  if (!limit) return '';
  const { separator, value } = limit;
  if (!value || value.length === 0) return '';

  if (separator === 'offset') {
    const limitVal = literalToSQL(value[0]);
    const offsetVal = value.length > 1 ? literalToSQL(value[1]) : null;
    const parts = [`LIMIT ${limitVal}`];
    if (offsetVal) parts.push(`OFFSET ${offsetVal}`);
    return parts.join(' ');
  } else {
    return `LIMIT ${value.map(literalToSQL).join(', ')}`;
  }
}
