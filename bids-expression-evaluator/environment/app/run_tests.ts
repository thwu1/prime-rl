
import { readFileSync } from 'fs';
import yaml from 'js-yaml';
import { evaluateExpression } from './src/index';

interface TestCase {
  expression: string;
  result: unknown;
}

const testCases = yaml.load(
  readFileSync('./spec/expression_tests.yaml', 'utf8')
) as TestCase[];

const context: Record<string, unknown> = {
  sidecar: {},
};

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null) return a === b;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const aObj = a as Record<string, unknown>;
    const bObj = b as Record<string, unknown>;
    const aKeys = Object.keys(aObj);
    const bKeys = Object.keys(bObj);
    if (aKeys.length !== bKeys.length) return false;
    return aKeys.every((k) => deepEqual(aObj[k], bObj[k]));
  }
  return false;
}

interface TestResult {
  expression: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];

for (const tc of testCases) {
  try {
    const actual = evaluateExpression(tc.expression, context);
    const passed = deepEqual(actual, tc.result);
    results.push({
      expression: tc.expression,
      expected: tc.result,
      actual,
      passed,
    });
  } catch (err: unknown) {
    results.push({
      expression: tc.expression,
      expected: tc.result,
      actual: null,
      passed: false,
      error: (err as Error).message,
    });
  }
}

console.log(JSON.stringify(results, null, 2));
