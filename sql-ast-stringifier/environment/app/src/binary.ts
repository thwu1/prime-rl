import { exprToSQL, registerHandler } from './expr';
import { toUpper, hasVal } from './util';

function binaryToSQL(expr: any): string {
  let operator = expr.operator || expr.op;
  let rstr = exprToSQL(expr.right);
  let isBetween = false;

  if (Array.isArray(rstr)) {
    switch (operator) {
      case '=':
        operator = 'IN';
        break;
      case '!=':
        operator = 'NOT IN';
        break;
      case 'BETWEEN':
      case 'NOT BETWEEN':
        isBetween = true;
        rstr = `${rstr[0]} AND ${rstr[1]}`;
        break;
      default:
        break;
    }
    if (!isBetween) rstr = `(${rstr.join(', ')})`;
  }

  const escape = (expr.right && expr.right.escape) || {};
  const leftPart = Array.isArray(expr.left)
    ? expr.left.map(exprToSQL).join(', ')
    : exprToSQL(expr.left);

  const parts = [leftPart, operator, rstr];
  if (escape.type) parts.push(toUpper(escape.type), exprToSQL(escape.value));

  const str = parts.filter(hasVal).join(operator === '.' ? '' : ' ');
  return expr.parentheses ? `(${str})` : str;
}

registerHandler('binary_expr', binaryToSQL);

export { binaryToSQL };
