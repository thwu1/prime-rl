/**
 * Central expression dispatch hub.
 *
 * All AST expression nodes are routed through exprToSQL(), which looks
 * up a handler by node type. Handlers are registered by the various
 * stringifier modules at import time (see init.ts).
 */
import { literalToSQL, toUpper, hasVal } from './util';

type ExprHandler = (expr: any) => any;
const handlers: Record<string, ExprHandler> = {};

export function registerHandler(type: string, fn: ExprHandler): void {
  handlers[type] = fn;
}

export function exprToSQL(expr: any): any {
  if (!expr) return '';
  const { type } = expr;
  if (type === 'expr') return exprToSQL(expr.expr);
  if (handlers[type]) return handlers[type](expr);
  return literalToSQL(expr);
}

export function getExprListSQL(exprList: any): string[] {
  if (!exprList) return [];
  const list = Array.isArray(exprList) ? exprList : [exprList];
  return list.map((e: any) => exprToSQL(e));
}

// ── Built-in handlers ──────────────────────────────────────────────

registerHandler('expr_list', (expr: any) => {
  const result = getExprListSQL(expr.value);
  const { parentheses, separator } = expr;
  if (!parentheses && !separator) return result;
  const joinSymbol = separator || ', ';
  const str = result.join(joinSymbol);
  return parentheses ? `(${str})` : str;
});

registerHandler('unary_expr', (expr: any) => {
  const { operator, parentheses, expr: inner } = expr;
  const space = ['-', '+', '~', '!'].includes(operator) ? '' : ' ';
  const str = `${operator}${space}${exprToSQL(inner)}`;
  return parentheses ? `(${str})` : str;
});

registerHandler('var', (expr: any) => {
  const { prefix = '@', name, members, suffix } = expr;
  const varName = members && members.length > 0
    ? `${name}.${members.join('.')}`
    : name;
  let result = `${prefix || ''}${varName}`;
  if (suffix) result += suffix;
  return result;
});

registerHandler('interval', (expr: any) => {
  const { unit, expr: valExpr } = expr;
  return `INTERVAL ${literalToSQL(valExpr)} ${toUpper(unit)}`;
});
