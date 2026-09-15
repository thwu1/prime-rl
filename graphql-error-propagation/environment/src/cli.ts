
/**
 * CLI entry point for the GraphQL Value Completion Engine.
 *
 * Reads a JSON object from stdin with the shape:
 *   { "rootType": ObjectTypeDescriptor, "resolvedValues": Record<string, unknown> }
 *
 * Outputs a JSON ExecutionResponse to stdout.
 *
 * FieldError values in the resolved tree are represented as:
 *   { "__error__": "error message" }
 */

import { FieldError } from './types.js';
import { executeCompletion } from './engine.js';

function reviveFieldErrors(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value !== 'object') return value;
  if (Array.isArray(value)) {
    return value.map(reviveFieldErrors);
  }
  const obj = value as Record<string, unknown>;
  if (typeof obj['__error__'] === 'string') {
    return new FieldError(obj['__error__'] as string);
  }
  const result: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    result[k] = reviveFieldErrors(v);
  }
  return result;
}

async function main() {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf-8'));
  const rootType = input.rootType;
  const resolvedValues = reviveFieldErrors(input.resolvedValues) as Record<string, unknown>;
  const response = executeCompletion(rootType, resolvedValues);
  process.stdout.write(JSON.stringify(response) + '\n');
}

main().catch((err) => {
  process.stderr.write(String(err) + '\n');
  if (err instanceof Error && err.stack) {
    process.stderr.write(err.stack + '\n');
  }
  process.exit(1);
});
