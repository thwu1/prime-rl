/**
 * Handler registration – imports every stringifier module so that
 * their registerHandler() calls execute, then wires up the 'select'
 * handler which needs both selectToSQL and unionToSQL.
 */
import './binary';
import './case';
import './column';
import './func';
import { registerHandler } from './expr';
import { selectToSQL } from './select';

// Register the 'select' type handler for sub-query expressions
// (e.g. a SELECT used inside FROM, WHERE, or as a column value).
registerHandler('select', (expr: any) => {
  const str = selectToSQL(expr);
  return expr.parentheses ? `(${str})` : str;
});
