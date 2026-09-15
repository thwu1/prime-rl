import { tokenize } from './lexer';
import { parse } from './parser';
import { evaluate, Context } from './evaluator';

// Simple CLI: evaluates an expression passed as argument
const expr = process.argv[2];
if (!expr) {
  console.error('Usage: ts-node src/index.ts "<expression>"');
  process.exit(1);
}

const ctx: Context = { sidecar: {} };

try {
  const tokens = tokenize(expr);
  const ast = parse(tokens);
  const result = evaluate(ast, ctx);
  console.log(JSON.stringify(result));
} catch (e: any) {
  console.error(`Error: ${e.message}`);
  process.exit(1);
}
