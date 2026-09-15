import { exprToSQL, registerHandler } from './expr';
import { identifierToSql, hasVal } from './util';

function columnRefToSQL(expr: any): string {
  const { column, table, schema, db } = expr;
  const parts: string[] = [];

  if (db) parts.push(identifierToSql(db));
  if (schema) parts.push(identifierToSql(schema));
  if (table) parts.push(identifierToSql(table));

  let colStr: string;
  if (column === '*') {
    colStr = '*';
  } else if (typeof column === 'string') {
    colStr = identifierToSql(column);
  } else if (column && column.expr) {
    colStr = exprToSQL(column.expr);
  } else {
    colStr = '';
  }

  parts.push(colStr);
  return parts.join('.');
}

registerHandler('column_ref', columnRefToSQL);

export { columnRefToSQL };
