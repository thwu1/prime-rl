import * as fs from 'fs';
import * as path from 'path';
import { evaluate } from './evaluator';
import { TestFile, Row } from './types';

function isEqual(a: any, b: any): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return (
      a.length === b.length &&
      a.every((val: any, index: number) => isEqual(val, b[index]))
    );
  }
  return a === b;
}

function canonicalize(arr: Row[]): Row[] {
  if (!Array.isArray(arr)) {
    throw new Error('Expected array, got ' + JSON.stringify(arr));
  }
  return [...arr].sort((a, b) => {
    const keysA = Object.keys(a).sort();
    const keysB = Object.keys(b).sort();
    for (let i = 0; i < Math.min(keysA.length, keysB.length); i++) {
      const va = a[keysA[i]];
      const vb = b[keysB[i]];
      if (va === null && vb !== null) return -1;
      if (va !== null && vb === null) return 1;
      if (va < vb) return -1;
      if (va > vb) return 1;
    }
    return keysA.length - keysB.length;
  });
}

function arraysMatch(
  actual: Row[],
  expected: Row[]
): { passed: boolean; message?: string } {
  const a = canonicalize(actual);
  const e = canonicalize(expected);

  if (a.length !== e.length) {
    return {
      passed: false,
      message: `Array lengths differ: got ${a.length}, expected ${e.length}`,
    };
  }

  for (let i = 0; i < a.length; i++) {
    const obj1 = a[i];
    const obj2 = e[i];
    const keys1 = Object.keys(obj1).sort();
    const keys2 = Object.keys(obj2).sort();

    if (keys1.length !== keys2.length) {
      return {
        passed: false,
        message: `Objects at index ${i} have different key counts: got [${keys1}], expected [${keys2}]`,
      };
    }

    for (const key of keys2) {
      if (!isEqual(obj1[key], obj2[key])) {
        return {
          passed: false,
          message: `Mismatch at index ${i} for key "${key}": got ${JSON.stringify(
            obj1[key]
          )}, expected ${JSON.stringify(obj2[key])}`,
        };
      }
    }
  }

  return { passed: true };
}

function main(): void {
  const args = process.argv.slice(2);

  if (args.length < 2 || args[0] !== 'run') {
    console.error(
      'Usage: ts-node src/cli.ts run <testfile1.json> [testfile2.json ...]'
    );
    process.exit(1);
  }

  const testFiles = args.slice(1);
  const report: any = {
    total: 0,
    passed: 0,
    failed: 0,
    errors: 0,
    results: [],
  };

  for (const file of testFiles) {
    if (!fs.existsSync(file)) {
      console.error(`File not found: ${file}`);
      continue;
    }

    const content: TestFile = JSON.parse(fs.readFileSync(file, 'utf-8'));
    const resources = content.resources;
    const fileName = path.basename(file);

    for (const testCase of content.tests) {
      report.total++;

      try {
        if (testCase.expectError) {
          try {
            evaluate(testCase.view, resources);
            report.failed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'FAIL',
              message: 'Expected error but none was thrown',
            });
          } catch (e: any) {
            report.passed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'PASS',
            });
          }
        } else if (testCase.expect !== undefined) {
          const result = evaluate(testCase.view, resources);
          const match = arraysMatch(result, testCase.expect);

          if (match.passed) {
            report.passed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'PASS',
            });
          } else {
            report.failed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'FAIL',
              message: match.message,
              expected: testCase.expect,
              actual: result,
            });
          }
        } else if (testCase.expectCount !== undefined) {
          const result = evaluate(testCase.view, resources);
          if (result.length === testCase.expectCount) {
            report.passed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'PASS',
            });
          } else {
            report.failed++;
            report.results.push({
              file: fileName,
              title: testCase.title,
              status: 'FAIL',
              message: `Expected ${testCase.expectCount} rows, got ${result.length}`,
            });
          }
        }
      } catch (e: any) {
        report.errors++;
        report.results.push({
          file: fileName,
          title: testCase.title,
          status: 'ERROR',
          message: e.message || String(e),
        });
      }
    }
  }

  console.log(JSON.stringify(report, null, 2));

  if (report.failed > 0 || report.errors > 0) {
    process.exit(1);
  }
}

main();
