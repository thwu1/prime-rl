
import { readFileSync } from 'fs';
import { resolveAll, DatasetNode } from './src/inheritance';

interface TestFile {
  path: string;
  expected_metadata: Record<string, unknown>;
  expected_sidecars: string[];
}

interface TestInput {
  tree: DatasetNode;
  test_files: TestFile[];
}

const inputPath = process.argv[2] || './spec/inheritance_tests.json';
const input = JSON.parse(readFileSync(inputPath, 'utf8')) as TestInput;

const results = resolveAll(input.tree, input.test_files.map(f => f.path));

interface TestResult {
  file_id: string;
  resolved_metadata: Record<string, unknown>;
  applied_sidecars: string[];
  expected_metadata: Record<string, unknown>;
  expected_sidecars: string[];
  metadata_match: boolean;
  sidecars_match: boolean;
  passed: boolean;
}

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
    const aKeys = Object.keys(aObj).sort();
    const bKeys = Object.keys(bObj).sort();
    if (aKeys.length !== bKeys.length) return false;
    return aKeys.every((k, i) => k === bKeys[i] && deepEqual(aObj[k], bObj[k]));
  }
  return false;
}

const output: TestResult[] = results.map((r, i) => {
  const tf = input.test_files[i];
  const metadataMatch = deepEqual(r.resolved_metadata, tf.expected_metadata);
  const sidecarsMatch = deepEqual(
    [...r.applied_sidecars].sort(),
    [...tf.expected_sidecars].sort()
  );
  return {
    file_id: r.file_id,
    resolved_metadata: r.resolved_metadata,
    applied_sidecars: r.applied_sidecars,
    expected_metadata: tf.expected_metadata,
    expected_sidecars: tf.expected_sidecars,
    metadata_match: metadataMatch,
    sidecars_match: sidecarsMatch,
    passed: metadataMatch && sidecarsMatch,
  };
});

console.log(JSON.stringify(output, null, 2));
