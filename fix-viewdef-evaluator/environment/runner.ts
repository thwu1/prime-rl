
// Conformance test runner for SQL-on-FHIR ViewDefinition evaluator.
// Loads test fixture JSON files, runs evaluate() against each test,
// and outputs a JSON report of pass/fail results.

import * as fs from 'fs';
import * as path from 'path';
import { evaluate, getColumns } from './src/evaluator';

interface TestResult {
  file: string;
  title: string;
  passed: boolean;
  error?: string;
}

function deepEqual(a: any, b: any): boolean {
  if (a === b) return true;
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  if (typeof a !== typeof b) return false;
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) < 1e-10;
  }
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v: any, i: number) => deepEqual(v, b[i]));
  }
  if (typeof a === 'object') {
    const keysA = Object.keys(a).sort();
    const keysB = Object.keys(b).sort();
    if (!deepEqual(keysA, keysB)) return false;
    return keysA.every((k: string) => deepEqual(a[k], b[k]));
  }
  return false;
}

function runTests(): TestResult[] {
  const fixturesDir = path.join('/app', 'fixtures');
  const results: TestResult[] = [];

  const files = fs.readdirSync(fixturesDir)
    .filter((f: string) => f.endsWith('.json'))
    .sort();

  for (const file of files) {
    const content = fs.readFileSync(path.join(fixturesDir, file), 'utf-8');
    const suite = JSON.parse(content);
    const resources: any[] = suite.resources || [];

    for (const test of suite.tests) {
      const result: TestResult = {
        file,
        title: test.title,
        passed: false,
      };

      try {
        const view = test.view;
        if (!view) {
          result.error = 'Test has no view';
          results.push(result);
          continue;
        }

        const filteredResources = resources.filter(
          (r: any) => r.resourceType === view.resource
        );

        const rows = evaluate(view, filteredResources);

        if (test.expectError) {
          result.error = 'Expected error but evaluation succeeded';
          result.passed = false;
        } else if (test.expect !== undefined) {
          if (deepEqual(rows, test.expect)) {
            result.passed = true;
          } else {
            result.passed = false;
            result.error = `Row mismatch: expected ${JSON.stringify(test.expect).substring(0, 200)}, got ${JSON.stringify(rows).substring(0, 200)}`;
          }
        } else if (test.expectCount !== undefined) {
          if (rows.length === test.expectCount) {
            result.passed = true;
          } else {
            result.passed = false;
            result.error = `Count mismatch: expected ${test.expectCount}, got ${rows.length}`;
          }
        } else {
          result.passed = true;
        }
      } catch (e: any) {
        if (test.expectError) {
          result.passed = true;
        } else {
          result.passed = false;
          result.error = `Unexpected error: ${e.message}`;
        }
      }

      results.push(result);
    }
  }

  return results;
}

const results = runTests();
const passed = results.filter((r) => r.passed).length;
const failed = results.filter((r) => !r.passed).length;
const output = {
  total: results.length,
  passed,
  failed,
  results,
};

console.log(JSON.stringify(output));
if (failed > 0) {
  process.stderr.write(
    `\n${failed}/${results.length} tests failed:\n` +
    results
      .filter((r) => !r.passed)
      .map((r) => `  FAIL ${r.file}::${r.title} — ${r.error}`)
      .join('\n') +
    '\n'
  );
}
