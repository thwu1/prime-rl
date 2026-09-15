/**
 * SELECT statement stringification, including FROM, ORDER BY, LIMIT,
 * GROUP BY, HAVING, DISTINCT, and OVER (window functions).
 */
import { exprToSQL, getExprListSQL } from './expr';
import { identifierToSql, literalToSQL, toUpper, hasVal } from './util';

// ── DISTINCT ────────────────────────────────────────────────────────

function distinctToSQL(distinct: any): string {
  if (!distinct) return '';
  if (typeof distinct === 'string') return distinct;
  const { type } = distinct;
  return type ? type.toUpperCase() : '';
}

// ── Column / alias helpers ──────────────────────────────────────────

function asToSQL(alias: any): string {
  if (!alias) return '';
  if (typeof alias === 'string') return `AS ${identifierToSql(alias)}`;
  if (alias && alias.value) return `AS ${identifierToSql(alias.value)}`;
  return '';
}

function columnToSQL(col: any): string {
  const { expr, as: alias } = col;
  const exprStr = exprToSQL(expr);
  const aliasStr = asToSQL(alias);
  return [exprStr, aliasStr].filter(hasVal).join(' ');
}

function columnsToSQL(columns: any): string {
  if (!columns || columns === '*') return columns || '*';
  return columns.map(columnToSQL).join(', ');
}

// ── FROM / tables ───────────────────────────────────────────────────

function tableToSQL(tableInfo: any): string {
  if (!tableInfo) return '';
  if (tableInfo.type === 'dual') return 'DUAL';

  const { db, table, as: alias, schema, expr } = tableInfo;
  let tableName = '';

  if (expr) {
    tableName = exprToSQL(expr);
  } else {
    const parts: string[] = [];
    if (db) parts.push(identifierToSql(db));
    if (schema) parts.push(identifierToSql(schema));
    if (table) parts.push(identifierToSql(table));
    tableName = parts.join('.');
  }

  const result: string[] = [tableName];
  if (alias) result.push('AS', identifierToSql(alias));

  return result.filter(hasVal).join(' ');
}

function tablesToSQL(tables: any): string {
  if (!tables) return '';
  if (!Array.isArray(tables)) return tableToSQL(tables);

  const result: string[] = [];
  for (let i = 0; i < tables.length; i++) {
    const t = tables[i];
    if (i === 0) {
      result.push(tableToSQL(t));
    } else {
      const { join, on, using: usingCols } = t;
      const parts: string[] = [];
      parts.push(join ? toUpper(join) : ',');
      parts.push(tableToSQL(t));
      if (on) parts.push('ON', exprToSQL(on));
      if (usingCols)
        parts.push(
          `USING (${usingCols.map(literalToSQL).join(', ')})`
        );
      result.push(parts.filter(hasVal).join(' '));
    }
  }
  return result.join(' ');
}

// ── ORDER BY / LIMIT ────────────────────────────────────────────────

export function orderByToSQL(orderby: any[]): string {
  if (!Array.isArray(orderby) || orderby.length === 0) return '';
  const items = orderby.map((item: any) => {
    const dir = item.type || 'ASC';
    return `${exprToSQL(item.expr)} ${dir}`;
  });
  return `ORDER BY ${items.join(', ')}`;
}

export function limitToSQL(limit: any): string {
  if (!limit) return '';
  const { seperator, value } = limit;
  if (seperator === 'offset') {
    return `LIMIT ${literalToSQL(value[0])} OFFSET ${literalToSQL(value[1])}`;
  }
  return `LIMIT ${value.map(literalToSQL).join(', ')}`;
}

// ── Window / OVER ───────────────────────────────────────────────────

function frameBoundToSQL(bound: any): string {
  if (!bound) return '';
  const { type, value } = bound;
  if (value !== null && value !== undefined) {
    return `${value} ${type}`;
  }
  return type;
}

function windowFrameToSQL(frame: any): string {
  if (!frame) return '';
  if (typeof frame === 'string') return frame;
  const { type, start, end } = frame;
  const startStr = frameBoundToSQL(start);
  return `${type} ${startStr}`;
}

export function overToSQL(over: any): string {
  if (!over) return '';
  if (typeof over === 'string') return `OVER ${over}`;

  const parts: string[] = [];

  if (over.partitionby) {
    const pbParts = over.partitionby.map((p: any) => exprToSQL(p));
    parts.push(`PARTITION BY ${pbParts.join(', ')}`);
  }

  if (over.orderby) {
    const obParts = over.orderby.map((item: any) => {
      const dir = item.type || 'ASC';
      return `${exprToSQL(item.expr)} ${dir}`;
    });
    parts.push(`ORDER BY ${obParts.join(', ')}`);
  }

  if (over.window_frame_clause) {
    parts.push(windowFrameToSQL(over.window_frame_clause));
  }

  return `OVER (${parts.join(' ')})`;
}

// ── GROUP BY / HAVING ───────────────────────────────────────────────

function groupByToSQL(groupby: any): string {
  if (!groupby) return '';
  const { columns, modifiers } = groupby;
  if (!columns) return '';
  const colsStr = getExprListSQL(columns).join(', ');
  const result: string[] = [`GROUP BY ${colsStr}`];
  if (modifiers && modifiers.length > 0) {
    result.push(modifiers.map(literalToSQL).join(', '));
  }
  return result.join(' ');
}

// ── SELECT ──────────────────────────────────────────────────────────

export function selectToSQL(stmt: any): string {
  const {
    columns,
    distinct,
    from,
    where,
    groupby,
    having,
    orderby,
    limit,
    options,
    parentheses_symbol,
  } = stmt;

  const parts: string[] = ['SELECT'];

  if (options && Array.isArray(options)) parts.push(options.join(' '));

  const distinctStr = distinctToSQL(distinct);
  if (distinctStr) parts.push(distinctStr);

  parts.push(columnsToSQL(columns));

  if (from) parts.push('FROM', tablesToSQL(from));
  if (where) parts.push('WHERE', exprToSQL(where));

  const gbStr = groupByToSQL(groupby);
  if (gbStr) parts.push(gbStr);

  if (having) parts.push('HAVING', exprToSQL(having));

  const obStr = orderByToSQL(orderby);
  if (obStr) parts.push(obStr);

  const limStr = limitToSQL(limit);
  if (limStr) parts.push(limStr);

  const sql = parts.filter(hasVal).join(' ');
  return parentheses_symbol ? `(${sql})` : sql;
}
