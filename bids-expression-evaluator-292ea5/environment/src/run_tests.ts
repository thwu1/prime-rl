import * as fs from 'fs';
import * as yaml from 'js-yaml';
import { tokenize } from './lexer';
import { parse } from './parser';
import { evaluate, Context } from './evaluator';


interface TestCase {
  expression: string;
  result: any;
}

function isEqual(a: any, b: any): boolean {
  if (a === b) return true;
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  if (typeof a === 'number' && typeof b === 'number') {
    if (isNaN(a) && isNaN(b)) return true;
    return a === b;
  }
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((v: any, i: number) => isEqual(v, b[i]));
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (typeof a === 'object' && typeof b === 'object') {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    return keysA.every((k) => isEqual(a[k], b[k]));
  }
  return a === b;
}

function main(): void {
  const raw = fs.readFileSync('/app/expression_tests.yaml', 'utf8');
  const tests = yaml.load(raw) as TestCase[];

  const context: Context = {
    sidecar: {},
  };

  let passed = 0;
  let failed = 0;
  const errors: any[] = [];

  for (const tc of tests) {
    try {
      const tokens = tokenize(tc.expression);
      const ast = parse(tokens);
      const result = evaluate(ast, context);

      if (isEqual(result, tc.result)) {
        passed++;
      } else {
        failed++;
        errors.push({
          expression: tc.expression,
          expected: tc.result,
          got: result,
        });
      }
    } catch (e: any) {
      failed++;
      errors.push({
        expression: tc.expression,
        expected: tc.result,
        got: `ERROR: ${e.message}`,
      });
    }
  }

  const output = { total: passed + failed, passed, failed, errors };
  console.log(JSON.stringify(output));
}

main();
