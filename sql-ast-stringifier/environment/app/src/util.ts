/**
 * Utility functions for SQL stringification.
 */

export function toUpper(val: any): string {
  if (!val) return '';
  return typeof val === 'string' ? val.toUpperCase() : '';
}

export function hasVal(val: any): boolean {
  return val !== null && val !== undefined && val !== '' && val !== false;
}

export function identifierToSql(ident: any): string {
  if (!ident) return '';
  if (typeof ident !== 'string') return String(ident);
  if (ident === '*') return '*';
  return `"${ident}"`;
}

export function literalToSQL(expr: any): string {
  if (expr === null || expr === undefined) return '';
  if (typeof expr === 'string') return expr;
  if (typeof expr === 'number') return String(expr);
  const { type, value } = expr;
  switch (type) {
    case 'number':
      return String(value);
    case 'string':
    case 'single_quote_string':
      return `'${value}'`;
    case 'double_quote_string':
      return `"${value}"`;
    case 'backticks_quote_string':
      return `\`${value}\``;
    case 'boolean':
    case 'bool':
      return String(value).toUpperCase();
    case 'null':
      return 'NULL';
    case 'star':
      return '*';
    case 'param':
      return `$${value}`;
    case 'origin':
      return String(value);
    case 'default':
      return value !== undefined && value !== null ? String(value) : 'DEFAULT';
    default:
      if (value !== undefined && value !== null) return String(value);
      return '';
  }
}

export function connector(keyword: string, str: string): string {
  if (!str) return '';
  return `${keyword} ${str}`;
}
