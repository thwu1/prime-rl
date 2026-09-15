/**
 * Function, cast, and aggregate stringification.
 */
import { exprToSQL, registerHandler } from './expr';
import { literalToSQL, toUpper, hasVal } from './util';
import { overToSQL } from './select';

function withinGroupToSQL(stmt: any): string {
  if (!stmt) return '';
  const { type, keyword, orderby } = stmt;
  const orderbyStr = orderby
    .map((item: any) => {
      const dir = item.type || 'ASC';
      return `${exprToSQL(item.expr)} ${dir}`;
    })
    .join(', ');
  return `${toUpper(type)} ${toUpper(keyword)} (ORDER BY ${orderbyStr})`;
}

function castToSQL(expr: any): string {
  const { keyword, expr: castExpr, symbol, target, parentheses } = expr;
  const exprStr = exprToSQL(castExpr);

  const targetParts = target.map((t: any) => {
    let str = t.dataType;
    if (t.length != null) {
      str += t.scale != null ? `(${t.length}, ${t.scale})` : `(${t.length})`;
    }
    if (t.suffix && t.suffix.length) {
      str += ' ' + t.suffix.map(literalToSQL).join(' ');
    }
    return str;
  });
  const targetStr = targetParts.join('');

  if (symbol === 'as') {
    return `${toUpper(keyword)}(${exprStr} AS ${targetStr})`;
  }

  // PostgreSQL :: cast syntax
  return `${targetStr}::${exprStr}`;
}

function funcToSQL(expr: any): string {
  const {
    args,
    name,
    over,
    within_group: withinGroup,
    parentheses,
  } = expr;
  const overStr = overToSQL(over);
  const withinGroupStr = withinGroupToSQL(withinGroup);

  const funcName = name.name.map(literalToSQL).join('.');
  const schemaStr = name.schema ? literalToSQL(name.schema) : '';
  const fullName = schemaStr ? `${schemaStr}.${funcName}` : funcName;

  if (!args) {
    return [fullName, withinGroupStr, overStr].filter(hasVal).join(' ');
  }

  const argsList = exprToSQL(args);
  const argsStr = Array.isArray(argsList) ? argsList.join(', ') : argsList;
  const str = `${fullName}(${argsStr})`;
  return [
    parentheses ? `(${str})` : str,
    withinGroupStr,
    overStr,
  ]
    .filter(hasVal)
    .join(' ');
}

function aggrToSQL(expr: any): string {
  const { name, args, over } = expr;
  const { expr: argExpr, distinct: distinctKw, orderby } = args;

  const parts: string[] = [];
  parts.push(exprToSQL(argExpr));

  if (orderby) {
    const orderbyStr = orderby
      .map((item: any) => {
        const dir = item.type || 'ASC';
        return `${exprToSQL(item.expr)} ${dir}`;
      })
      .join(', ');
    parts.push(`ORDER BY ${orderbyStr}`);
  }

  const overStr = overToSQL(over);
  const result = `${name.toUpperCase()}(${parts.join(' ')})`;
  return [result, overStr].filter(hasVal).join(' ');
}

registerHandler('cast', castToSQL);
registerHandler('function', funcToSQL);
registerHandler('aggr_func', aggrToSQL);

export { castToSQL, funcToSQL, aggrToSQL, withinGroupToSQL };
