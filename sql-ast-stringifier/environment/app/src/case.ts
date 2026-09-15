import { exprToSQL, registerHandler } from './expr';
import { hasVal } from './util';

function caseToSQL(expr: any): string {
  const { expr: switchExpr, args } = expr;
  const result: string[] = ['CASE'];

  if (switchExpr) result.push(exprToSQL(switchExpr));

  for (const arg of args) {
    if (arg.type === 'when') {
      result.push('WHEN', exprToSQL(arg.cond), 'THEN', exprToSQL(arg.result));
    } else if (arg.type === 'else') {
      result.push('ELSE', exprToSQL(arg.result));
    }
  }

  result.push('END');
  return result.filter(hasVal).join(' ');
}

registerHandler('case', caseToSQL);

export { caseToSQL };
