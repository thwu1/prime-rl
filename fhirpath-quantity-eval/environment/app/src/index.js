'use strict';

const { parse } = require('./parser');
const { evaluate, formatResult } = require('./evaluator');

const expr = process.argv[2];
if (!expr) {
  process.stderr.write('Usage: node src/index.js "<expression>"\n');
  process.exit(1);
}

try {
  const ast = parse(expr);
  const result = evaluate(ast);
  console.log(formatResult(result));
} catch (e) {
  process.stderr.write('Error: ' + e.message + '\n');
  process.exit(1);
}
