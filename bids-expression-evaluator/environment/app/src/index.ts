
import { parse } from './parser';
import { evaluate, Context } from './evaluator';

export function evaluateExpression(expression: string, context: Context = {}): unknown {
  const ast = parse(expression);
  return evaluate(ast, context);
}

export { parse } from './parser';
export { evaluate } from './evaluator';
export type { Context } from './evaluator';
export { tokenize } from './lexer';
